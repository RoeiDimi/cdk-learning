import json
import os
import logging
from typing import List, Dict, Any, Optional
import boto3
from boto3.dynamodb.conditions import Key, Attr
from botocore.exceptions import ClientError

logger = logging.getLogger()
logger.setLevel(logging.INFO)

dynamo = boto3.resource("dynamodb")

TABLE_NAME = os.getenv("CONNECTIONS_TABLE_NAME") or os.getenv("CONNECTIONS_TABLE") or os.getenv("TABLE_NAME")
CONNECTION_ID_KEY = os.getenv("CONNECTION_ID_KEY", "connectionId")
USER_ID_ATTR = os.getenv("USER_ID_ATTR", "userId")
USER_GSI_NAME = os.getenv("USER_GSI_NAME")  # optional: GSI with partition key = USER_ID_ATTR

if not TABLE_NAME:
    raise RuntimeError("Missing env var: CONNECTIONS_TABLE or TABLE_NAME")

table = dynamo.Table(TABLE_NAME)


def _response(status: int, body: Dict[str, Any]):
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body),
    }


def _get_json_body(event: Dict[str, Any]) -> Dict[str, Any]:
    body = event.get("body")
    if not body:
        return {}
    if isinstance(body, dict):
        return body
    try:
        return json.loads(body)
    except Exception:
        return {}


def _extract_connection_id(event: Dict[str, Any], body: Dict[str, Any]) -> Optional[str]:
    # WebSocket $disconnect or custom route
    rc = event.get("requestContext") or {}
    if rc.get("connectionId"):
        return rc["connectionId"]

    # HTTP API: path, query, or body
    path_params = event.get("pathParameters") or {}
    if path_params.get("connectionId"):
        return path_params["connectionId"]

    query = event.get("queryStringParameters") or {}
    if query.get("connectionId"):
        return query["connectionId"]

    if body.get("connectionId"):
        return body["connectionId"]

    return None


def _extract_user_id(event: Dict[str, Any], body: Dict[str, Any]) -> Optional[str]:
    path_params = event.get("pathParameters") or {}
    if path_params.get("userId"):
        return path_params["userId"]

    query = event.get("queryStringParameters") or {}
    if query.get("userId"):
        return query["userId"]

    if body.get("userId"):
        return body["userId"]

    return None


def _delete_by_connection_id(connection_id: str) -> bool:
    try:
        table.delete_item(
            Key={CONNECTION_ID_KEY: connection_id},
            ConditionExpression=Attr(CONNECTION_ID_KEY).exists(),
        )
        return True
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            # Item already missing; treat as success (idempotent)
            logger.info("Connection %s not found; nothing to delete.", connection_id)
            return False
        logger.exception("Failed to delete connectionId=%s", connection_id)
        raise


def _batch_delete(keys: List[Dict[str, Any]]) -> None:
    if not keys:
        return
    with table.batch_writer() as batch:
        for key in keys:
            batch.delete_item(Key=key)


def _find_keys_by_user_id(user_id: str) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []

    if USER_GSI_NAME:
        # Query the GSI for fast lookup
        resp = table.query(
            IndexName=USER_GSI_NAME,
            KeyConditionExpression=Key(USER_ID_ATTR).eq(user_id),
        )
        items.extend(resp.get("Items", []))
        while "LastEvaluatedKey" in resp:
            resp = table.query(
                IndexName=USER_GSI_NAME,
                KeyConditionExpression=Key(USER_ID_ATTR).eq(user_id),
                ExclusiveStartKey=resp["LastEvaluatedKey"],
            )
            items.extend(resp.get("Items", []))
    else:
        # Fallback: scan (acceptable for small tables)
        resp = table.scan(
            FilterExpression=Attr(USER_ID_ATTR).eq(user_id),
            ProjectionExpression=CONNECTION_ID_KEY,
        )
        items.extend(resp.get("Items", []))
        while "LastEvaluatedKey" in resp:
            resp = table.scan(
                FilterExpression=Attr(USER_ID_ATTR).eq(user_id),
                ProjectionExpression=CONNECTION_ID_KEY,
                ExclusiveStartKey=resp["LastEvaluatedKey"],
            )
            items.extend(resp.get("Items", []))

    keys: List[Dict[str, Any]] = []
    for it in items:
        if CONNECTION_ID_KEY in it:
            keys.append({CONNECTION_ID_KEY: it[CONNECTION_ID_KEY]})
    return keys


def handler(event, context):
    try:
        body = _get_json_body(event)

        # Prefer explicit connection deletion when present
        connection_id = _extract_connection_id(event, body)
        user_id = _extract_user_id(event, body)

        if connection_id:
            deleted = _delete_by_connection_id(connection_id)
            return _response(200, {
                "message": "Connection deleted",
                "connectionId": connection_id,
                "deleted": deleted,
            })

        if user_id:
            keys = _find_keys_by_user_id(user_id)
            if not keys:
                return _response(200, {
                    "message": "No connections found for user",
                    "userId": user_id,
                    "deletedCount": 0,
                })
            # Batch delete in chunks of 25
            count = 0
            for i in range(0, len(keys), 25):
                chunk = keys[i:i+25]
                _batch_delete(chunk)
                count += len(chunk)
            return _response(200, {
                "message": "User connections deleted",
                "userId": user_id,
                "deletedCount": count,
            })

        return _response(400, {
            "error": "Missing connectionId or userId",
            "hint": "Provide connectionId (WS $disconnect auto-provides it) or userId to delete all connections for a user.",
        })

    except Exception as e:
        logger.exception("Unhandled error")
        return _response(500, {"error": "Internal Server Error", "detail": str(e)})

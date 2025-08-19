import json
import logging
import os
from typing import Any, Dict, Iterable, List, Optional
import boto3
from botocore.exceptions import ClientError

# Environment:
# - CONNECTIONS_TABLE_NAME: DynamoDB table that stores active WebSocket connections
# - CONNECTION_ID_ATTR: Attribute name for the connection id (default: "connectionId")
# - WEBSOCKET_API_ENDPOINT: Full endpoint for apigatewaymanagementapi, e.g. https://{apiId}.execute-api.{region}.amazonaws.com/{stage}
#   Alternatively, provide APIGW_DOMAIN_NAME and APIGW_STAGE to construct the endpoint.
# - LOG_LEVEL: optional logging level (e.g. INFO, DEBUG)

logger = logging.getLogger(__name__)
logger.setLevel(os.getenv("LOG_LEVEL", "INFO"))

dynamodb = boto3.resource("dynamodb")
apigw_mgmt_client = None


def _resolve_ws_endpoint() -> str:
    endpoint = os.getenv("WEBSOCKET_API_ENDPOINT")
    if endpoint:
        return endpoint.rstrip("/")
    domain = os.getenv("APIGW_DOMAIN_NAME")  # e.g. abcd1234.execute-api.us-east-1.amazonaws.com
    stage = os.getenv("APIGW_STAGE")
    if not (domain and stage):
        raise RuntimeError(
            "Missing WEBSOCKET_API_ENDPOINT or (APIGW_DOMAIN_NAME and APIGW_STAGE) environment variables."
        )
    if domain.startswith("https://") or domain.startswith("http://"):
        base = domain
    else:
        base = f"https://{domain}"
    return f"{base.rstrip('/')}/{stage.lstrip('/')}"


def _apigw_client():
    global apigw_mgmt_client
    if apigw_mgmt_client is None:
        endpoint = _resolve_ws_endpoint()
        # apigatewaymanagementapi requires the endpoint_url to include the stage
        apigw_mgmt_client = boto3.client("apigatewaymanagementapi", endpoint_url=endpoint)
        logger.debug("Initialized apigatewaymanagementapi client with endpoint: %s", endpoint)
    return apigw_mgmt_client


def _scan_all_connections(
    table_name: str,
    connection_id_attr: str = "connectionId",
    projection: Optional[str] = None,
) -> List[str]:
    table = dynamodb.Table(table_name)
    scan_kwargs: Dict[str, Any] = {}
    if projection:
        scan_kwargs["ProjectionExpression"] = projection

    connection_ids: List[str] = []
    last_evaluated_key = None

    while True:
        if last_evaluated_key:
            scan_kwargs["ExclusiveStartKey"] = last_evaluated_key
        resp = table.scan(**scan_kwargs)
        items = resp.get("Items", [])
        for item in items:
            cid = item.get(connection_id_attr)
            if cid:
                connection_ids.append(cid)
        last_evaluated_key = resp.get("LastEvaluatedKey")
        if not last_evaluated_key:
            break

    return connection_ids


def _delete_connection_record(table_name: str, connection_id: str, connection_id_attr: str = "connectionId") -> None:
    table = dynamodb.Table(table_name)
    try:
        table.delete_item(Key={connection_id_attr: connection_id})
    except ClientError as e:
        logger.warning("Failed to delete stale connection %s from table %s: %s", connection_id, table_name, e)


def _extract_sns_messages(event: Dict[str, Any]) -> List[str]:
    messages: List[str] = []
    for record in event.get("Records", []):
        if record.get("EventSource") == "aws:sns" or record.get("EventSource") == "aws:sns":
            sns = record.get("Sns") or {}
            msg = sns.get("Message")
            if msg is None:
                continue
            # Ensure string payload for WebSocket. If it's JSON, keep as is; otherwise stringify.
            if isinstance(msg, (dict, list)):
                messages.append(json.dumps(msg))
            else:
                messages.append(str(msg))
    if not messages and isinstance(event, dict) and "message" in event:
        messages.append(json.dumps(event["message"]) if isinstance(event["message"], (dict, list)) else str(event["message"]))
    return messages


def _post_to_connection(connection_id: str, data: bytes) -> Optional[int]:
    try:
        _apigw_client().post_to_connection(ConnectionId=connection_id, Data=data)
        return 200
    except _apigw_client().exceptions.GoneException:
        return 410
    except ClientError as e:
        logger.error("Failed to post to connection %s: %s", connection_id, e)
        return None


def handler(event, context):
    table_name = os.getenv("CONNECTIONS_TABLE_NAME")
    if not table_name:
        raise RuntimeError("CONNECTIONS_TABLE_NAME is required")
    connection_id_attr = os.getenv("CONNECTION_ID_ATTR", "connectionId")

    messages = _extract_sns_messages(event)
    if not messages:
        logger.info("No SNS messages to broadcast.")
        return {"statusCode": 200, "body": json.dumps({"broadcasted": 0, "connections": 0})}

    payloads = [m.encode("utf-8") for m in messages]

    # Fetch all current connections
    connections = _scan_all_connections(
        table_name=table_name,
        connection_id_attr=connection_id_attr,
        projection=connection_id_attr,
    )

    if not connections:
        logger.info("No active connections found.")
        return {"statusCode": 200, "body": json.dumps({"broadcasted": 0, "connections": 0})}

    total_attempts = 0
    total_sent = 0
    stale: List[str] = []

    for connection_id in connections:
        for data in payloads:
            total_attempts += 1
            result = _post_to_connection(connection_id, data)
            if result == 200:
                total_sent += 1
            elif result == 410:
                stale.append(connection_id)
                # No need to attempt further messages for this stale connection
                break

    # Cleanup stale connections
    if stale:
        unique_stale = sorted(set(stale))
        for cid in unique_stale:
            _delete_connection_record(table_name, cid, connection_id_attr)
        logger.info("Removed %d stale connections", len(unique_stale))

    body = {
        "connections": len(connections),
        "messagesInEvent": len(messages),
        "attempts": total_attempts,
        "sent": total_sent,
        "staleRemoved": len(set(stale)),
    }
    return {"statusCode": 200, "body": json.dumps(body)}
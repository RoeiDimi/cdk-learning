import os
import json
import logging
import decimal
from typing import Any, Dict, List, Optional
import boto3
from botocore.exceptions import BotoCoreError, ClientError
from response_utils import (
    create_response, success_response, internal_server_error_response,
    handle_cors_preflight, log_and_return_error
)
from auth_utils import validate_jwt_token, extract_user_info, extract_token_from_event

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Resolve table name from environment (support a few common keys)
_TABLE_ENV_KEYS = ["DDB_MESSAGES_TABLE_NAME", "MESSAGES_TABLE_NAME", "DDB_MESSAGES_TABLE"]
TABLE_NAME: Optional[str] = next((os.getenv(k) for k in _TABLE_ENV_KEYS if os.getenv(k)), None)

dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(TABLE_NAME) if TABLE_NAME else None


def _decimal_to_native(value: Any) -> Any:
    if isinstance(value, list):
        return [_decimal_to_native(v) for v in value]
    if isinstance(value, dict):
        return {k: _decimal_to_native(v) for k, v in value.items()}
    if isinstance(value, decimal.Decimal):
        return int(value) if value % 1 == 0 else float(value)
    return value

def _scan_all_messages(tbl) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    scan_kwargs: Dict[str, Any] = {}
    while True:
        resp = tbl.scan(**scan_kwargs)
        items.extend(resp.get("Items", []))
        last_key = resp.get("LastEvaluatedKey")
        if not last_key:
            break
        scan_kwargs["ExclusiveStartKey"] = last_key
    return items

def _get_http_method(event: Dict[str, Any]) -> str:
    # REST API
    if "httpMethod" in event:
        return event["httpMethod"]
    # HTTP API v2
    return event.get("requestContext", {}).get("http", {}).get("method", "")


def handler(event, context):
    method = _get_http_method(event)

    if method == "OPTIONS":
        return handle_cors_preflight()

    if method != "GET":
        return create_response(405, {"error": "Method Not Allowed"})

    # Add authentication to ensure only authenticated users can fetch messages
    try:
        token = extract_token_from_event(event)
        if not token:
            return create_response(401, {"error": "Missing authentication token"})
        
        token_payload = validate_jwt_token(token)
        user_info = extract_user_info(token_payload)
        
        if not user_info:
            return create_response(401, {"error": "Invalid authentication token"})
            
    except Exception as e:
        logger.warning("Authentication failed: %s", str(e))
        return create_response(401, {"error": "Authentication failed"})

    if table is None:
        logger.error("DynamoDB table name not configured. Checked env keys: %s", _TABLE_ENV_KEYS)
        return internal_server_error_response("Server misconfiguration: table name not set")

    try:
        raw_items = _scan_all_messages(table)
        items = _decimal_to_native(raw_items)

        # Optional: keep response stable by sorting if a timestamp-like key exists
        # Try common keys; ignore if absent
        for ts_key in ("createdAt", "timestamp", "ts"):
            if items and all(isinstance(i, dict) and ts_key in i for i in items):
                try:
                    items.sort(key=lambda x: x.get(ts_key))
                except Exception:
                    pass
                break

        return success_response({"messages": items, "count": len(items)})
    except (ClientError, BotoCoreError) as e:
        logger.exception("Failed to read messages from DynamoDB: %s", e)
        return log_and_return_error("Failed to read messages", e)

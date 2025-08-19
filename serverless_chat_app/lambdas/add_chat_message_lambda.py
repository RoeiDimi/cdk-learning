import json
import os
import uuid
import logging
from datetime import datetime, timezone
from typing import Union, Tuple, Optional
import boto3
from botocore.exceptions import ClientError
from auth_utils import validate_jwt_token, extract_user_info, extract_token_from_event, create_auth_response
from response_utils import (
    create_response, success_response, bad_request_response, 
    unauthorized_response, internal_server_error_response, 
    conflict_response, handle_cors_preflight, log_and_return_error
)

# Configure logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Resolve DynamoDB table from environment
_TABLE_ENV_KEYS = ("CHAT_MESSAGES_TABLE", "TABLE_NAME", "DYNAMODB_TABLE")
def _resolve_table_name() -> str:
    for k in _TABLE_ENV_KEYS:
        v = os.getenv(k)
        if v:
            return v
    raise RuntimeError(
        f"Missing DynamoDB table env var. Set one of: {', '.join(_TABLE_ENV_KEYS)}"
    )

_dynamodb = boto3.resource("dynamodb")
_TABLE = _dynamodb.Table(_resolve_table_name())
_sns = boto3.client("sns")


def _parse_body(event) -> Tuple[Optional[dict], Optional[str]]:
    # Support API Gateway proxy events and direct invocation
    if isinstance(event, dict) and "body" in event:
        raw = event["body"]
        if raw is None:
            return None, "Request body is required"
        if isinstance(raw, str):
            try:
                return json.loads(raw), None
            except json.JSONDecodeError:
                return None, "Request body must be valid JSON"
        if isinstance(raw, dict):
            return raw, None
        return None, "Unsupported body type"
    if isinstance(event, dict):
        # Treat the entire event as payload for non-API Gateway invocations
        return event, None
    return None, "Unsupported event format"

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

def handler(event, context):
    # Handle CORS preflight
    cors_response = handle_cors_preflight(event)
    if cors_response:
        return cors_response

    # Authenticate user first
    try:
        token = extract_token_from_event(event)
        if not token:
            return unauthorized_response("Authentication token required")
        
        # Validate JWT token
        token_payload = validate_jwt_token(token)
        user_info = extract_user_info(token_payload)
        
        # Extract authenticated user ID
        authenticated_user_id = user_info.get("username") or user_info.get("sub")
        if not authenticated_user_id:
            return unauthorized_response("Invalid token: missing user identification")
            
    except Exception as e:
        logger.warning(f"Authentication failed: {str(e)}")
        return unauthorized_response("Authentication failed")

    payload, err = _parse_body(event)
    if err:
        return bad_request_response(err)

    # Validate required fields
    errors = []
    sender_id = payload.get("senderId")
    content = payload.get("content")

    if not isinstance(sender_id, str) or not sender_id.strip():
        errors.append("senderId is required and must be a non-empty string")
    if not isinstance(content, str) or not content.strip():
        errors.append("content is required and must be a non-empty string")
    
    # Ensure the sender_id matches the authenticated user
    if sender_id.strip() != authenticated_user_id:
        errors.append("senderId must match the authenticated user")

    # Simple content length guard (adjust as needed)
    if isinstance(content, str) and len(content) > 5000:
        errors.append("content must be 5000 characters or fewer")

    if errors:
        return bad_request_response("Validation failed", errors)

    # Normalize fields
    message_id = payload.get("messageId")
    if not isinstance(message_id, str) or not message_id.strip():
        message_id = uuid.uuid4().hex

    created_at = payload.get("createdAt")
    if not isinstance(created_at, str) or not created_at.strip():
        created_at = _now_iso()

    # Optional extra attributes (must be JSON-serializable)
    # e.g., threadId, replyToMessageId, attachments, metadata
    item = {
        "messageId": message_id.strip(),
        "senderId": authenticated_user_id,  # Use authenticated user ID instead of client-provided
        "content": content.strip(),
        "createdAt": created_at,
    }

    # Whitelist optional simple fields if present
    for key in ("threadId", "replyToMessageId"):
        val = payload.get(key)
        if isinstance(val, str) and val.strip():
            item[key] = val.strip()

    # Allow metadata dict if provided
    meta = payload.get("metadata")
    if isinstance(meta, dict):
        item["metadata"] = meta

    try:
        # Prevent accidental overwrite of an existing message
        _TABLE.put_item(
            Item=item,
            ConditionExpression="attribute_not_exists(messageId)",
        )

        # Publish message to SNS topic
        _sns.publish(
            TopicArn=os.environ["CHAT_MESSAGES_TOPIC_ARN"],
            Message=json.dumps({"message": item}),
        )
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "")
        if code == "ConditionalCheckFailedException":
            logger.info("Duplicate message: messageId=%s", item["messageId"])
            return conflict_response("Message already exists", {"messageId": item["messageId"]})
        return log_and_return_error(e, "add_chat_message", 500, "Failed to store message")

    return success_response({"message": item}, "Message sent successfully")

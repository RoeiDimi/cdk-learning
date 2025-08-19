import json
import os
import time
import logging
from typing import Dict, Any, Optional
import boto3
from botocore.exceptions import ClientError
from auth_utils import validate_jwt_token, extract_user_info

# Environment
TABLE_NAME = os.getenv("CONNECTIONS_TABLE_NAME", "")
PRIMARY_KEY_NAME = os.getenv("PRIMARY_KEY_NAME", "connectionId")
TTL_ATTRIBUTE_NAME = os.getenv("TTL_ATTRIBUTE_NAME", "ttl")
TTL_DAYS = int(os.getenv("TTL_DAYS", "30"))

# Init
dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(TABLE_NAME) if TABLE_NAME else None

logger = logging.getLogger()
logger.setLevel(logging.INFO)

def handler(event, context):
    """Handle WebSocket $connect event"""
    if not table:
        logger.error("TABLE_NAME not configured")
        return {"statusCode": 500, "body": "Configuration error"}
    
    # Extract connection ID from WebSocket event
    connection_id = event["requestContext"]["connectionId"]
    
    # Extract token from query parameters
    query_params = event.get("queryStringParameters") or {}
    token = query_params.get("token")
    
    if not token:
        logger.warning(f"WebSocket connect without token: {connection_id}")
        return {"statusCode": 401, "body": "Missing token"}
    
    # Validate the token using auth_utils
    try:
        token_payload = validate_jwt_token(token)
        user_info = extract_user_info(token_payload)
        user_id = user_info.get("username") or user_info.get("sub")
        
        if not user_id:
            logger.warning(f"WebSocket connect with invalid token (no user ID): {connection_id}")
            return {"statusCode": 401, "body": "Invalid token: missing user identification"}
            
    except Exception as e:
        logger.warning(f"WebSocket connect with invalid token: {connection_id}, error: {str(e)}")
        return {"statusCode": 401, "body": "Invalid token"}
    
    # Store connection in DynamoDB
    now = int(time.time())
    ttl = now + TTL_DAYS * 86400
    
    try:
        table.put_item(
            Item={
                PRIMARY_KEY_NAME: connection_id,
                "userId": user_id,
                "connectedAt": now,
                "lastSeen": now,
                TTL_ATTRIBUTE_NAME: ttl
            }
        )
        
        logger.info(f"WebSocket connection stored: {connection_id} -> {user_id}")
        return {"statusCode": 200, "body": "Connected"}
        
    except ClientError as e:
        logger.exception(f"Failed to store connection {connection_id}")
        return {"statusCode": 500, "body": "Connection failed"}

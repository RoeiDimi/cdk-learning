import json
import os
import time
import base64
import logging
from typing import Any, Dict, Optional
import boto3
from botocore.exceptions import ClientError
from response_utils import (
    create_response, success_response, internal_server_error_response,
    handle_cors_preflight, log_and_return_error
)
from auth_utils import validate_jwt_token, extract_user_info

# Environment
TABLE_NAME = os.getenv("CONNECTIONS_TABLE_NAME", "")
PRIMARY_KEY_NAME = os.getenv("PRIMARY_KEY_NAME", "connectionId")
TTL_ATTRIBUTE_NAME = os.getenv("TTL_ATTRIBUTE_NAME", "ttl")
TTL_DAYS = int(os.getenv("TTL_DAYS", "30"))

# WebSocket environment variables
WEBSOCKET_API_ID = os.getenv("WEBSOCKET_API_ID", "")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
WEBSOCKET_STAGE = os.getenv("WEBSOCKET_STAGE", "prod")
USER_POOL_ID = os.getenv("COGNITO_USER_POOL_ID", "")

# Init
dynamodb = boto3.resource("dynamodb")
cognito_client = boto3.client("cognito-idp")
table = dynamodb.Table(TABLE_NAME) if TABLE_NAME else None

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Add CLIENT_ID environment variable for Cognito authentication
USER_POOL_CLIENT_ID = os.getenv("USER_POOL_CLIENT_ID", "")



def _safe_json_loads(s: Optional[str], is_b64: bool = False) -> Dict[str, Any]:
    if not s:
        return {}
    try:
        payload = base64.b64decode(s) if is_b64 else s.encode("utf-8")
        return json.loads(payload)
    except Exception:
        return {}

def _lower_headers(event: Dict[str, Any]) -> Dict[str, str]:
    headers = event.get("headers") or {}
    return {str(k).lower(): str(v) for k, v in headers.items()}

def _get_websocket_url() -> str:
    """Generate WebSocket URL"""
    if WEBSOCKET_API_ID:
        return f"wss://{WEBSOCKET_API_ID}.execute-api.{AWS_REGION}.amazonaws.com/{WEBSOCKET_STAGE}"
    return ""

def _extract_connection_id(event: Dict[str, Any], body: Dict[str, Any]) -> Optional[str]:
    # Query string
    q = event.get("queryStringParameters") or {}
    if q.get("connectionId"):
        return str(q["connectionId"])

    # Body
    for k in ("connectionId", "connection_id", "connId"):
        if body.get(k):
            return str(body[k])

    return None

def _extract_user_id(event: Dict[str, Any], body: Dict[str, Any]) -> Optional[str]:
    # Cognito (REST API)
    claims = (event.get("requestContext") or {}).get("authorizer", {}).get("claims") or {}
    for k in ("sub", "username", "cognito:username", "user_id"):
        if claims.get(k):
            return str(claims[k])

    # HTTP API JWT authorizer
    jwt_auth = (event.get("requestContext") or {}).get("authorizer", {}).get("jwt") or {}
    jwt_claims = jwt_auth.get("claims") or {}
    for k in ("sub", "username", "cognito:username", "user_id"):
        if jwt_claims.get(k):
            return str(jwt_claims[k])

    # Custom authorizer lambda context
    lam = (event.get("requestContext") or {}).get("authorizer", {}).get("lambda") or {}
    for k in ("userId", "user_id", "sub"):
        if lam.get(k):
            return str(lam[k])

    # Body fallback
    for k in ("userId", "user_id"):
        if body.get(k):
            return str(body[k])

    return None

def authenticate_with_cognito(username: str, password: str) -> Dict[str, Any]:
    """Authenticate user with Cognito using username/password"""
    if not USER_POOL_CLIENT_ID:
        raise ValueError("USER_POOL_CLIENT_ID not configured")
    
    try:
        response = cognito_client.admin_initiate_auth(
            UserPoolId=USER_POOL_ID,
            ClientId=USER_POOL_CLIENT_ID,
            AuthFlow='ADMIN_NO_SRP_AUTH',
            AuthParameters={
                'USERNAME': username,
                'PASSWORD': password
            }
        )
        
        if 'AuthenticationResult' in response:
            return response['AuthenticationResult']
        else:
            raise ValueError("Authentication failed - no result returned")
            
    except cognito_client.exceptions.NotAuthorizedException:
        raise ValueError("Invalid username or password")
    except cognito_client.exceptions.UserNotConfirmedException:
        raise ValueError("User account not confirmed")
    except cognito_client.exceptions.UserNotFoundException:
        raise ValueError("User not found")
    except Exception as e:
        raise ValueError(f"Authentication failed: {str(e)}")

def handler(event, context):
    """Handle HTTP login request with username/password authentication"""
    
    # Handle CORS preflight
    if event.get('httpMethod') == 'OPTIONS':
        return handle_cors_preflight()
    
    if not table:
        return internal_server_error_response("TABLE_NAME not configured")

    try:
        body = _safe_json_loads(event.get("body"), bool(event.get("isBase64Encoded")))
        now = int(time.time())
        ttl = now + TTL_DAYS * 86400

        # Extract username and password from request body
        username = body.get("username") or body.get("userName")
        password = body.get("password")

        if not username:
            return create_response(400, {"error": "Username is required"})

        if not password:
            return create_response(400, {"error": "Password is required"})

        # Authenticate with Cognito
        try:
            auth_result = authenticate_with_cognito(username, password)
            id_token = auth_result.get('IdToken')
            access_token = auth_result.get('AccessToken')
            
            if not id_token:
                return internal_server_error_response("No ID token received from Cognito")
            
            # Decode the ID token to get user info using centralized auth utils
            payload = validate_jwt_token(id_token)
            user_info = extract_user_info(payload)
            user_id = user_info.get("user_id") or user_info.get("username") or username
            email = user_info.get("email")
            
        except ValueError as e:
            logger.warning(f"Authentication failed: {str(e)}")
            return create_response(401, {"error": f"Authentication failed: {str(e)}"})

        connection_id = _extract_connection_id(event, body)

        # For HTTP login, connection_id is optional - mainly for tracking login sessions
        if connection_id:
            # Additional metadata
            headers = _lower_headers(event)
            user_agent = headers.get("user-agent")
            ip = ((event.get("requestContext") or {}).get("http") or {}).get("sourceIp") or \
                 ((event.get("requestContext") or {}).get("identity") or {}).get("sourceIp")

            key = {PRIMARY_KEY_NAME: connection_id}

            update_expr_parts = [
                "SET userId = :uid",
                "lastLoginAt = :now",
                "updatedAt = :now",
                f"{TTL_ATTRIBUTE_NAME} = :ttl",
            ]
            expr_attr_values = {
                ":uid": user_id,
                ":now": now,
                ":ttl": ttl,
                ":one": 1,
            }
            expr_attr_names = {}

            if email:
                update_expr_parts.append("email = :email")
                expr_attr_values[":email"] = email
            if user_agent:
                update_expr_parts.append("userAgent = :ua")
                expr_attr_values[":ua"] = user_agent
            if ip:
                update_expr_parts.append("sourceIp = :ip")
                expr_attr_values[":ip"] = ip

            update_expr = " ".join(update_expr_parts) + " ADD loginCount :one"

            try:
                table.update_item(
                    Key=key,
                    UpdateExpression=update_expr,
                    ExpressionAttributeValues=expr_attr_values,
                    ExpressionAttributeNames=expr_attr_names or None,
                    ReturnValues="UPDATED_NEW",
                )
            except ClientError as e:
                logger.exception("DynamoDB update failed")
                return log_and_return_error("DynamoDB update failed", e)

        # Note: Messages are fetched separately via /getStoredMessages endpoint
        # This keeps login focused on authentication only
        
        # Generate WebSocket URL
        ws_url = _get_websocket_url()

        return success_response({
            "ok": True,
            "message": "Login successful",
            "userId": user_id,
            "username": username,
            "email": email,
            "connectionId": connection_id,
            "ttl": ttl,
            "token": id_token,  # Return the ID token for frontend to use
            "wsUrl": ws_url,
            "websocketUrl": ws_url
            # Note: Messages are fetched separately via /getStoredMessages endpoint
        })

    except Exception as e:
        logger.exception("Unexpected error in login handler")
        return log_and_return_error("Internal server error", e)

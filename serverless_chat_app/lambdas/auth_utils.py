import os
import jwt
import requests
import logging
from typing import Dict, Any, Optional
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

# Cache for JWKS keys
_jwks_cache = {}

def get_cognito_jwks(user_pool_id: str, region: str = None) -> Dict[str, Any]:
    """Get Cognito JWKS (JSON Web Key Set) for token verification"""
    if region is None:
        region = os.getenv("AWS_REGION", "us-east-1")
    
    jwks_url = f"https://cognito-idp.{region}.amazonaws.com/{user_pool_id}/.well-known/jwks.json"
    
    # Use cached JWKS if available
    if jwks_url in _jwks_cache:
        return _jwks_cache[jwks_url]
    
    try:
        response = requests.get(jwks_url, timeout=10)
        response.raise_for_status()
        jwks = response.json()
        _jwks_cache[jwks_url] = jwks
        return jwks
    except requests.RequestException as e:
        logger.error(f"Failed to fetch JWKS from {jwks_url}: {e}")
        raise ValueError(f"Failed to fetch public keys: {str(e)}")

def validate_jwt_token(token: str, user_pool_id: str = None) -> Dict[str, Any]:
    """
    Simplified JWT token validation without signature verification
    Returns decoded token payload if valid, raises ValueError if invalid
    Note: This is a simplified version for development - signature verification skipped
    """
    if not token:
        raise ValueError("Token is required")
    
    try:
        # Decode token without verification (development only)
        payload = jwt.decode(
            token,
            options={"verify_signature": False, "verify_aud": False}
        )
        
        # Basic validation - check if token looks like a Cognito token
        if not payload.get("iss") or "cognito-idp" not in payload.get("iss", ""):
            raise ValueError("Token not from Cognito")
            
        # Check if token is expired
        import time
        exp = payload.get("exp")
        if exp and exp < time.time():
            raise ValueError("Token has expired")
        
        # Validate token use (should be 'id' or 'access')
        token_use = payload.get("token_use")
        if token_use not in ["id", "access"]:
            raise ValueError(f"Invalid token use: {token_use}")
        
        return payload
        
    except jwt.InvalidTokenError as e:
        raise ValueError(f"Invalid token: {str(e)}")
    except Exception as e:
        logger.error(f"Token validation failed: {e}")
        raise ValueError(f"Token validation failed: {str(e)}")

def extract_user_info(token_payload: Dict[str, Any]) -> Dict[str, Any]:
    """Extract user information from validated token payload"""
    return {
        "user_id": token_payload.get("sub") or token_payload.get("username") or token_payload.get("cognito:username"),
        "username": token_payload.get("cognito:username") or token_payload.get("username"),
        "email": token_payload.get("email"),
        "token_use": token_payload.get("token_use"),
        "exp": token_payload.get("exp"),
        "iat": token_payload.get("iat")
    }

def extract_token_from_event(event: Dict[str, Any]) -> Optional[str]:
    """Extract JWT token from various event sources (Authorization header, query params, etc.)"""
    
    # Try Authorization header first
    headers = event.get("headers", {})
    if headers:
        # Handle case-insensitive headers
        auth_header = None
        for key, value in headers.items():
            if key.lower() == "authorization":
                auth_header = value
                break
        
        if auth_header:
            # Extract Bearer token
            if auth_header.startswith("Bearer "):
                return auth_header[7:]
            return auth_header
    
    # Try query string parameters
    query_params = event.get("queryStringParameters") or {}
    if query_params.get("token"):
        return query_params["token"]
    
    # Try request body for token
    body = event.get("body")
    if body:
        try:
            import json
            body_data = json.loads(body) if isinstance(body, str) else body
            if body_data.get("token"):
                return body_data["token"]
        except:
            pass
    
    return None

def create_auth_response(status_code: int, message: str, details: str = None) -> Dict[str, Any]:
    """Create standardized authentication response"""
    import json
    body = {"error": message}
    if details:
        body["details"] = details
    
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Content-Type,Authorization",
            "Access-Control-Allow-Methods": "OPTIONS,POST,GET"
        },
        "body": json.dumps(body)
    }

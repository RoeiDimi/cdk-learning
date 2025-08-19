"""
Common response utilities for consistent CORS headers and error handling across all lambdas
"""
import json
import logging
from typing import Any, Dict, Optional, Union

logger = logging.getLogger(__name__)

# Standard CORS headers for all responses
CORS_HEADERS = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Credentials": "true",
    "Access-Control-Allow-Methods": "GET,POST,PUT,DELETE,OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type,Authorization,X-Amz-Date,X-Api-Key,X-Amz-Security-Token",
}

def create_response(
    status_code: int,
    body: Optional[Union[Dict[str, Any], str]] = None,
    additional_headers: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    """
    Create a standardized HTTP response with proper CORS headers
    
    Args:
        status_code: HTTP status code
        body: Response body (dict will be JSON encoded, str used as-is)
        additional_headers: Any additional headers to include
    
    Returns:
        Dict containing statusCode, headers, and body
    """
    headers = CORS_HEADERS.copy()
    if additional_headers:
        headers.update(additional_headers)
    
    # Handle body encoding
    if body is None:
        response_body = ""
    elif isinstance(body, str):
        response_body = body
    else:
        response_body = json.dumps(body)
    
    return {
        "statusCode": status_code,
        "headers": headers,
        "body": response_body
    }

def success_response(data: Any = None, message: str = "Success") -> Dict[str, Any]:
    """Create a successful response (200)"""
    body = {"ok": True, "message": message}
    if data is not None:
        if isinstance(data, dict):
            body.update(data)
        else:
            body["data"] = data
    return create_response(200, body)

def error_response(
    status_code: int, 
    error_message: str, 
    details: Optional[Any] = None,
    error_code: Optional[str] = None
) -> Dict[str, Any]:
    """
    Create an error response with standardized format
    
    Args:
        status_code: HTTP error status code
        error_message: Human-readable error message
        details: Optional additional error details
        error_code: Optional machine-readable error code
    """
    body = {
        "ok": False,
        "error": error_message
    }
    
    if error_code:
        body["errorCode"] = error_code
    
    if details is not None:
        body["details"] = details
    
    return create_response(status_code, body)

def bad_request_response(message: str = "Bad Request", details: Any = None) -> Dict[str, Any]:
    """Create a 400 Bad Request response"""
    return error_response(400, message, details, "BAD_REQUEST")

def unauthorized_response(message: str = "Unauthorized", details: Any = None) -> Dict[str, Any]:
    """Create a 401 Unauthorized response"""
    return error_response(401, message, details, "UNAUTHORIZED")

def forbidden_response(message: str = "Forbidden", details: Any = None) -> Dict[str, Any]:
    """Create a 403 Forbidden response"""
    return error_response(403, message, details, "FORBIDDEN")

def not_found_response(message: str = "Not Found", details: Any = None) -> Dict[str, Any]:
    """Create a 404 Not Found response"""
    return error_response(404, message, details, "NOT_FOUND")

def conflict_response(message: str = "Conflict", details: Any = None) -> Dict[str, Any]:
    """Create a 409 Conflict response"""
    return error_response(409, message, details, "CONFLICT")

def internal_server_error_response(message: str = "Internal Server Error", details: Any = None) -> Dict[str, Any]:
    """Create a 500 Internal Server Error response"""
    return error_response(500, message, details, "INTERNAL_SERVER_ERROR")

def options_response() -> Dict[str, Any]:
    """Create a standard CORS preflight OPTIONS response"""
    return create_response(204, None)

def handle_cors_preflight(event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Check if request is CORS preflight and return appropriate response
    
    Args:
        event: Lambda event
        
    Returns:
        OPTIONS response if preflight request, None otherwise
    """
    # Check for OPTIONS method in both REST API and HTTP API formats
    method = None
    if "httpMethod" in event:
        method = event["httpMethod"]
    elif "requestContext" in event and "http" in event["requestContext"]:
        method = event["requestContext"]["http"].get("method")
    
    if method == "OPTIONS":
        return options_response()
    
    return None

def log_and_return_error(
    error: Exception,
    context: str,
    status_code: int = 500,
    user_message: str = "An error occurred"
) -> Dict[str, Any]:
    """
    Log an error and return appropriate error response
    
    Args:
        error: The exception that occurred
        context: Context string for logging
        status_code: HTTP status code to return
        user_message: User-friendly error message
    """
    logger.exception(f"Error in {context}: {str(error)}")
    return error_response(status_code, user_message)

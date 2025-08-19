import json
import boto3
import os
import logging
from botocore.exceptions import ClientError
from response_utils import (
    create_response, success_response, internal_server_error_response,
    handle_cors_preflight, log_and_return_error
)

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Force redeploy - updated JSON parsing logic

def lambda_handler(event, context):
    try:
        # Handle CORS preflight
        if event.get('httpMethod') == 'OPTIONS':
            return handle_cors_preflight(event)
        
        # Simplified and robust body parsing for API Gateway HTTP API (Payload 2.0)
        body = {}
        try:
            raw_body = event.get('body')
            if raw_body:
                # The body from HTTP API is a string, so we need to parse it.
                body = json.loads(raw_body)
            if not isinstance(body, dict):
                raise json.JSONDecodeError("Body is not a dictionary", raw_body or "", 0)
        except (json.JSONDecodeError, TypeError) as e:
            logger.error(f"Failed to parse request body: {e}")
            return create_response(400, {'error': 'Invalid JSON format in request body'})

        username = body.get('username')
        password = body.get('password')
        
        if not username or not password:
            return create_response(400, {'error': 'Username and password are required'})
        
        # Validate password length
        if len(password) < 8:
            return create_response(400, {'error': 'Password must be at least 8 characters long'})
        
        # Initialize Cognito client
        cognito = boto3.client('cognito-idp')
        user_pool_id = os.environ.get('COGNITO_USER_POOL_ID')
        
        if not user_pool_id:
            logger.error("COGNITO_USER_POOL_ID environment variable not set")
            return internal_server_error_response("Server configuration error")
        
        # Create user in Cognito
        try:
            response = cognito.admin_create_user(
                UserPoolId=user_pool_id,
                Username=username,
                TemporaryPassword=password,
                MessageAction='SUPPRESS'  # Don't send welcome email
            )
            
            # Set permanent password
            cognito.admin_set_user_password(
                UserPoolId=user_pool_id,
                Username=username,
                Password=password,
                Permanent=True
            )
            
            return success_response({
                'message': 'User registered successfully',
                'username': username
            })
            
        except ClientError as e:
            error_code = e.response['Error']['Code']
            if error_code == 'UsernameExistsException':
                return create_response(409, {'error': 'Username already exists'})
            elif error_code == 'InvalidPasswordException':
                return create_response(400, {'error': 'Password does not meet requirements'})
            else:
                error_message = f"Cognito error: {error_code} - {str(e)}"
                logger.error(error_message)
                return create_response(500, {'error': 'User registration failed', 'details': error_message})
                
    except Exception as e:
        error_message = f"Unexpected error in register_user_lambda: {str(e)}"
        logger.exception(error_message)
        return create_response(500, {'error': 'Registration failed', 'details': error_message})

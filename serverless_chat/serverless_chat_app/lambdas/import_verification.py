#!/usr/bin/env python3
"""
Verification script to check that all lambda function imports work correctly.
This helps catch any import issues before deployment.
"""

import sys
import importlib.util
import os

def test_import(module_name, file_path):
    """Test if a module can be imported successfully"""
    try:
        spec = importlib.util.spec_from_file_location(module_name, file_path)
        if spec is None:
            return False, f"Could not create module spec for {file_path}"
        
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        return True, "Import successful"
    except Exception as e:
        return False, str(e)

def main():
    """Verify all lambda imports work correctly"""
    # Set required environment variables for testing
    os.environ['AWS_REGION'] = 'us-east-1'
    os.environ['AWS_DEFAULT_REGION'] = 'us-east-1'
    os.environ['CONNECTIONS_TABLE_NAME'] = 'test-connections'
    os.environ['CHAT_MESSAGES_TABLE'] = 'test-messages'
    os.environ['COGNITO_USER_POOL_ID'] = 'test-pool'
    os.environ['USER_POOL_CLIENT_ID'] = 'test-client'
    os.environ['CHAT_MESSAGES_TOPIC_ARN'] = 'arn:aws:sns:us-east-1:123456789012:test-topic'
    os.environ['WEBSOCKET_API_ENDPOINT'] = 'https://test.execute-api.us-east-1.amazonaws.com/prod'
    
    lambdas_dir = os.path.dirname(os.path.abspath(__file__))
    
    # Core utility modules that should be imported first
    core_modules = [
        ("auth_utils", "auth_utils.py"),
        ("response_utils", "response_utils.py")
    ]
    
    # Lambda functions that depend on core modules
    lambda_modules = [
        ("add_chat_message_lambda", "add_chat_message_lambda.py"),
        ("get_stored_messages_lambda", "get_stored_messages_lambda.py"),
        ("login_user_to_chat_lambda", "login_user_to_chat_lambda.py"),
        ("register_user_lambda", "register_user_lambda.py"),
        ("websocket_connect_lambda", "websocket_connect_lambda.py"),
        ("notify_all_connections_lambda", "notify_all_connections_lambda.py")
    ]
    
    print("=== Lambda Import Verification ===\n")
    
    all_passed = True
    
    # Test core modules first
    print("Testing core utility modules:")
    for module_name, filename in core_modules:
        file_path = os.path.join(lambdas_dir, filename)
        if not os.path.exists(file_path):
            print(f"❌ {module_name}: File not found at {file_path}")
            all_passed = False
            continue
            
        success, message = test_import(module_name, file_path)
        status = "✅" if success else "❌"
        print(f"{status} {module_name}: {message}")
        if not success:
            all_passed = False
    
    print("\nTesting lambda function modules:")
    # Test lambda modules
    for module_name, filename in lambda_modules:
        file_path = os.path.join(lambdas_dir, filename)
        if not os.path.exists(file_path):
            print(f"❌ {module_name}: File not found at {file_path}")
            all_passed = False
            continue
            
        success, message = test_import(module_name, file_path)
        status = "✅" if success else "❌"
        print(f"{status} {module_name}: {message}")
        if not success:
            all_passed = False
    
    print("\n=== Verification Summary ===")
    if all_passed:
        print("✅ All imports successful! Lambda dependencies are properly configured.")
        return 0
    else:
        print("❌ Some imports failed. Please check the error messages above.")
        return 1

if __name__ == "__main__":
    sys.exit(main())

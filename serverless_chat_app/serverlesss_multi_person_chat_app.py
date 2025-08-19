from aws_cdk import (
    CfnOutput,
    Duration,
    Stack,
    BundlingOptions,
    aws_dynamodb as _dynamodb,
    aws_lambda as _lambda,
    aws_apigatewayv2 as apigw_v2,
    aws_apigatewayv2_integrations as apigw_v2_integrations,
    aws_sns as _sns,
    aws_cognito as _cognito,
    aws_sns_subscriptions as _sns_subscriptions,
    aws_cloudfront as _cloudfront,
    aws_cloudfront_origins as origins,
    aws_s3 as _s3,
    aws_s3_deployment as _s3_deployment,
    aws_iam as _iam
)
from constructs import Construct


class ServerlessMultiPersonChatStack(Stack):

    def __init__(self, scope: Construct, id: str, **kwargs) -> None:
        super().__init__(scope, id, **kwargs)

        ## tables
        # Create DynamoDB table to store api gateway connection IDs
        self.ddb_connections_table = _dynamodb.Table(
            self, "ChatConnections",
            partition_key=_dynamodb.Attribute(
                name="connectionId",
                type=_dynamodb.AttributeType.STRING
            ),
            time_to_live_attribute="ttl"
        )

        # create dynamo db table to save all the chat messages
        self.ddb_messages_table = _dynamodb.Table(
            self, "ChatMessages",
            partition_key=_dynamodb.Attribute(
                name="messageId",
                type=_dynamodb.AttributeType.STRING
            )
        )

        ## sns
        # create SNS topic to publish chat messages
        self.chat_messages_topic = _sns.Topic(
            self, "ChatMessagesTopic",
            display_name="Chat Messages Topic"
        )


        ## lambdas
        # provision web socket API first
        self.chat_websocket_api = apigw_v2.WebSocketApi(
            self, "ChatWebSocketApi",
            description="WebSocket API for chat messages"
        )

        # Create a lambda function to handle user registration
        self.register_user_lambda = _lambda.Function(
            self, "RegisterUserFunction",
            runtime=_lambda.Runtime.PYTHON_3_9,
            handler="register_user_lambda.lambda_handler",
            code=_lambda.Code.from_asset("serverless_chat_app/lambdas"),
            environment={}  # Will add COGNITO_USER_POOL_ID later after user pool is created
        )

        # Create a lambda function to handle user login
        self.login_user_lambda = _lambda.Function(
            self, "LoginUserFunction",
            runtime=_lambda.Runtime.PYTHON_3_9,
            handler="login_user_to_chat_lambda.handler",
            code=_lambda.Code.from_asset("serverless_chat_app/lambdas"),
            environment={
                "CONNECTIONS_TABLE_NAME": self.ddb_connections_table.table_name,
                "PRIMARY_KEY_NAME": "connectionId",
                "TTL_ATTRIBUTE_NAME": "ttl",
                "TTL_DAYS": "30",
                "WEBSOCKET_API_ID": self.chat_websocket_api.api_id,
                "WEBSOCKET_STAGE": "prod"
            }
        )

        # create lambda function to handle adding chat messages
        self.add_chat_message_lambda = _lambda.Function(
            self, "AddChatMessageFunction",
            runtime=_lambda.Runtime.PYTHON_3_9,
            handler="add_chat_message_lambda.handler",
            code=_lambda.Code.from_asset("serverless_chat_app/lambdas"),
            environment={
                "CHAT_MESSAGES_TABLE": self.ddb_messages_table.table_name,
                "CHAT_MESSAGES_TOPIC_ARN": self.chat_messages_topic.topic_arn
            }
        )

        # create lambda function to get stored messages
        self.get_stored_messages_lambda = _lambda.Function(
            self, "GetStoredMessagesFunction",
            runtime=_lambda.Runtime.PYTHON_3_9,
            handler="get_stored_messages_lambda.handler",
            code=_lambda.Code.from_asset("serverless_chat_app/lambdas"),
            environment={
                "DDB_MESSAGES_TABLE_NAME": self.ddb_messages_table.table_name
            }
        )

        # create lambda notify all connections
        self.notify_all_connections_lambda = _lambda.Function(
            self, "NotifyAllConnectionsFunction",
            runtime=_lambda.Runtime.PYTHON_3_9,
            handler="notify_all_connections_lambda.handler",
            code=_lambda.Code.from_asset("serverless_chat_app/lambdas"),
            environment={
                "CONNECTIONS_TABLE_NAME": self.ddb_connections_table.table_name,
                "CONNECTION_ID_ATTR": "connectionId",
                "WEBSOCKET_API_ENDPOINT": f"https://{self.chat_websocket_api.api_id}.execute-api.{self.region}.amazonaws.com/prod"
            }
        )

        # create lambda for deleting a user
        self.delete_user_lambda = _lambda.Function(
            self, "DeleteUserFunction",
            runtime=_lambda.Runtime.PYTHON_3_9,
            handler="delete_user_lambda.handler",
            code=_lambda.Code.from_asset("serverless_chat_app/lambdas"),
            environment={
                "CONNECTIONS_TABLE_NAME": self.ddb_connections_table.table_name,
                "PRIMARY_KEY_NAME": "connectionId",
                "USER_ID_ATTR": "userId"
            }
        )

        # create lambda for websocket connect
        self.websocket_connect_lambda = _lambda.Function(
            self, "WebSocketConnectFunction",
            runtime=_lambda.Runtime.PYTHON_3_9,
            handler="websocket_connect_lambda.handler",
            code=_lambda.Code.from_asset("serverless_chat_app/lambdas"),
            environment={
                "CONNECTIONS_TABLE_NAME": self.ddb_connections_table.table_name,
                "PRIMARY_KEY_NAME": "connectionId",
                "TTL_ATTRIBUTE_NAME": "ttl",
                "TTL_DAYS": "30"
            }
        )

        # create $connect and $disconnect routes
        self.chat_websocket_api.add_route(
            "$connect",
            integration=apigw_v2_integrations.WebSocketLambdaIntegration(
                "ChatWebSocketConnectIntegration",
                handler=self.websocket_connect_lambda
            )
        )

        self.chat_websocket_api.add_route(
            "$disconnect",
            integration=apigw_v2_integrations.WebSocketLambdaIntegration(
                "ChatWebSocketDisconnectIntegration",
                handler=self.delete_user_lambda
            )
        )

        # Create WebSocket stage
        self.websocket_stage = apigw_v2.WebSocketStage(
            self, "ChatWebSocketStage",
            web_socket_api=self.chat_websocket_api,
            stage_name="prod",
            auto_deploy=True
        )

        ## IAM Permissions
        # grant the lambda function permissions to write to the DynamoDB table
        self.ddb_messages_table.grant_write_data(self.add_chat_message_lambda)
        # grant the lambda function permissions to publish to the SNS topic
        self.chat_messages_topic.grant_publish(self.add_chat_message_lambda)
        # grant lambda function permissions to subscribe to the SNS topic
        self.chat_messages_topic.grant_subscribe(self.notify_all_connections_lambda)
        # grant the notify all connections lambda permissions to read from the DynamoDB table
        self.ddb_connections_table.grant_read_data(self.notify_all_connections_lambda)
        # grant the get stored messages lambda permissions to read from the DynamoDB table
        self.ddb_messages_table.grant_read_data(self.get_stored_messages_lambda)
        # grant login lambda permissions to connections table
        self.ddb_connections_table.grant_read_write_data(self.login_user_lambda)
        # grant notify lambda permissions to connections table
        self.ddb_connections_table.grant_read_write_data(self.notify_all_connections_lambda)
        # grant websocket connect lambda permissions to connections table
        self.ddb_connections_table.grant_write_data(self.websocket_connect_lambda)
        # grant delete user lambda permissions to connections table
        self.ddb_connections_table.grant_read_write_data(self.delete_user_lambda)

        # Grant NotifyAllConnectionsFunction permission to manage WebSocket connections
        self.notify_all_connections_lambda.add_to_role_policy(
            _iam.PolicyStatement(
                effect=_iam.Effect.ALLOW,
                actions=["execute-api:ManageConnections"],
                resources=[f"arn:aws:execute-api:{self.region}:{self.account}:{self.chat_websocket_api.api_id}/prod/POST/@connections/*"]
            )
        )


        # subscribe the notify all connections lambda to the chat messages topic
        self.chat_messages_topic.add_subscription(_sns_subscriptions.LambdaSubscription(self.notify_all_connections_lambda))

        # create HTTP API Gateway to expose the lambda functions
        self.http_api = apigw_v2.HttpApi(
            self, "ChatHttpApi",
            api_name="Chat HTTP API",
            description="HTTP API for chat login and messages",
            cors_preflight=apigw_v2.CorsPreflightOptions(
                allow_origins=["*"],
                allow_methods=[apigw_v2.CorsHttpMethod.POST, apigw_v2.CorsHttpMethod.GET],
                allow_headers=["Content-Type", "Authorization"]
            )
        )

        # Add routes to HTTP API
        self.http_api.add_routes(
            path="/register",
            methods=[apigw_v2.HttpMethod.POST],
            integration=apigw_v2_integrations.HttpLambdaIntegration(
                "RegisterIntegration",
                self.register_user_lambda
            )
        )

        self.http_api.add_routes(
            path="/login",
            methods=[apigw_v2.HttpMethod.POST],
            integration=apigw_v2_integrations.HttpLambdaIntegration(
                "LoginIntegration",
                self.login_user_lambda
            )
        )

        self.http_api.add_routes(
            path="/addMessages",
            methods=[apigw_v2.HttpMethod.POST],
            integration=apigw_v2_integrations.HttpLambdaIntegration(
                "AddMessagesIntegration",
                self.add_chat_message_lambda
            )
        )

        self.http_api.add_routes(
            path="/getStoredMessages",
            methods=[apigw_v2.HttpMethod.GET],
            integration=apigw_v2_integrations.HttpLambdaIntegration(
                "GetStoredMessagesIntegration",
                self.get_stored_messages_lambda
            )
        )

        ## configure serverless_chat_app/index.js as a static asset and expose it using CloudFront
        self.s3_bucket = _s3.Bucket(
            self, "ChatAppBucket",
            website_index_document="index.html",
            public_read_access=False,  # CloudFront will use OAC
            block_public_access=_s3.BlockPublicAccess.BLOCK_ALL
        )
        # upload index.js to the S3 bucket
        _s3_deployment.BucketDeployment(
            self, "ChatAppDeployment",
            sources=[_s3_deployment.Source.asset("./serverless_chat_app/static")],
            destination_bucket=self.s3_bucket
        )

        # Create Origin Access Control manually
        oac = _cloudfront.CfnOriginAccessControl(
            self, "ChatAppOAC",
            origin_access_control_config=_cloudfront.CfnOriginAccessControl.OriginAccessControlConfigProperty(
                name="ChatAppOAC",
                origin_access_control_origin_type="s3",
                signing_behavior="always",
                signing_protocol="sigv4"
            )
        )

        # create cloudfront to deploy static assets with proper cache behaviors
        self.cloudfront_distribution = _cloudfront.Distribution(
            self, "ChatAppDistribution",
            default_root_object="index.html",  # Serve index.html when accessing root URL
            default_behavior=_cloudfront.BehaviorOptions(
                origin=origins.S3BucketOrigin(self.s3_bucket),
                viewer_protocol_policy=_cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                cache_policy=_cloudfront.CachePolicy.CACHING_DISABLED,  # No caching for HTML to ensure updates
                origin_request_policy=_cloudfront.OriginRequestPolicy.CORS_S3_ORIGIN
            ),
            additional_behaviors={
                # Cache JavaScript and CSS files for short duration with versioning
                "*.js": _cloudfront.BehaviorOptions(
                    origin=origins.S3BucketOrigin(self.s3_bucket),
                    viewer_protocol_policy=_cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                    cache_policy=_cloudfront.CachePolicy(
                        self, "JSCachePolicy",
                        default_ttl=Duration.minutes(5),  # 5 minute cache
                        max_ttl=Duration.hours(1),        # Max 1 hour
                        min_ttl=Duration.seconds(0),      # Allow immediate invalidation
                        header_behavior=_cloudfront.CacheHeaderBehavior.none(),
                        query_string_behavior=_cloudfront.CacheQueryStringBehavior.all(),  # Include version params
                        cookie_behavior=_cloudfront.CacheCookieBehavior.none()
                    )
                ),
                "*.css": _cloudfront.BehaviorOptions(
                    origin=origins.S3BucketOrigin(self.s3_bucket),
                    viewer_protocol_policy=_cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                    cache_policy=_cloudfront.CachePolicy(
                        self, "CSSCachePolicy", 
                        default_ttl=Duration.minutes(5),
                        max_ttl=Duration.hours(1),
                        min_ttl=Duration.seconds(0),
                        header_behavior=_cloudfront.CacheHeaderBehavior.none(),
                        query_string_behavior=_cloudfront.CacheQueryStringBehavior.all(),
                        cookie_behavior=_cloudfront.CacheCookieBehavior.none()
                    )
                )
            },
            comment="ServerlessMultiPersonChatAppDistribution"
        )

        # Update the origins to use OAC
        cfn_distribution = self.cloudfront_distribution.node.default_child
        cfn_distribution.add_property_override("DistributionConfig.Origins.0.OriginAccessControlId", oac.attr_id)
        cfn_distribution.add_property_override("DistributionConfig.Origins.1.OriginAccessControlId", oac.attr_id)  
        cfn_distribution.add_property_override("DistributionConfig.Origins.2.OriginAccessControlId", oac.attr_id)

        # Grant CloudFront OAC access to S3 bucket
        self.s3_bucket.add_to_resource_policy(
            _iam.PolicyStatement(
                effect=_iam.Effect.ALLOW,
                principals=[_iam.ServicePrincipal("cloudfront.amazonaws.com")],
                actions=["s3:GetObject"],
                resources=[f"{self.s3_bucket.bucket_arn}/*"],
                conditions={
                    "StringEquals": {
                        "AWS:SourceArn": f"arn:aws:cloudfront::{self.account}:distribution/{self.cloudfront_distribution.distribution_id}"
                    }
                }
            )
        )

        ## login - moved here to use CloudFront domain
        # Create cognito for user authentication
        self.user_pool = _cognito.UserPool(
            self, "ChatUserPool",
            self_sign_up_enabled=True,
            sign_in_aliases={"username": True},
            password_policy=_cognito.PasswordPolicy(
                min_length=8,
                require_lowercase=True,
                require_uppercase=False,
                require_digits=True,
                require_symbols=False
            )
        )

        # Cognito app client for browser based apps
        self.user_pool_client = _cognito.UserPoolClient(
            self, "ChatUserPoolClient",
            user_pool=self.user_pool,
            generate_secret=False,  # public client
            auth_flows=_cognito.AuthFlow(
                admin_user_password=True,  # Enable ADMIN_NO_SRP_AUTH for AdminInitiateAuth
                user_password=True,        # Enable ALLOW_USER_PASSWORD_AUTH
                user_srp=True            # Enable ALLOW_USER_SRP_AUTH for standard flows
            ),
            o_auth=_cognito.OAuthSettings(
                flows=_cognito.OAuthFlows(
                    authorization_code_grant=True,   # PKCE when no secret
                    implicit_code_grant=False        # not recommended
                ),
                scopes=[_cognito.OAuthScope.OPENID, _cognito.OAuthScope.EMAIL, _cognito.OAuthScope.PROFILE],
                callback_urls=[f"https://{self.cloudfront_distribution.distribution_domain_name}/"],  # Fixed: use actual CloudFront domain
                logout_urls=[f"https://{self.cloudfront_distribution.distribution_domain_name}/"],     # Fixed: use actual CloudFront domain
            ),
        )

        # Add USER_POOL_ID and CLIENT_ID to login and register lambda environment variables now that user pool is created
        self.login_user_lambda.add_environment("COGNITO_USER_POOL_ID", self.user_pool.user_pool_id)
        self.login_user_lambda.add_environment("USER_POOL_CLIENT_ID", self.user_pool_client.user_pool_client_id)
        self.register_user_lambda.add_environment("COGNITO_USER_POOL_ID", self.user_pool.user_pool_id)
        self.register_user_lambda.add_environment("FORCE_DEPLOY", "1") # Force redeployment

        # Grant register lambda permission to create users in Cognito
        self.register_user_lambda.add_to_role_policy(
            _iam.PolicyStatement(
                effect=_iam.Effect.ALLOW,
                actions=["cognito-idp:AdminCreateUser", "cognito-idp:AdminSetUserPassword"],
                resources=[self.user_pool.user_pool_arn]
            )
        )
        
        # Grant login lambda permission to authenticate users in Cognito
        self.user_pool.grant(self.login_user_lambda, "cognito-idp:AdminInitiateAuth", "cognito-idp:AdminGetUser")

        # Output the CloudFront URL for static assets only
        CfnOutput(
            self, "ChatAppUrl",
            value=f"https://{self.cloudfront_distribution.distribution_domain_name}",
            description="CloudFront URL for static assets (HTML/JS/CSS only)"
        )

        # Output the HTTP API URL for all API calls
        CfnOutput(
            self, "HttpApiUrl", 
            value=self.http_api.url,
            description="HTTP API URL - Use this for ALL API calls (/register, /login, /addMessages, /getStoredMessages)"
        )

        # Output the WebSocket API URL
        CfnOutput(
            self, "WebSocketApiUrl",
            value=f"{self.chat_websocket_api.api_endpoint}/prod",
            description="WebSocket API URL for real-time chat connections"
        )

        # Output specific API endpoints for easy reference
        CfnOutput(
            self, "RegisterEndpoint",
            value=f"{self.http_api.url}register",
            description="Registration endpoint - POST requests only"
        )

        CfnOutput(
            self, "LoginEndpoint", 
            value=f"{self.http_api.url}login",
            description="Login endpoint - POST requests only"
        )

        CfnOutput(
            self, "AddMessagesEndpoint",
            value=f"{self.http_api.url}addMessages", 
            description="Add messages endpoint - POST requests only"
        )

        CfnOutput(
            self, "GetStoredMessagesEndpoint",
            value=f"{self.http_api.url}getStoredMessages",
            description="Get stored messages endpoint - GET requests only"
        )

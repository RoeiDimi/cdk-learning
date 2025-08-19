# Python
#!/usr/bin/env python3
import aws_cdk as cdk
from cdk_test.cdk_test_stack import CdkTestStack
from resource_stacks.NetworkStack import NetworkStack
from serverless_chat_app.serverlesss_multi_person_chat_app import ServerlessMultiPersonChatStack

app = cdk.App()

network_stack = NetworkStack(app, "NetworkStack",
                             env=cdk.Environment(account="219400381002", region="us-east-1"))

# Pass the VPC created in NetworkStack to CdkTestStack
vpc = network_stack.vpc
CdkTestStack(app, "CdkTestStack",
             env=cdk.Environment(account="219400381002", region="us-east-1"),
             vpc=vpc)

# Add the Serverless Chat App Stack
ServerlessMultiPersonChatStack(app, "ServerlessChatStack",
                               env=cdk.Environment(account="219400381002", region="us-east-1"))

app.synth()

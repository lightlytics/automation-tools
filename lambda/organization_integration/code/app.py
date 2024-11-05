import boto3
import json
import os
import time

print("Running StreamSecurity organization integration Lambda")

def assume_role(account_id):
    sts_client = boto3.client("sts")

    role_name = os.getenv("ROLE_NAME", "OrganizationAccountAccessRole")  
    role_arn = f"arn:aws:iam::{account_id}:role/{role_name}"
    role_session_name = f"OrganizationIntegrationRole-{int(time.time())}"  # Unique session name

    print (f"Assuming role {role_arn} in account {account_id} for organization integration")
    response = sts_client.assume_role(RoleArn=role_arn, RoleSessionName=role_session_name)

    return response["Credentials"]

def lambda_handler(event, context):
    # Extract account ID from the EventBridge event
    account_id = event["detail"]["accountId"]
    credentials = assume_role(account_id)

    if not credentials:
        print(f"Failed to assume role in account {account_id}")
        return
    print(f"Integrating account {account_id}")
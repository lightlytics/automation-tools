import argparse
import boto3
import json
import time
import zipfile
import shutil
import os
import tempfile

parser = argparse.ArgumentParser(description="Streamsec Organization Lambda Setup Script")
parser.add_argument("--environment", required=False, help="The environment name in which the Lambda function will operate.")
parser.add_argument("--user-name", required=False, help="The username for the environment.")
parser.add_argument("--password", required=False, help="The password for the environment.")
parser.add_argument("--cleanup", action="store_true", help="Clean up the resources created by the script.")
parser.add_argument("--accounts", required=False, help="manually specify accounts to integrate.")
parser.add_argument("--ws-id", required=False, help="The workspace ID.")
parser.add_argument("--control-role", default="OrganizationAccountAccessRole", help="The control role name for assuming the role in the target account.", required=False)
parser.add_argument("--response", action="store_true", help="Enable creation of the response stack.")
parser.add_argument("--response-region", default="us-east-1", help="Region for response stack.")
parser.add_argument("--response-exclude-runbooks", help="Comma separated list of runbooks to exclude from response stack.")
parser.add_argument("--eks-audit-logs", action="store_true", help="Enable creation of the EKS audit logs.")
parser.add_argument("--eks-audit-logs-regions", required=False, help="Comma separated list of regions to enable EKS audit logs.")
args = parser.parse_args()

iam_client = boto3.client('iam')
sts_client = boto3.client('sts')
lambda_client = boto3.client('lambda')
events_client = boto3.client('events')

aws_account_id = sts_client.get_caller_identity()['Account']

def main():
    missing_args = []
    if not args.environment:
        missing_args.append("--environment")
    if not args.user_name:
        missing_args.append("--user-name")
    if not args.password:
        missing_args.append("--password")
    if not args.ws_id:
        missing_args.append("--ws-id")

    if missing_args:
        print(f"Missing required arguments: {', '.join(missing_args)}")
        print("These arguments are required unless --cleanup is specified.")
        return
    
    print("Welcome to the Streamsec Organization Lambda Setup Script!")
    print("This script will perform the following actions:")
    print("1. Create an IAM policy with permissions to list AWS accounts and describe EC2 regions.")
    print("2. Create an IAM role for the Lambda function with the necessary assume role policy.")
    print("3. Attach the created policy and the AWS Lambda basic execution role policy to the IAM role.")
    print("4. Create a Lambda function with the specified configurations.")
    print("5. Create an EventBridge rule to trigger the Lambda function when a new AWS account is created.")
    print("6. Add necessary permissions for EventBridge to invoke the Lambda function.")
    print("7. Set the EventBridge rule target to the Lambda function.")

    proceed = input("Do you want to proceed with these actions? (yes/no): ")
    if proceed.lower() != "yes":
        print("Script execution aborted by the user.")
        return

    print("Starting the setup process...")

    aws_account_id = sts_client.get_caller_identity()['Account']
    region = boto3.Session().region_name

    # Create IAM policy
    policy_name = "streamsec-organization-lambda-policy"
    policy_document = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "VisualEditor0",
                "Effect": "Allow",
                "Action": ["organizations:ListAccounts", "ec2:DescribeRegions"],
                "Resource": "*"
            },
            {
                "Sid": "VisualEditor1",
                "Effect": "Allow",
                "Action": "sts:AssumeRole",
                "Resource": f"arn:aws:iam::*:role/OrganizationAccountAccessRole"
            }
        ]
    }
    policy_response = iam_client.create_policy(
        PolicyName=policy_name,
        PolicyDocument=json.dumps(policy_document)
    )
    policy_arn = policy_response['Policy']['Arn']

    # Create IAM role
    role_name = "streamsec-organization-lambda-role"
    assume_role_policy_document = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {"Service": "lambda.amazonaws.com"},
                "Action": "sts:AssumeRole"
            }
        ]
    }
    role_response = iam_client.create_role(
        RoleName=role_name,
        AssumeRolePolicyDocument=json.dumps(assume_role_policy_document)
    )
    role_arn = role_response['Role']['Arn']

    # Attach policies to role
    iam_client.attach_role_policy(
        RoleName=role_name,
        PolicyArn=policy_arn
    )
    iam_client.attach_role_policy(
        RoleName=role_name,
        PolicyArn="arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
    )

    time.sleep(5)  # Wait for role to propagate

    # --- Create deployment package (zip) with dependencies ---
    zip_filename = "lambda_deploy.zip"
    with tempfile.TemporaryDirectory() as build_dir:
        # Install dependencies into build_dir
        os.system(f"pip install -r lambda/organization_integration/requirements.txt -t {build_dir}")
        # Copy app.py into build_dir
        shutil.copy("lambda/organization_integration/app.py", os.path.join(build_dir, "app.py"))
        # Copy src into build_dir/src
        shutil.copytree("src", os.path.join(build_dir, "src"))
        # Zip everything in build_dir
        with zipfile.ZipFile(zip_filename, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for foldername, subfolders, filenames in os.walk(build_dir):
                for filename in filenames:
                    filepath = os.path.join(foldername, filename)
                    arcname = os.path.relpath(filepath, build_dir)
                    zipf.write(filepath, arcname=arcname)

    # Create Lambda function
    function_name = "streamsec-organization-lambda"
    env_vars = {
        "ENVIRONMENT": args.environment,
        "ENVIRONMENT_USER_NAME": args.user_name,
        "ENVIRONMENT_PASSWORD": args.password,
        "WS_ID": args.ws_id,
        "PARALLEL": "8",
        "CONTROL_ROLE": args.control_role,
        "RESPONSE": str(args.response).lower(),
        "RESPONSE_REGION": args.response_region,
        "EKS_AUDIT_LOGS": str(args.eks_audit_logs).lower(),
    }
    if args.accounts is not None:
        env_vars["ACCOUNTS"] = args.accounts
        
    if args.response_exclude_runbooks is not None:
        env_vars["RESPONSE_EXCLUDE_RUNBOOKS"] = args.response_exclude_runbooks

    if args.eks_audit_logs_regions is not None:
        env_vars["EKS_AUDIT_LOGS_REGIONS"] = args.eks_audit_logs_regions

    with open(zip_filename, 'rb') as f:
        zipped_code = f.read()

    lambda_client.create_function(
        FunctionName=function_name,
        Runtime="python3.12",
        Role=role_arn,
        Handler="app.lambda_handler",
        Code={
            'ZipFile': zipped_code
        },
        MemorySize=2048,
        Timeout=900,
        Environment={"Variables": env_vars},
        Publish=True
    )

    # Clean up zip file
    os.remove(zip_filename)

    # Create EventBridge rule
    rule_name = "streamsec-organization-newaccount-rule"
    event_pattern = {
        "source": ["aws.organizations"],
        "detail-type": ["AWS API Call via CloudTrail"],
        "detail": {"eventName": ["CreateAccountResult"]}
    }
    events_client.put_rule(
        Name=rule_name,
        EventPattern=json.dumps(event_pattern),
        Description="Rule to trigger Lambda when a new AWS account is created"
    )

    # Add permission for EventBridge to invoke Lambda
    lambda_client.add_permission(
        FunctionName=function_name,
        StatementId="EventBridgeInvokeLambda",
        Action="lambda:InvokeFunction",
        Principal="events.amazonaws.com",
        SourceArn=f"arn:aws:events:{region}:{aws_account_id}:rule/{rule_name}"
    )

    # Set EventBridge rule target to Lambda function
    events_client.put_targets(
        Rule=rule_name,
        Targets=[
            {
                "Id": "1",
                "Arn": f"arn:aws:lambda:{region}:{aws_account_id}:function:{function_name}"
            }
        ]
    )

    print("Setup completed successfully!")

def cleanup():
    proceed = input("Do you want to cleanup this script resources? (yes/no): ")
    if proceed.lower() != "yes":
        print("Script execution aborted by the user.")
        return
    # try to delete the resources created by the script
    # if resources are not found, ignore the exception

    
    try:
        # Delete the Lambda function
        print("Deleting the Lambda function...")
        lambda_client.delete_function(FunctionName="streamsec-organization-lambda")
    except lambda_client.exceptions.ResourceNotFoundException:
        print("Lambda function not found.")
        pass
    
    try:
        # Delete the EventBridge rule
        print("Deleting the EventBridge rule...")
        events_client.remove_targets(Rule="streamsec-organization-newaccount-rule", Ids=["1"])
        events_client.delete_rule(Name="streamsec-organization-newaccount-rule")
    except events_client.exceptions.ResourceNotFoundException:
        print("EventBridge rule not found.")
        pass
    
    try:
        # Detach and delete the IAM role
        print("Deleting the IAM role...")
        role_name = "streamsec-organization-lambda-role"
        try:
            iam_client.detach_role_policy(RoleName=role_name, PolicyArn="arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole")
        except iam_client.exceptions.NoSuchEntityException:
            print("AWSLambdaBasicExecutionRole policy not attached.")
        try:
            iam_client.detach_role_policy(RoleName=role_name, PolicyArn="arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole")
        except iam_client.exceptions.NoSuchEntityException:
            print("AWSLambdaVPCAccessExecutionRole policy not attached.")
        try:
            iam_client.detach_role_policy(RoleName=role_name, PolicyArn=f"arn:aws:iam::{aws_account_id}:policy/streamsec-organization-lambda-policy")
        except iam_client.exceptions.NoSuchEntityException:
            print("Streamsec Organization Lambda policy not attached.")
        print("Detached the policies from the IAM role.")
        iam_client.delete_role(RoleName=role_name)
        print("Deleted the IAM role.")
    except iam_client.exceptions.NoSuchEntityException:
        print("IAM role not found.")
        pass
    
    try:
        # Delete the IAM policy
        print("Deleting the IAM policy...")
        iam_client.delete_policy(PolicyArn=f"arn:aws:iam::{aws_account_id}:policy/streamsec-organization-lambda-policy")
    except iam_client.exceptions.NoSuchEntityException:
        print("IAM policy not found.")
        pass
    
    print("Cleanup completed successfully!")

if __name__ == "__main__":
    if not args.cleanup:
        main()
    else:
        cleanup()
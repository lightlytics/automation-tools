import argparse
import boto3
import json
import os
import random
import sys

# Add the project root directory to the Python path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')))
try:
    from src.python.common.boto_common import *
    from src.python.common.graph_common import GraphCommon
except ModuleNotFoundError:
    sys.path.append("../../..")
    from src.python.common.boto_common import *
    from src.python.common.graph_common import GraphCommon


def main(environment, ll_username, ll_password, aws_profile_name, accounts,
         ws_id=None, control_role="OrganizationAccountAccessRole"):
    # Setting up variables
    if accounts:
        accounts = accounts.replace(" ", "").split(",")

    print(color("Trying to login into Stream Security", "blue"))
    ll_url = f"https://{environment}.streamsec.io/graphql"
    graph_client = GraphCommon(ll_url, ll_username, ll_password, ws_id)
    print(color("Logged in successfully!", "green"))

    print(color("Creating Boto3 Session", "blue"))
    # Set the AWS_PROFILE environment variable
    os.environ['AWS_PROFILE'] = aws_profile_name

    # Set up the Organizations client
    org_client = boto3.client('organizations')

    # Set up the STS client
    sts_client = boto3.client('sts')

    print(color("Fetching all accounts connected to the organization", "blue"))
    list_accounts = get_all_accounts(org_client)

    # Getting only the account IDs of the active AWS accounts
    sub_accounts = [(a["Id"], a["Name"]) for a in list_accounts if a["Status"] == "ACTIVE"]
    print(color(f"Found {len(sub_accounts)} accounts", "blue"))

    if accounts:
        sub_accounts = [sa for sa in sub_accounts if sa[0] in accounts]

    print(color(f"Accounts to-be updated: {[sa[0] for sa in sub_accounts]}", "blue"))
    with concurrent.futures.ThreadPoolExecutor() as executor:
        # Submit tasks to the thread pool
        results = [executor.submit(integrate_cloudtrail, sub_account, sts_client, graph_client, control_role,
                                   environment)
                   for sub_account in sub_accounts]
        # Wait for all tasks to complete
        concurrent.futures.wait(results)

    print(color("Integration finished successfully!", "green"))


def integrate_cloudtrail(sub_account, sts_client, graph_client, control_role, environment):
    print(color(f"Account: {sub_account[0]} | Starting integration", color="blue"))
    try:
        # Assume the role in the sub_account[0]
        assumed_role = sts_client.assume_role(
            RoleArn=f'arn:aws:iam::{sub_account[0]}:role/{control_role}',
            RoleSessionName='MySessionName'
        )
        print(color(f"Account: {sub_account[0]} | Initializing Boto session", "blue"))
        sub_account_session = boto3.Session(
            aws_access_key_id=assumed_role['Credentials']['AccessKeyId'],
            aws_secret_access_key=assumed_role['Credentials']['SecretAccessKey'],
            aws_session_token=assumed_role['Credentials']['SessionToken']
        )
        print(color(f"Account: {sub_account[0]} | Session initialized successfully", "green"))

        print(color(f"Account: {sub_account[0]} | Getting all the multi region trails", "blue"))
        ct_client = sub_account_session.client('cloudtrail')
        multi_region_trails = [t for t in ct_client.describe_trails().get('trailList') if t["IsMultiRegionTrail"]]
        if len(multi_region_trails) == 0:
            raise Exception(f"Account: {sub_account[0]} | Multi region trail not found, create it first")
        relevant_s3_name = multi_region_trails[0].get('S3BucketName')
        print(color(f"Account: {sub_account[0]} | Found {len(multi_region_trails)} multi region trails", "green"))

        print(color(f"Account: {sub_account[0]} | Getting realtime region for the integration", "blue"))
        account_realtime_regions = [r['region_name'] for r in
                                    graph_client.get_specific_account(sub_account[0])['realtime_regions']]
        print(color(f"Account: {sub_account[0]} | Found {len(account_realtime_regions)} regions", "green"))

        for region in account_realtime_regions:
            print(color(f"Account: {sub_account[0]} | Connection region: '{region}'", "blue"))

            print(color(f"Account: {sub_account[0]} | Searching for IAM Collection Lambda", "blue"))
            lambda_client = sub_account_session.client('lambda')
            relevant_lambda = [la for la in lambda_client.list_functions().get('Functions') if
                               "IAMLogsCollection" in la['FunctionName'] and
                               environment in la['Environment']['Variables'].get("API_URL", None)][0]
            print(color(f"Account: {sub_account[0]} | "
                        f"Found the desired lambda: {relevant_lambda['FunctionName']}", "green"))

            print(color(f"Account: {sub_account[0]} | Adding Lambda permissions", "blue"))
            lambda_client.add_permission(
                FunctionName=relevant_lambda['FunctionName'],
                StatementId='AllowToBeInvoked',
                Action='lambda:InvokeFunction',
                Principal='s3.amazonaws.com',
                SourceAccount=sub_account[0],
                SourceArn=f'arn:aws:s3:::{relevant_s3_name}'
            )
            print(color(f"Account: {sub_account[0]} | Lambda permissions added successfully", "green"))

            print(color(f"Account: {sub_account[0]} | Create trigger policy", "blue"))
            boto_iam = sub_account_session.client('iam')
            policy = {
                "Version": "2012-10-17",
                "Statement": [{
                    "Action": ["s3:GetObject", "s3:ListBucket", "s3:GetBucketLocation",
                               "s3:GetObjectVersion", "s3:GetLifecycleConfiguration"],
                    "Resource": [f"arn:aws:s3:::{relevant_s3_name}/*"],
                    "Effect": "Allow"}
                ]
            }
            policy_name = f"StreamIAMCollectionPolicy-{random.randint(100000, 999999)}"
            policy_arn = boto_iam.create_policy(
                PolicyName=policy_name, PolicyDocument=json.dumps(policy))['Policy']['Arn']
            print(color(f"Account: {sub_account[0]} | Policy '{policy_name}' created successfully", "green"))

            print(color(f"Account: {sub_account[0]} | Attaching '{policy_name}' to Lambda's role", "blue"))
            lambda_role_name = relevant_lambda['Role'].split("/")[-1]
            boto_iam.attach_role_policy(RoleName=lambda_role_name, PolicyArn=policy_arn)
            print(color(f"Account: {sub_account[0]} | Attached successfully", "green"))

            print(color(f"Account: {sub_account[0]} | Adding {relevant_s3_name} as Lambda trigger", "blue"))
            s3_client = sub_account_session.client('s3')
            s3_client.put_bucket_notification_configuration(
                Bucket=relevant_s3_name,
                NotificationConfiguration={
                    'LambdaFunctionConfigurations': [{
                        'LambdaFunctionArn': relevant_lambda['FunctionArn'],
                        'Events': ['s3:ObjectCreated:*']
                    }]
                },
                SkipDestinationValidation=True
            )
            print(color(f"Account: {sub_account[0]} | Trigger added successfully", "green"))

            print(color(f"Account: {sub_account[0]} | Successfully integrated in region: {region}", "green"))

    except Exception as e:
        err_msg = f"Account: {sub_account[0]} | Something went wrong: {e}"
        print(color(err_msg, "red"))
        raise Exception(err_msg)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description='This script will integrate StreamSecurity environment with every account in the organization.')
    parser.add_argument(
        "--environment_sub_domain", help="The StreamSecurity environment sub domain")
    parser.add_argument(
        "--environment_user_name", help="The StreamSecurity environment user name")
    parser.add_argument(
        "--environment_password", help="The StreamSecurity environment password")
    parser.add_argument(
        "--aws_profile_name", help="The AWS profile with admin permissions for the organization account",
        default="staging")
    parser.add_argument(
        "--accounts", help="Accounts list to iterate when creating the report (e.g '123123123123,321321321321')",
        required=False)
    parser.add_argument(
        "--ws_id", help="ID of the WS to deploy to", required=False)
    parser.add_argument(
        "--control_role", help="Specify a role for control", default="OrganizationAccountAccessRole", required=False)
    args = parser.parse_args()
    main(args.environment_sub_domain, args.environment_user_name, args.environment_password,
         args.aws_profile_name, args.accounts, ws_id=args.ws_id, control_role=args.control_role)

import argparse
import boto3
import os
import random
import sys
from urllib.parse import urlparse

# Add the project root directory to the Python path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')))
try:
    from src.python.common.boto_common import *
    from src.python.common.graph_common import GraphCommon
except ModuleNotFoundError:
    sys.path.append("../../..")
    from src.python.common.boto_common import *
    from src.python.common.graph_common import GraphCommon


def main(environment_url, ll_username, ll_password, aws_profile_name,
         ws_id=None, old_url=None, control_role=None):
    
    try:
        # Check for required parameters
        if not environment_url:
            raise ValueError("The environment URL is required.")
        if not ll_username:
            raise ValueError("The StreamSecurity environment user name is required.")
        if not ll_password:
            raise ValueError("The StreamSecurity environment password is required.")
        if not aws_profile_name:
            raise ValueError("The AWS profile name is required.")
    except Exception as e:
        print(color(f"Error: {e}", "red"))
        return

    print(color("Trying to login into Stream Security", "blue"))
    try:
        parsed_url = urlparse(environment_url)
        if parsed_url.scheme and parsed_url.netloc:
            ll_url = f"https://{parsed_url.netloc}/graphql"
        elif '.' in environment_url:
            ll_url = f"https://{environment_url}/graphql" if environment_url.count('.') >= 2 else f"https://{environment_url}.streamsec.io/graphql"
        else:
            raise ValueError("The environment should be a valid URL or a subdomain.")
        print(color(f"Stream Security URL: {ll_url}", "blue"))
        graph_client = GraphCommon(ll_url, ll_username, ll_password, ws_id)
        print(color("Logged in successfully!", "green"))
    except Exception as e:
        print(color(f"Error: {e}", "red"))
        return
    
    try:
        print(color("Creating Boto3 Session", "blue"))
        # Set the AWS_PROFILE environment variable
        os.environ['AWS_PROFILE'] = aws_profile_name
        # Set up the STS client
        sts_client = boto3.client('sts')
        print(color("Boto3 Session created successfully!", "green"))

    except Exception as e: 
        print(color(f"Error: {e}", "red"))
        return

    aws_accounts = [acc for acc in graph_client.get_accounts() if acc["account_type"] == 'AWS']
    print(color(f"AWS Accounts: {[acc['cloud_account_id'] for acc in aws_accounts]}", "blue"))
    

    # confirmation = input("Do you want to continue? Type 'yes' to proceed: ")
    # if confirmation.lower() != 'yes':
    #     print("Operation canceled.")
    #     return

    for aws_account in aws_accounts:
        modify_lambda_url(aws_account, environment_url, old_url, control_role, sts_client)

    print(color("finished successfully!", "green"))

def modify_lambda_url(aws_account, environment_url, old_url, control_role, sts_client):
    print(color(f"Checking account: {aws_account['cloud_account_id']}", "blue"))
    
    # Assume the role in the sub_account[0]
    assumed_role = sts_client.assume_role(
        RoleArn=f'arn:aws:iam::{aws_account['cloud_account_id']}:role/{control_role}',
        RoleSessionName='MySessionName'
    )
    print(color(f"Account: {aws_account['cloud_account_id']} | Initializing Boto session", "blue"))
    aws_account_session = boto3.Session(
        aws_access_key_id=assumed_role['Credentials']['AccessKeyId'],
        aws_secret_access_key=assumed_role['Credentials']['SecretAccessKey'],
        aws_session_token=assumed_role['Credentials']['SessionToken']
    )
    print(color(f"Account: {aws_account['cloud_account_id']} | Session initialized successfully", "green"))
    
    regions = aws_account['cloud_regions']
    for region in regions:
        print(color(f"Checking region: {region}", "blue"))
        lambda_client = aws_account_session.client('lambda', region_name=region)
        # check all lambdas that have stream/lightlytics/streamsec/streamsecurity in the name
        functions = []
        paginator = lambda_client.get_paginator('list_functions')
        for page in paginator.paginate():
            functions.extend(page['Functions'])
        # keep only the functions that have stream/lightlytics/streamsec/streamsecurity in the name
        keywords = ('stream', 'lightlytics', 'streamsec', 'streamsecurity')
        functions = [f for f in functions if any(k in f['FunctionName'].lower() for k in keywords)]
            print(color(f"Checking function: {function['FunctionName']}", "blue"))
            # if the value is not the same as the environment url, update the value
            try:
                if function['Environment']['Variables']['API_URL'] == old_url:
                    print(color(f"Found match for function: {function['FunctionName']}, updating to new url", "blue"))
                    # Get current environment variables
                    current_env = function['Environment']['Variables']
                    # Update API_URL while preserving other variables
                    current_env['API_URL'] = f"{environment_url}"
                    lambda_client.update_function_configuration(
                        FunctionName=function['FunctionName'],
                        Environment={'Variables': current_env})
                    print(color(f"API_URL updated for function: {function['FunctionName']}", "green"))
            except Exception as e:
                continue
            
if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description='This script will integrate StreamSecurity environment with every account in the organization.')
    parser.add_argument(
        "--environment_url", help="The StreamSecurity environment URL", required=True)
    parser.add_argument(
        "--environment_user_name", help="The StreamSecurity environment user name", required=True)
    parser.add_argument(
        "--environment_password", help="The StreamSecurity environment password", required=True)
    parser.add_argument(
        "--aws_profile_name", help="The AWS profile with admin permissions for the organization account",
        default="staging")
    # parser.add_argument(
        # "--parallel", help="Number of threads for parallel integration", type=int, required=False, default=1)
    parser.add_argument(
        "--ws_id", help="ID of the WS to deploy to", required=False)
    parser.add_argument(
        "--control_role", help="Specify a role for control", default="OrganizationAccountAccessRole", required=False)
    parser.add_argument(
        "--old_url", help="Specify the old URL to replace", required=False, default="https://app.streamsec.io")
    args = parser.parse_args()
    main(args.environment_url, args.environment_user_name, args.environment_password,
         args.aws_profile_name,
         ws_id=args.ws_id,
         old_url=args.old_url,
         control_role=args.control_role)

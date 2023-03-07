import argparse
import boto3
import botocore
import datetime
import os
import random
import time
from botocore.exceptions import ClientError
from src.python.common.graph_common import GraphCommon

# TODO REMOVE
from pprint import pprint

GLOBAL_REGION = "us-east-1"


def main(environment, ll_username, ll_password):
    # Setting up variables
    random_int = random.randint(1000000, 9999999)

    print("Trying to login into Lightlytics")
    ll_url = f"https://{environment}.lightlytics.com/graphql"
    ll_url = f"https://{environment}.lightops.io/graphql"
    graph_client = GraphCommon(ll_url, ll_username, ll_password)
    print("Logged in successfully!")

    print("Creating Boto3 Session")
    # Set the AWS_PROFILE environment variable
    os.environ['AWS_PROFILE'] = 'staging'

    # Set up the Organizations client
    org_client = boto3.client('organizations')

    # Set up the STS client
    sts_client = boto3.client('sts')

    print("Fetching all accounts connected to the organization")
    list_accounts = []
    next_token = None
    while True:
        if next_token:
            list_accounts_operation = org_client.list_accounts(NextToken=next_token)
        else:
            list_accounts_operation = org_client.list_accounts()
        list_accounts.extend(list_accounts_operation["Accounts"])
        if 'NextToken' in list_accounts_operation:
            next_token = list_accounts_operation["NextToken"]
        else:
            break
    # Getting only the account IDs of the active AWS accounts
    sub_accounts = [a["Id"] for a in list_accounts if a["Status"] == "ACTIVE"]
    print(f"Found {len(sub_accounts)} accounts")

    for sub_account in sub_accounts:
        if sub_account != "139614369439":
            continue
        try:
            # Assume the role in the sub_account
            assumed_role = sts_client.assume_role(
                RoleArn=f'arn:aws:iam::{sub_account}:role/OrganizationAccountAccessRole',
                RoleSessionName='MySessionName'
            )
            print(f"Initializing session for account: {sub_account}")
            sub_account_session = boto3.Session(
                aws_access_key_id=assumed_role['Credentials']['AccessKeyId'],
                aws_secret_access_key=assumed_role['Credentials']['SecretAccessKey'],
                aws_session_token=assumed_role['Credentials']['SessionToken']
            )
            print("Session initialized successfully")

            print("Checking if integration already exists")
            if sub_account in [acc["aws_account_id"] for acc in graph_client.get_accounts()]:
                print("Account is already integrated, skipping")
                continue

            print(f"Creating {sub_account} account in Lightlytics")
            graph_client.create_account(sub_account, [GLOBAL_REGION])
            print("Account created successfully")

            print("Fetching the CFT Template URL from lightlytics")
            sub_account_template_url = graph_client.get_template_by_account_id(sub_account)
            print(f"Fetched successfully, the template URL: {sub_account_template_url}")

            # Initializing "cloudformation" boto client
            cf = sub_account_session.client('cloudformation')

            print("Creating the CFT stack using Boto")
            stack_creation_payload = {
                "StackName": f"LightlyticsStack-{random_int}",
                "Capabilities": ['CAPABILITY_IAM', 'CAPABILITY_NAMED_IAM', 'CAPABILITY_AUTO_EXPAND'],
                "OnFailure": 'ROLLBACK',
                "EnableTerminationProtection": False,
                "TemplateURL": sub_account_template_url
            }
            sub_account_stack_id = cf.create_stack(**stack_creation_payload)["StackId"]
            print(f"{sub_account_stack_id} Created successfully")

            print("Waiting for the stack to finish deploying successfully")
            wait_for_cloudformation(sub_account_stack_id, cf)

        except botocore.exceptions.ClientError as e:
            # Print an error message
            print("Error for sub_account {}: {}".format(sub_account, e))


def wait_for_cloudformation(cft_id, cf_client, timeout=180):
    """ Wait for stack to be deployed.
        :param timeout (int)        - Max waiting time; Defaults to 180.
        :param cft_id (str)         - Stack ID.
        :param cf_client (object)   - CF Session.
    """
    dt_start = datetime.datetime.utcnow()
    dt_diff = 0

    print(f"Waiting for stack to finish creating, timeout is {timeout} seconds")
    while dt_diff < timeout:
        stack_list = cf_client.list_stacks()
        pprint(stack_list)
        status = [stack['StackStatus'] for stack in stack_list['StackSummaries'] if stack['StackId'] == cft_id]
        dt_finish = datetime.datetime.utcnow()
        dt_diff = (dt_finish - dt_start).total_seconds()

        if status == 'CREATE_COMPLETE':
            print(f'Stack deployed successfully after {dt_diff} seconds')
            break
        else:
            time.sleep(1)
            time.sleep(20)
    if dt_diff >= timeout:
        print("Timed out before stack has been created/deleted")
        return False
    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description='This script will integrate Lightlytics environment with every account in the organization.')
    parser.add_argument(
        "--environment_sub_domain", help="The Lightlytics environment sub domain")
    parser.add_argument(
        "--environment_user_name", help="The Lightlytics environment user name")
    parser.add_argument(
        "--environment_password", help="The Lightlytics environment password")
    args = parser.parse_args()
    main(args.environment_sub_domain, args.environment_user_name, args.environment_password)

import argparse
import boto3
import botocore
import os
from botocore.exceptions import ClientError
from src.python.common.graph_common import *
# TODO REMOVE
from pprint import pprint


def main(environment, ll_username, ll_password):
    # Setting up variables
    ll_url = f"https://{environment}.lightlytics.com/graphql"
    ll_url = f"https://{environment}.lightops.io/graphql"
    ll_token = get_token(ll_url, ll_username, ll_password)

    print("Creating Boto3 Session")
    # Set the AWS_PROFILE environment variable
    os.environ['AWS_PROFILE'] = 'staging'

    # Set up the Organizations client
    org_client = boto3.client('organizations')

    # Set up the STS client
    sts_client = boto3.client('sts')

    # Call a Boto3 function to fetch all accounts
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

            # TODO ADD REGION SELECTION HERE
            # Create a Boto3 session using the assumed role credentials
            sub_account_session = boto3.Session(
                aws_access_key_id=assumed_role['Credentials']['AccessKeyId'],
                aws_secret_access_key=assumed_role['Credentials']['SecretAccessKey'],
                aws_session_token=assumed_role['Credentials']['SessionToken']
            )

            ec2 = sub_account_session.client('ec2')
            pprint(ec2.describe_vpcs())
            break

        except botocore.exceptions.ClientError as e:
            # Print an error message
            print("Error for sub_account {}: {}".format(sub_account, e))


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

import argparse
import boto3
import os
import sys

import concurrent.futures
from datetime import datetime

# Add the project root directory to the Python path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')))
try:
    from src.python.common.boto_common import *
    from src.python.common.graph_common import GraphCommon
except ModuleNotFoundError:
    sys.path.append("../../..")
    from src.python.common.boto_common import *
    from src.python.common.graph_common import GraphCommon


def main(aws_profile_name, accounts, control_role="OrganizationAccountAccessRole", just_print=False):
    if accounts:
        accounts = accounts.replace(" ", "").split(",")

    print(color("Creating Boto3 Session", "blue"))
    # Set the AWS_PROFILE environment variable
    os.environ['AWS_PROFILE'] = aws_profile_name

    # Set up the Organizations client
    org_client = boto3.client('organizations')

    # Set up the STS client
    sts_client = boto3.client('sts')

    # Set region to find stacks in
    region = "us-east-1"

    print("Fetching all accounts connected to the organization")
    list_accounts = get_all_accounts(org_client)

    # Getting only the account IDs of the active AWS accounts
    sub_accounts = [(a["Id"], a["Name"]) for a in list_accounts if a["Status"] == "ACTIVE"]
    print(f"Found {len(sub_accounts)} accounts")

    if accounts:
        sub_accounts = [sa for sa in sub_accounts if sa[0] in accounts]

    with concurrent.futures.ThreadPoolExecutor() as executor:
        futures = [executor.submit(delete_stacks, sts_client, sub_account, control_role, region, just_print)
                   for sub_account in sub_accounts]
        print(color(f"Number of threads created: {len(futures)}", "blue"))
        completed_count = 0
        for _ in concurrent.futures.as_completed(futures):
            completed_count += 1
            if completed_count % 50 == 0:
                completed_percentage = int(completed_count / len(futures) * 100)
                print(color(f"{completed_count} threads completed out of "
                            f"{len(futures)} ({completed_percentage}%)", "blue"))
        print(color("All threads completed", "green"))


def delete_stacks(sts_client, sub_account, control_role, region, just_print):
    try:
        # Assume the role in the sub_account[0]
        assumed_role = sts_client.assume_role(
            RoleArn=f'arn:aws:iam::{sub_account[0]}:role/{control_role}',
            RoleSessionName='MySessionName'
        )
    except Exception as e:
        print(color(f"Account: {sub_account[0]} | Can't assume role, Error: {e}", "red"))
        return

    print(color(f"Account: {sub_account[0]} | Initializing Boto session", "blue"))
    sub_account_session = boto3.Session(
        aws_access_key_id=assumed_role['Credentials']['AccessKeyId'],
        aws_secret_access_key=assumed_role['Credentials']['SecretAccessKey'],
        aws_session_token=assumed_role['Credentials']['SessionToken']
    )
    print(color(f"Account: {sub_account[0]} | Session initialized successfully", "green"))

    try:
        cft_client = sub_account_session.client("cloudformation", region_name=region)
        list_stacks = cft_client.list_stacks()
        cft_stacks = [stack for stack in list_stacks['StackSummaries'] if "TemplateDescription" in stack]
        stream_stacks = [s for s in cft_stacks if 'lightlytics' in s['TemplateDescription'].lower()
                         and 'ParentId' not in s
                         and s['StackStatus'] == 'CREATE_COMPLETE'
                         and s['CreationTime'].date() == datetime.date(2024, 3, 1)
                         or s['CreationTime'].date() == datetime.date(2024, 2, 22)]
        for s in stream_stacks:
            if just_print:
                print(f"Account: {sub_account[0]} | Stack to be deleted: {s['StackName']}")
            else:
                print(f"Account: {sub_account[0]} | Deleting {s['StackName']}")
                cft_client.delete_stack(StackName=s['StackName'])
    except Exception as e:
        print(color(f"Account: {sub_account[0]} | Error found on us-east-1, error: {e}", "red"))
        return


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description='This script will remove specific StreamSec (Lightlytics) stacks from the Organization accounts.')
    parser.add_argument(
        "--aws_profile_name", help="The AWS profile with admin permissions for the organization account",
        default="staging")
    parser.add_argument(
        "--accounts", help="Accounts list to iterate when creating the report (e.g '123123123123,321321321321')",
        required=False)
    parser.add_argument(
        "--control_role", help="Specify a role for control", default="OrganizationAccountAccessRole")
    parser.add_argument(
        "--just_print", action="store_true")
    args = parser.parse_args()
    main(args.aws_profile_name, args.accounts, control_role=args.control_role, just_print=args.just_print)

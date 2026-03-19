import argparse
import boto3
import os
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


def main(accounts, aws_profile_name, just_print=False, force_delete_failed=False, stack_name_contains=None):
    if accounts:
        accounts = accounts.replace(" ", "").split(",")

    print(color("Creating Boto3 Session", "blue"))
    # Set the AWS_PROFILE environment variable
    os.environ['AWS_PROFILE'] = aws_profile_name

    # Set up the Organizations client
    org_client = boto3.client('organizations', region_name='us-east-1')

    # Set up the STS client
    sts_client = boto3.client('sts', region_name='us-east-1')

    # Get all activated regions from Org account
    regions = [region['RegionName'] for region in boto3.client('ec2', region_name='us-east-1').describe_regions()['Regions']]

    print("Fetching all accounts connected to the organization")
    list_accounts = get_all_accounts(org_client)

    # Getting only the account IDs of the active AWS accounts
    sub_accounts = [(a["Id"], a["Name"]) for a in list_accounts if a["Status"] == "ACTIVE"]
    print(f"Found {len(sub_accounts)} accounts")

    if accounts:
        sub_accounts = [sa for sa in sub_accounts if sa[0] in accounts]

    print(color(f"Accounts to-be deleted: {[sa[0] for sa in sub_accounts]}", "blue"))

    for sub_account in sub_accounts:
        try:
            # Assume the role in the sub_account[0]
            assumed_role = sts_client.assume_role(
                RoleArn=f'arn:aws:iam::{sub_account[0]}:role/OrganizationAccountAccessRole',
                RoleSessionName='MySessionName'
            )
        except Exception as e:
            print(color(f"Account: {sub_account[0]} | Can't assume role, skipping. Error: {e}", "red"))
            continue

        print(color(f"Account: {sub_account[0]} | Initializing Boto session", "blue"))
        sub_account_session = boto3.Session(
            aws_access_key_id=assumed_role['Credentials']['AccessKeyId'],
            aws_secret_access_key=assumed_role['Credentials']['SecretAccessKey'],
            aws_session_token=assumed_role['Credentials']['SessionToken']
        )
        print(color(f"Account: {sub_account[0]} | Session initialized successfully", "green"))

        delete_stacks_in_all_regions(sub_account, sub_account_session, regions, just_print, force_delete_failed, stack_name_contains)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description='This script will delete all Lightlytics/StreamSecurity stacks from organization accounts.')
    parser.add_argument(
        "--accounts", help="Accounts list to iterate (e.g '123123123123,321321321321')",
        required=False)
    parser.add_argument(
        "--aws_profile_name", help="The AWS profile with admin permissions for the organization account",
        default="staging")
    parser.add_argument(
        "--just_print", action="store_true", help="Dry run - only print stacks that would be deleted")
    parser.add_argument(
        "--force_delete_failed", action="store_true",
        help="Only target DELETE_FAILED stacks and use FORCE_DELETE_STACK mode")
    parser.add_argument(
        "--stack_name_contains", help="Filter stacks by custom name pattern (case-insensitive). "
        "When provided, replaces the default Lightlytics/lightlytics filter.",
        required=False)
    args = parser.parse_args()
    main(args.accounts, args.aws_profile_name, just_print=args.just_print, force_delete_failed=args.force_delete_failed, stack_name_contains=args.stack_name_contains)

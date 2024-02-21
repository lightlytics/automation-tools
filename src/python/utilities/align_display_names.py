import argparse
import boto3
import os
import sys
from termcolor import colored as color

# Add the project root directory to the Python path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')))
try:
    from src.python.common.boto_common import *
    from src.python.common.graph_common import GraphCommon
except ModuleNotFoundError:
    sys.path.append("../../..")
    from src.python.common.boto_common import *
    from src.python.common.graph_common import GraphCommon


def main(environment, ll_username, ll_password, aws_profile_name):
    print(color("Trying to login into Stream", "blue"))
    ll_url = f"https://{environment}.streamsec.io/graphql"
    graph_client = GraphCommon(ll_url, ll_username, ll_password)
    print(color("Logged in successfully!", "green"))

    print(color("Creating Boto3 Session", "blue"))
    # Set the AWS_PROFILE environment variable
    os.environ['AWS_PROFILE'] = aws_profile_name

    # Set up the Organizations client
    org_client = boto3.client('organizations')

    print(color("Fetching all accounts connected to the organization", "blue"))
    list_accounts = get_all_accounts(org_client)

    # Getting only the account IDs of the active AWS accounts
    sub_accounts = [(a["Id"], a["Name"]) for a in list_accounts if a["Status"] == "ACTIVE"]
    print(color(f"Found {len(sub_accounts)} AWS accounts", "blue"))

    # Getting Stream integrated accounts
    ll_integrated_accounts = [a["aws_account_id"] for a in graph_client.get_accounts()]

    # Setting new variable for fixed accounts
    accounts_display_fixed = []

    for sub_account in sub_accounts:
        if sub_account[0] not in ll_integrated_accounts:
            print(color(f"Account {sub_account[0]} is not integrated", "yellow"))
            continue
        try:
            sub_account_info = graph_client.get_specific_account(sub_account[0])
            if sub_account_info['display_name'] == sub_account[0]:
                print(color(f"Changing account display name to {sub_account[1]}", "blue"))
                graph_client.update_account_display_name(sub_account[0], sub_account[1])
                accounts_display_fixed.append(sub_account)
                print(color(f"Display name changed!", "green"))

        except Exception as e:
            # Print the error message
            print(color(f"Error for sub_account {sub_account[0]}: {e}", "red"))
            continue

    print(color("Finished successfully!", "green"))
    print(accounts_display_fixed)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description='This script will integrate Stream environment with every account in the organization.')
    parser.add_argument(
        "--environment_sub_domain", help="The Stream environment sub domain")
    parser.add_argument(
        "--environment_user_name", help="The Stream environment user name")
    parser.add_argument(
        "--environment_password", help="The Stream environment password")
    parser.add_argument(
        "--aws_profile_name", help="The AWS profile with admin permissions for the organization account",
        default="staging")
    args = parser.parse_args()
    main(args.environment_sub_domain, args.environment_user_name, args.environment_password, args.aws_profile_name)

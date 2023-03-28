import argparse
import boto3
import os
import random
from pprint import pprint
from src.python.common.boto_common import *
from src.python.common.graph_common import GraphCommon
from termcolor import colored as color


def main(environment, ll_username, ll_password):
    # Setting up variables
    random_int = random.randint(1000000, 9999999)

    print(color("Trying to login into Lightlytics", "blue"))
    ll_url = f"https://{environment}.lightlytics.com/graphql"
    graph_client = GraphCommon(ll_url, ll_username, ll_password)
    print(color("Logged in successfully!", "green"))

    print(color("Creating Boto3 Session", "blue"))
    # Set the AWS_PROFILE environment variable
    os.environ['AWS_PROFILE'] = 'staging'

    # Set up the Organizations client
    org_client = boto3.client('organizations')

    # Set up the STS client
    sts_client = boto3.client('sts')

    # Get all activated regions from Org account
    regions = [region['RegionName'] for region in boto3.client('ec2').describe_regions()['Regions']]

    print(color("Fetching all accounts connected to the organization", "blue"))
    list_accounts = get_all_accounts(org_client)

    # Getting only the account IDs of the active AWS accounts
    sub_accounts = [a["Id"] for a in list_accounts if a["Status"] == "ACTIVE"]
    print(color(f"Found {len(sub_accounts)} accounts", "blue"))

    # Setting the dict for successfully integrated accounts
    accounts_integrated = {}

    for sub_account in sub_accounts:
        print(color(f"Starting integration on {sub_account}", color="blue"))
        try:
            # Assume the role in the sub_account
            assumed_role = sts_client.assume_role(
                RoleArn=f'arn:aws:iam::{sub_account}:role/OrganizationAccountAccessRole',
                RoleSessionName='MySessionName'
            )
            print(color(f"Initializing session for account: {sub_account}", "blue"))
            sub_account_session = boto3.Session(
                aws_access_key_id=assumed_role['Credentials']['AccessKeyId'],
                aws_secret_access_key=assumed_role['Credentials']['SecretAccessKey'],
                aws_session_token=assumed_role['Credentials']['SessionToken']
            )
            print(color("Session initialized successfully", "green"))

            print(color("Checking if integration already exists", "blue"))
            if sub_account in [acc["aws_account_id"] for acc in graph_client.get_accounts()]:
                print(color("Account is already integrated, skipping", "yellow"))
                continue

            print(color(f"Creating {sub_account} account in Lightlytics", "blue"))
            graph_client.create_account(sub_account, [sub_account_session.region_name])
            print(color("Account created successfully", "green"))

            print(color("Fetching relevant account information", "blue"))
            account_information = [acc for acc in graph_client.get_accounts()
                                   if acc["aws_account_id"] == sub_account][0]
            sub_account_template_url = account_information["template_url"]
            ll_collection_template = account_information["collection_template_url"]
            print(color("Finished fetching information", "green"))

            # Initializing "cloudformation" boto client
            cf = sub_account_session.client('cloudformation')

            print(color("Creating the CFT stack using Boto", "blue"))
            stack_creation_payload = create_stack_payload(f"LightlyticsStack-{random_int}", sub_account_template_url)
            sub_account_stack_id = cf.create_stack(**stack_creation_payload)["StackId"]
            print(color(f"{sub_account_stack_id} Created successfully", "green"))

            print(color("Waiting for the stack to finish deploying successfully", "blue"))
            wait_for_cloudformation(sub_account_stack_id, cf)

            print(color("Waiting for the account to finish integrating with Lightlytics", "blue"))
            account_status = graph_client.wait_for_account_connection(sub_account)
            if account_status != "READY":
                print(color(f"Account is in the state of {account_status}, integration failed", "red"))
                continue
            print(color(f"Account {sub_account} integrated successfully with Lightlytics", "green"))

            # Adding integrated account to finished dict
            accounts_integrated[sub_account] = []

            print(color("Getting active regions (Has EC2 instances)", "blue"))
            active_regions = get_active_regions(sub_account_session, regions)
            print(color(f"Active regions are: {active_regions}", "blue"))

            print(color("Updating regions in Lightlytics according to active regions", "blue"))
            graph_client.edit_regions(sub_account, active_regions)
            print(color(f"Updated regions to {active_regions}", "green"))

            print(color("Waiting for the account to finish editing regions", "blue"))
            account_status = graph_client.wait_for_account_connection(sub_account)
            if account_status != "READY":
                print(color(f"Account is in the state of {account_status}, integration failed", "red"))
                continue
            print(color(f"Editing regions finished successfully", "green"))

            print(color("Adding collection CFT stack for realtime events for each region", color="blue"))
            for region in active_regions:
                print(color(f"Adding collection CFT stack for {region}", "blue"))
                region_client = sub_account_session.client('cloudformation', region_name=region)
                stack_creation_payload = create_stack_payload(
                    f"LightlyticsStack-collection-{region}-{random_int}", ll_collection_template)
                collection_stack_id = region_client.create_stack(**stack_creation_payload)["StackId"]
                print(color(f"Collection stack {collection_stack_id} deploying", "blue"))

                print(color("Waiting for the stack to finish deploying successfully", "blue"))
                wait_for_cloudformation(collection_stack_id, region_client)

                # Adding realtime to finished dict
                accounts_integrated[sub_account].append(region)
            print(color(f"Realtime enabled for {active_regions}", "green"))

        except Exception as e:
            # Print the error message
            print(color(f"Error for sub_account {sub_account}: {e}", "red"))
            continue

    print(color("Integration finished successfully!", "green"))
    pprint(accounts_integrated)


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

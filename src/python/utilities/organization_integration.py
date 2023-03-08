import argparse
import boto3
import botocore
import os
import random
from botocore.exceptions import ClientError
from src.python.common.boto_common import *
from src.python.common.graph_common import GraphCommon


def main(environment, ll_username, ll_password):
    # Setting up variables
    random_int = random.randint(1000000, 9999999)

    print("Trying to login into Lightlytics")
    # TODO REMOVE io URL
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

    # Get all activated regions from Org account
    regions = [region['RegionName'] for region in boto3.client('ec2').describe_regions()['Regions']]

    print("Fetching all accounts connected to the organization")
    list_accounts = get_all_accounts(org_client)

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
            graph_client.create_account(sub_account, [sub_account_session.region_name])
            print("Account created successfully")

            print("Fetching relevant account information")
            account_information = [acc for acc in graph_client.get_accounts()
                                   if acc["aws_account_id"] == sub_account][0]
            sub_account_template_url = account_information["template_url"]
            ll_collection_template = account_information["collection_template_url"]
            print("Finished fetching information")

            # Initializing "cloudformation" boto client
            cf = sub_account_session.client('cloudformation')

            print("Creating the CFT stack using Boto")
            stack_creation_payload = create_stack_payload(f"LightlyticsStack-{random_int}", sub_account_template_url)
            sub_account_stack_id = cf.create_stack(**stack_creation_payload)["StackId"]
            print(f"{sub_account_stack_id} Created successfully")

            print("Waiting for the stack to finish deploying successfully")
            wait_for_cloudformation(sub_account_stack_id, cf)

            print("Waiting for the account to finish integrating with Lightlytics")
            account_status = graph_client.wait_for_account_connection(sub_account)
            if account_status != "READY":
                print(f"Account is in the state of {account_status}, integration failed")
                continue
            print(f"Account {sub_account} integrated successfully with Lightlytics")

            print("Getting active regions (Has EC2 instances)")
            active_regions = get_active_regions(sub_account_session, regions)
            print(f"Active regions are: {active_regions}")

            print("Updating regions in Lightlytics according to active regions")
            graph_client.edit_regions(sub_account, active_regions)
            print(f"Updated regions to {active_regions}")

            print("Waiting for the account to finish editing regions")
            account_status = graph_client.wait_for_account_connection(sub_account)
            if account_status != "READY":
                print(f"Account is in the state of {account_status}, integration failed")
                continue
            print(f"Editing regions finished successfully")

            print("Adding collection CFT stack for realtime events for each region")
            for region in active_regions:
                print(f"Adding collection CFT stack for {region}")
                region_client = sub_account_session.client('cloudformation', region_name=region)
                stack_creation_payload = create_stack_payload(
                    f"LightlyticsStack-collection-{region}-{random_int}", ll_collection_template)
                collection_stack_id = region_client.create_stack(**stack_creation_payload)["StackId"]
                print(f"Collection stack {collection_stack_id} deploying")

                print("Waiting for the stack to finish deploying successfully")
                wait_for_cloudformation(sub_account_stack_id, region_client)
            print(f"Realtime enabled for {active_regions}")

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

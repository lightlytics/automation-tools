import argparse
import boto3
import os
import random
import sys
from pprint import pprint
from termcolor import colored as color

try:
    from src.python.common.boto_common import *
    from src.python.common.graph_common import GraphCommon
except ModuleNotFoundError:
    sys.path.append("../../..")
    from src.python.common.boto_common import *
    from src.python.common.graph_common import GraphCommon


def main(environment, ll_username, ll_password, aws_profile_name):
    # Setting up variables
    random_int = random.randint(1000000, 9999999)

    print(color("Trying to login into Lightlytics", "blue"))
    ll_url = f"https://{environment}.lightlytics.com/graphql"
    graph_client = GraphCommon(ll_url, ll_username, ll_password)
    print(color("Logged in successfully!", "green"))

    print(color("Creating Boto3 Session", "blue"))
    # Set the AWS_PROFILE environment variable
    os.environ['AWS_PROFILE'] = aws_profile_name

    # Set up the Organizations client
    org_client = boto3.client('organizations')

    # Set up the STS client
    sts_client = boto3.client('sts')

    # Get all activated regions from Org account
    regions = [region['RegionName'] for region in boto3.client('ec2').describe_regions()['Regions']]

    print(color("Fetching all accounts connected to the organization", "blue"))
    list_accounts = get_all_accounts(org_client)

    # Getting only the account IDs of the active AWS accounts
    sub_accounts = [(a["Id"], a["Name"]) for a in list_accounts if a["Status"] == "ACTIVE"]
    print(color(f"Found {len(sub_accounts)} accounts", "blue"))

    # Setting the dict for successfully integrated accounts
    accounts_integrated = {}

    for sub_account in sub_accounts:
        print(color(f"Starting integration on {sub_account[0]}", color="blue"))
        try:
            # Assume the role in the sub_account[0]
            assumed_role = sts_client.assume_role(
                RoleArn=f'arn:aws:iam::{sub_account[0]}:role/OrganizationAccountAccessRole',
                RoleSessionName='MySessionName'
            )
            print(color(f"Initializing session for account: {sub_account[0]}", "blue"))
            sub_account_session = boto3.Session(
                aws_access_key_id=assumed_role['Credentials']['AccessKeyId'],
                aws_secret_access_key=assumed_role['Credentials']['SecretAccessKey'],
                aws_session_token=assumed_role['Credentials']['SessionToken']
            )
            print(color("Session initialized successfully", "green"))

            print(color("Checking if integration already exists", "blue"))
            ll_integrated = False
            try:
                sub_account_information = \
                    [acc for acc in graph_client.get_accounts() if sub_account[0] == acc["aws_account_id"]][0]
                if sub_account_information["status"] == "UNINITIALIZED":
                    ll_integrated = True
                    print(color(f"Account {sub_account[0]} is integrated but uninitialized, continuing", "blue"))
                elif sub_account_information["status"] == "READY":
                    accounts_integrated[sub_account[0]] = []
                    print(color("Integration exists and in READY state", "green"))
                    print(color("Checking if regions are updated", "blue"))
                    current_regions = sub_account_information["aws_regions"]
                    potential_regions = get_active_regions(sub_account_session, regions)
                    if sorted(current_regions) != sorted(potential_regions):
                        print(color(f"Regions are different, updating to {potential_regions}", "blue"))
                        if not update_regions(graph_client, sub_account, potential_regions):
                            continue
                    else:
                        print(color(f"Regions are the same", "green"))
                    print(color("Checking if realtime regions are functioning", "blue"))
                    realtime_regions = sub_account_information["realtime_regions"] or []
                    regions_to_integrate = [i for i in potential_regions if i not in realtime_regions]
                    if len(regions_to_integrate) > 0:
                        print(color(f"Realtime is not enabled on all regions, adding support", "blue"))
                        accounts_integrated = deploy_collection_stack(
                            regions_to_integrate, sub_account_session, random_int, sub_account_information,
                            accounts_integrated, sub_account)
                    else:
                        print(color(f"All regions are integrated to realtime", "green"))
                    continue
                else:
                    raise Exception(f"Account is in {sub_account_information['status']} "
                                    f"status at Lightlytics, remove it and try again")
            except IndexError:
                pass

            # If account is not already integrated to Lightlytics
            if not ll_integrated:
                print(color(f"Creating {sub_account[0]} account in Lightlytics", "blue"))
                graph_client.create_account(
                    sub_account[0], [sub_account_session.region_name], display_name=sub_account[1])
                print(color("Account created successfully", "green"))

            print(color("Fetching relevant account information", "blue"))
            account_information = [acc for acc in graph_client.get_accounts()
                                   if acc["aws_account_id"] == sub_account[0]][0]

            # Deploying the initial integration stack
            if not deploy_init_stack(account_information, graph_client, sub_account, sub_account_session, random_int):
                continue

            # Adding integrated account to finished dict
            accounts_integrated[sub_account[0]] = []

            print(color("Getting active regions (Has EC2 instances)", "blue"))
            active_regions = get_active_regions(sub_account_session, regions)
            print(color(f"Active regions are: {active_regions}", "blue"))

            # Updating the regions in Lightlytics and waiting
            if not update_regions(graph_client, sub_account, active_regions):
                continue

            # Deploying collections stacks for all regions
            accounts_integrated = deploy_collection_stack(
                active_regions, sub_account_session, random_int, account_information, accounts_integrated, sub_account)

        except Exception as e:
            # Print the error message
            print(color(f"Error for sub_account {sub_account[0]}: {e}", "red"))
            continue

    print(color("Integration finished successfully!", "green"))
    pprint(accounts_integrated)


def deploy_init_stack(account_information, graph_client, sub_account, sub_account_session, random_int):
    sub_account_template_url = account_information["template_url"]
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
    account_status = graph_client.wait_for_account_connection(sub_account[0])
    if account_status != "READY":
        print(color(f"Account is in the state of {account_status}, integration failed", "red"))
        return False
    print(color(f"Account {sub_account[0]} integrated successfully with Lightlytics", "green"))
    return True


def update_regions(graph_client, sub_account, active_regions):
    print(color("Updating regions in Lightlytics according to active regions", "blue"))
    graph_client.edit_regions(sub_account[0], active_regions)
    print(color(f"Updated regions to {active_regions}", "green"))

    print(color("Waiting for the account to finish editing regions", "blue"))
    account_status = graph_client.wait_for_account_connection(sub_account[0])
    if account_status != "READY":
        print(color(f"Account is in the state of {account_status}, integration failed", "red"))
        return False
    print(color(f"Editing regions finished successfully", "green"))
    return True


def deploy_collection_stack(
        active_regions, sub_account_session, random_int, account_information, accounts_integrated, sub_account):
    print(color("Adding collection CFT stack for realtime events for each region", color="blue"))
    for region in active_regions:
        print(color(f"Adding collection CFT stack for {region}", "blue"))
        region_client = sub_account_session.client('cloudformation', region_name=region)
        stack_creation_payload = create_stack_payload(
            f"LightlyticsStack-collection-{region}-{random_int}",
            account_information["collection_template_url"])
        collection_stack_id = region_client.create_stack(**stack_creation_payload)["StackId"]
        print(color(f"Collection stack {collection_stack_id} deploying", "blue"))

        print(color("Waiting for the stack to finish deploying successfully", "blue"))
        wait_for_cloudformation(collection_stack_id, region_client)

        # Adding realtime to finished dict
        accounts_integrated[sub_account[0]].append(region)
    print(color(f"Realtime enabled for {active_regions}", "green"))
    return accounts_integrated


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description='This script will integrate Lightlytics environment with every account in the organization.')
    parser.add_argument(
        "--environment_sub_domain", help="The Lightlytics environment sub domain")
    parser.add_argument(
        "--environment_user_name", help="The Lightlytics environment user name")
    parser.add_argument(
        "--environment_password", help="The Lightlytics environment password")
    parser.add_argument(
        "--aws_profile_name", help="The AWS profile with admin permissions for the organization account",
        default="staging")
    args = parser.parse_args()
    main(args.environment_sub_domain, args.environment_user_name, args.environment_password, args.aws_profile_name)

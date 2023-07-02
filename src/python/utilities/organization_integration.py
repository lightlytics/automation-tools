import argparse
import boto3
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


def main(environment, ll_username, ll_password, aws_profile_name, accounts, parallel):
    # Setting up variables
    random_int = random.randint(1000000, 9999999)
    if accounts:
        accounts = accounts.replace(" ", "").split(",")

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

    if accounts:
        sub_accounts = [sa for sa in sub_accounts if sa[0] in accounts]

    print(color(f"Accounts to-be integrated: {[sa[0] for sa in sub_accounts]}", "blue"))

    if parallel:
        with concurrent.futures.ThreadPoolExecutor(max_workers=parallel) as executor:
            # Submit tasks to the thread pool
            results = [executor.submit(
                integrate_sub_account,
                sub_account, sts_client, graph_client, regions, random_int, parallel
            ) for sub_account in sub_accounts]
            # Wait for all tasks to complete
            concurrent.futures.wait(results)
    else:
        for sub_account in sub_accounts:
            integrate_sub_account(sub_account, sts_client, graph_client, regions, random_int)

    print(color("Integration finished successfully!", "green"))


def integrate_sub_account(sub_account, sts_client, graph_client, regions, random_int, parallel=False):
    print(color(f"Account: {sub_account[0]} | Starting integration", color="blue"))
    try:
        # Assume the role in the sub_account[0]
        assumed_role = sts_client.assume_role(
            RoleArn=f'arn:aws:iam::{sub_account[0]}:role/OrganizationAccountAccessRole',
            RoleSessionName='MySessionName'
        )
        print(color(f"Account: {sub_account[0]} | Initializing Boto session", "blue"))
        sub_account_session = boto3.Session(
            aws_access_key_id=assumed_role['Credentials']['AccessKeyId'],
            aws_secret_access_key=assumed_role['Credentials']['SecretAccessKey'],
            aws_session_token=assumed_role['Credentials']['SessionToken']
        )
        print(color(f"Account: {sub_account[0]} | Session initialized successfully", "green"))

        print(color(f"Account: {sub_account[0]} | Checking if integration already exists", "blue"))
        ll_integrated = False
        try:
            sub_account_information = \
                [acc for acc in graph_client.get_accounts() if sub_account[0] == acc["cloud_account_id"]][0]
            if sub_account_information["status"] == "UNINITIALIZED":
                ll_integrated = True
                print(color(f"Account: {sub_account[0]} | Integrated but uninitialized, continuing", "blue"))
            elif sub_account_information["status"] == "READY":
                print(color(f"Account: {sub_account[0]} | Integration exists and in READY state", "green"))
                print(color(f"Account: {sub_account[0]} | Checking if regions are updated", "blue"))
                current_regions = sub_account_information["cloud_regions"]
                potential_regions = get_active_regions(sub_account_session, regions)
                if sorted(current_regions) != sorted(potential_regions):
                    print(color(
                        f"Account: {sub_account[0]} | Regions are different, updating to {potential_regions}", "blue"))
                    if not update_regions(graph_client, sub_account, potential_regions, not parallel):
                        err_msg = f"Account: {sub_account[0]} | Something went wrong with regions update"
                        print(color(err_msg, "red"))
                        raise Exception(err_msg)
                else:
                    print(color(f"Account: {sub_account[0]} | Regions are the same", "green"))
                print(color(f"Account: {sub_account[0]} | Checking if realtime regions are functioning", "blue"))
                realtime_regions = sub_account_information["realtime_regions"]
                if realtime_regions is None:
                    realtime_regions = []
                realtime_region_names = [r["region_name"] for r in realtime_regions]
                regions_to_integrate = [i for i in potential_regions if i not in realtime_region_names]
                if len(regions_to_integrate) > 0:
                    print(color(f"Account: {sub_account[0]} | Realtime is not enabled on all regions, "
                                f"adding support for {regions_to_integrate}", "blue"))
                    deploy_all_collection_stacks(
                        regions_to_integrate, sub_account_session, random_int, sub_account_information, sub_account)
                else:
                    print(color(f"Account: {sub_account[0]} | All regions are integrated to realtime", "green"))
                return
            else:
                err_msg = f"Account: {sub_account[0]} | Account is in {sub_account_information['status']} " \
                          f"status at Lightlytics, remove it and try again"
                print(color(err_msg, "red"))
                raise Exception(err_msg)
        except IndexError:
            pass

        # If account is not already integrated to Lightlytics
        if not ll_integrated:
            print(color(f"Account: {sub_account[0]} | Creating account in Lightlytics", "blue"))
            graph_client.create_account(
                sub_account[0], [sub_account_session.region_name], display_name=sub_account[1])
            print(color(f"Account: {sub_account[0]} | Account created successfully", "green"))

        print(color(f"Account: {sub_account[0]} | Fetching relevant account information", "blue"))
        account_information = [acc for acc in graph_client.get_accounts()
                               if acc["cloud_account_id"] == sub_account[0]][0]

        # Deploying the initial integration stack
        if not deploy_init_stack(
                account_information, graph_client, sub_account, sub_account_session, random_int, not parallel):
            err_msg = f"Account: {sub_account[0]} | Something went wrong with init stack deployment"
            print(color(err_msg, "red"))
            raise Exception(err_msg)

        print(color(f"Account: {sub_account[0]} | Getting active regions (Has EC2 instances)", "blue"))
        active_regions = get_active_regions(sub_account_session, regions)
        print(color(f"Account: {sub_account[0]} | Active regions are: {active_regions}", "blue"))

        # Updating the regions in Lightlytics and waiting
        if not update_regions(graph_client, sub_account, active_regions, not parallel):
            err_msg = f"Account: {sub_account[0]} | Something went wrong with regions update"
            print(color(err_msg, "red"))
            raise Exception(err_msg)

        # Deploying collections stacks for all regions
        deploy_all_collection_stacks(
            active_regions, sub_account_session, random_int, account_information, sub_account)

        return

    except Exception as e:
        err_msg = f"Account: {sub_account[0]} | Something went wrong: {e}"
        print(color(err_msg, "red"))
        raise Exception(err_msg)


def update_regions(graph_client, sub_account, active_regions, wait=True):
    print(color(f"Account: {sub_account[0]} | Updating regions in Lightlytics according to active regions", "blue"))
    graph_client.edit_regions(sub_account[0], active_regions)
    print(color(f"Account: {sub_account[0]} | Updated regions to {active_regions}", "green"))

    if wait:
        print(color(f"Account: {sub_account[0]} | Waiting for the account to finish editing regions", "blue"))
        account_status = graph_client.wait_for_account_connection(sub_account[0])
        if account_status != "READY":
            print(color(
                f"Account: {sub_account[0]} | Account is in the state of {account_status}, integration failed", "red"))
            return False
    print(color(f"Account: {sub_account[0]} | Editing regions finished successfully", "green"))
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
    parser.add_argument(
        "--aws_profile_name", help="The AWS profile with admin permissions for the organization account",
        default="staging")
    parser.add_argument(
        "--accounts", help="Accounts list to iterate when creating the report (e.g '123123123123,321321321321')",
        required=False)
    parser.add_argument(
        "--parallel", help="Number of threads for parallel integration", type=int, required=False)
    args = parser.parse_args()
    main(args.environment_sub_domain, args.environment_user_name, args.environment_password,
         args.aws_profile_name, args.accounts, args.parallel)

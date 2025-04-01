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


def main(environment_url, ll_username, ll_password, aws_profile_name, accounts, parallel,
         ws_id=None, custom_tags=None, regions_to_integrate=None, control_role="OrganizationAccountAccessRole", response=False, response_region="us-east-1"):
    
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
    
    # Setting up variables
    random_int = random.randint(1000000, 9999999)
    if accounts:
        accounts = accounts.replace(" ", "").split(",")

    # Prepare tags if provided
    if custom_tags:
        custom_tags = [{'Key': k.split("|")[0], 'Value': k.split("|")[1]} for k in custom_tags.split(",")]

    # Prepare regions if provided
    if regions_to_integrate:
        regions_to_integrate = regions_to_integrate.split(",")

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
        # Set up the Organizations client
        org_client = boto3.client('organizations')

        # Set up the STS client
        sts_client = boto3.client('sts')

        # Set up org account variable
        org_account_id = sts_client.get_caller_identity().get('Account')

        # Get all activated regions from Org account
        regions = [region['RegionName'] for region in boto3.client('ec2').describe_regions()['Regions']]

        print(color("Fetching all accounts connected to the organization", "blue"))
        list_accounts = get_all_accounts(org_client)

        # Getting only the account IDs of the active AWS accounts
        sub_accounts = [(a["Id"], a["Name"]) for a in list_accounts if a["Status"] == "ACTIVE"]
        print(color(f"Found {len(sub_accounts)} accounts", "blue"))
    except Exception as e: 
        print(color(f"Error: {e}", "red"))
        return

    if accounts:
        sub_accounts = [sa for sa in sub_accounts if sa[0] in accounts]

    print(color(f"Accounts to-be integrated: {[sa[0] for sa in sub_accounts]}", "blue"))
       # Confirm with the user to continue
    confirmation = input("Do you want to continue? Type 'yes' to proceed: ")
    if confirmation.lower() != 'yes':
        print("Operation canceled.")
        return

    if parallel:
        with concurrent.futures.ThreadPoolExecutor(max_workers=parallel) as executor:
            # Submit tasks to the thread pool
            results = [executor.submit(
                integrate_sub_account,
                sub_account, sts_client, graph_client, regions, random_int, custom_tags, regions_to_integrate,
                control_role, org_account_id, parallel, response, response_region
            ) for sub_account in sub_accounts]
            # Wait for all tasks to complete
            concurrent.futures.wait(results)
    else:
        for sub_account in sub_accounts:
            integrate_sub_account(
                sub_account, sts_client, graph_client, regions, random_int,
                custom_tags, regions_to_integrate, control_role, org_account_id, response=response, response_region=response_region)

    print(color("Integration finished successfully!", "green"))


def integrate_sub_account(
        sub_account, sts_client, graph_client, regions, random_int, custom_tags, regions_to_integrate, control_role,
        org_account_id, parallel=False, response=False, response_region="us-east-1"):
    print(color(f"Account: {sub_account[0]} | Starting integration", color="blue"))
    try:
        if sub_account[0] == org_account_id:
            sub_account_session = boto3.Session()
        else:
            # Assume the role in the sub_account[0]
            assumed_role = sts_client.assume_role(
                RoleArn=f'arn:aws:iam::{sub_account[0]}:role/{control_role}',
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
                
                response_info = account_information["remediation"]
                if response_info is None and response:
                    graph_client.create_response_template(account_information["cloud_account_id"])
                    deploy_response_stack(
                        account_information, sub_account_session, sub_account, response_region, random_int, custom_tags, wait=True)
                
                print(color(f"Account: {sub_account[0]} | Checking if regions are updated", "blue"))
                current_regions = sub_account_information["cloud_regions"]
                if regions_to_integrate:
                    potential_regions = regions_to_integrate
                else:
                    potential_regions = get_active_regions(sub_account_session, regions)
                if sorted(current_regions) != sorted(potential_regions):
                    potential_regions.extend(current_regions)
                    potential_regions = list(set(potential_regions))
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
                        regions_to_integrate, sub_account_session, random_int, sub_account_information, sub_account,
                        custom_tags=custom_tags)
                else:
                    print(color(f"Account: {sub_account[0]} | All regions are integrated to realtime", "green"))
                return
            else:
                err_msg = f"Account: {sub_account[0]} | Account is in {sub_account_information['status']} " \
                          f"status at StreamSecurity, remove it and try again"
                print(color(err_msg, "red"))
                raise Exception(err_msg)
        except IndexError:
            pass

        # If account is not already integrated to StreamSecurity
        if not ll_integrated:
            print(color(f"Account: {sub_account[0]} | Creating account in StreamSecurity", "blue"))
            graph_client.create_account(
                sub_account[0], [sub_account_session.region_name], display_name=sub_account[1])
            print(color(f"Account: {sub_account[0]} | Account created successfully", "green"))

        print(color(f"Account: {sub_account[0]} | Fetching relevant account information", "blue"))
        account_information = [acc for acc in graph_client.get_accounts()
                               if acc["cloud_account_id"] == sub_account[0]][0]

        # Deploying the initial integration stack
        if not deploy_init_stack(
                account_information, graph_client, sub_account, sub_account_session, random_int, not parallel,
                custom_tags=custom_tags):
            err_msg = f"Account: {sub_account[0]} | Something went wrong with init stack deployment"
            print(color(err_msg, "red"))
            raise Exception(err_msg)

        print(color(f"Account: {sub_account[0]} | Setting regions", "blue"))
        if regions_to_integrate:
            active_regions = regions_to_integrate
        else:
            print(color(f"Account: {sub_account[0]} | Getting active regions (Has EC2 instances)", "blue"))
            active_regions = get_active_regions(sub_account_session, regions)
        print(color(f"Account: {sub_account[0]} | Active regions are: {active_regions}", "blue"))

        if response:
            graph_client.create_response_template(account_information["cloud_account_id"])
            deploy_response_stack(
                account_information, sub_account_session, sub_account, response_region, random_int, custom_tags, wait=True)

        # Updating the regions in StreamSecurity and waiting
        if not update_regions(graph_client, sub_account, active_regions, not parallel):
            err_msg = f"Account: {sub_account[0]} | Something went wrong with regions update"
            print(color(err_msg, "red"))
            raise Exception(err_msg)

        # Deploying collections stacks for all regions
        deploy_all_collection_stacks(
            active_regions, sub_account_session, random_int, account_information, sub_account, custom_tags=custom_tags)

        return

    except Exception as e:
        err_msg = f"Account: {sub_account[0]} | Something went wrong: {e}"
        print(color(err_msg, "red"))
        raise Exception(err_msg)


def update_regions(graph_client, sub_account, active_regions, wait=True):
    print(color(f"Account: {sub_account[0]} | Wait until account is initialized", "blue"))
    count = 0
    while True:
        sub_account_status = \
            [acc for acc in graph_client.get_accounts() if sub_account[0] == acc["cloud_account_id"]][0]['status']
        if sub_account_status == "UNINITIALIZED":
            time.sleep(1)
            count += 1
        else:
            break
        if count == 300:
            print(color(f"Account: {sub_account[0]} | Timed out after 5 minutes", "red"))
            raise Exception("Status change timed out, account still in uninitialized")
    print(color(f"Account: {sub_account[0]} | Account changed status to: {sub_account_status}", "blue"))

    print(color(f"Account: {sub_account[0]} | Updating regions in StreamSecurity according to active regions", "blue"))
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
    parser.add_argument(
        "--accounts", help="Accounts list to iterate when creating the report (e.g '123123123123,321321321321')",
        required=False)
    parser.add_argument(
        "--parallel", help="Number of threads for parallel integration", type=int, required=False)
    parser.add_argument(
        "--ws_id", help="ID of the WS to deploy to", required=False)
    parser.add_argument(
        "--custom_tags", help="Add custom tags to CFT Stacks and all resources, format: Name|Test,Env|Dev",
        required=False)
    parser.add_argument(
        "--regions", help="Force select specific regions to integrate, separated by comma", required=False)
    parser.add_argument(
        "--control_role", help="Specify a role for control", default="OrganizationAccountAccessRole", required=False)
    parser.add_argument(
        "--response", help="Create response stack", action="store_true", required=False)
    parser.add_argument(
        "--response_region", help="Region for response stack", required=False, default="us-east-1")
    args = parser.parse_args()
    main(args.environment_url, args.environment_user_name, args.environment_password,
         args.aws_profile_name, args.accounts, args.parallel,
         ws_id=args.ws_id, custom_tags=args.custom_tags, regions_to_integrate=args.regions,
         control_role=args.control_role, response=args.response, response_region=args.response_region)

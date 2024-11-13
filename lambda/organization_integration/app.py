import boto3
import random
import os
import concurrent.futures
from src.python.common.boto_common import *
from src.python.common.graph_common import GraphCommon

def lambda_handler(event, context):
    # Extract parameters from environment variables
    environment = os.environ.get('ENVIRONMENT')
    domain = os.environ.get('ENVIRONMENT_DOMAIN', 'streamsec.io')
    ll_username = os.environ.get('ENVIRONMENT_USER_NAME')
    ll_password = os.environ.get('ENVIRONMENT_PASSWORD')
    accounts = os.environ.get('ACCOUNTS', None)
    parallel = int(os.environ.get('PARALLEL', 1))  # Convert to int, default to 1
    ws_id = os.environ.get('WS_ID', None)
    custom_tags = os.environ.get('CUSTOM_TAGS', None)
    regions_to_integrate = os.environ.get('REGIONS', None)
    control_role = os.environ.get('CONTROL_ROLE', "OrganizationAccountAccessRole")

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

    print(f"Trying to login into Stream Security environment: {environment}")
    ll_url = f"https://{environment}.{domain}/graphql"
    graph_client = GraphCommon(ll_url, ll_username, ll_password, ws_id)
    print("Logged in successfully!")

    print("Creating Boto3 Session")
    
    # Set up the Organizations and STS clients
    org_client = boto3.client('organizations')
    sts_client = boto3.client('sts')

    # Set up org account variable
    org_account_id = sts_client.get_caller_identity().get('Account')

    # Get all activated regions from the Org account
    regions = [region['RegionName'] for region in boto3.client('ec2').describe_regions()['Regions']]

    print("Fetching all accounts connected to the organization")
    list_accounts = get_all_accounts(org_client)

    # Getting only the account IDs of the active AWS accounts
    sub_accounts = [(a["Id"], a["Name"]) for a in list_accounts if a["Status"] == "ACTIVE"]
    print(f"Found {len(sub_accounts)} accounts")

    if accounts:
        sub_accounts = [sa for sa in sub_accounts if sa[0] in accounts]

    print(f"Accounts to-be integrated: {[sa[0] for sa in sub_accounts]}")

    if parallel:
        with concurrent.futures.ThreadPoolExecutor(max_workers=parallel) as executor:
            # Submit tasks to the thread pool
            results = [executor.submit(
                integrate_sub_account,
                sub_account, sts_client, graph_client, regions, random_int, custom_tags, regions_to_integrate,
                control_role, org_account_id, parallel
            ) for sub_account in sub_accounts]
            # Wait for all tasks to complete
            concurrent.futures.wait(results)
    else:
        for sub_account in sub_accounts:
            integrate_sub_account(
                sub_account, sts_client, graph_client, regions, random_int,
                custom_tags, regions_to_integrate, control_role, org_account_id)

    print("Integration finished successfully!")

def integrate_sub_account(
        sub_account, sts_client, graph_client, regions, random_int, custom_tags, regions_to_integrate, control_role,
        org_account_id, parallel=False):
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
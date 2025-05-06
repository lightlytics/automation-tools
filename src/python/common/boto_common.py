import concurrent.futures
import datetime
import time
from termcolor import colored as color
import os

def get_all_accounts(org_client):
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
    return list_accounts


def wait_for_cloudformation(sub_account, cft_id, cf_client, timeout=240):
    """ Wait for stack to be deployed.
        :param sub_account (tup)    - Relevant account.
        :param timeout (int)        - Max waiting time; Defaults to 240.
        :param cft_id (str)         - Stack ID.
        :param cf_client (object)   - CF Session.
    """
    time.sleep(10)

    dt_start = datetime.datetime.utcnow()
    dt_diff = 0

    print(color(
        f"Account: {sub_account[0]} | Waiting for stack to finish creating, timeout is {timeout} seconds", "blue"))
    while dt_diff < timeout:
        stack_list = cf_client.list_stacks()
        status = [stack['StackStatus'] for stack in stack_list['StackSummaries'] if stack['StackId'] == cft_id][0]
        dt_finish = datetime.datetime.utcnow()
        dt_diff = (dt_finish - dt_start).total_seconds()

        if status == 'CREATE_COMPLETE':
            print(color(f'Account: {sub_account[0]} | Stack deployed successfully after {dt_diff} seconds', "green"))
            break
        elif status == 'ROLLBACK_IN_PROGRESS':
            err_msg = f"Account: {sub_account[0]} | Stack {cft_id} failed"
            print(color(err_msg, "red"))
            raise Exception(err_msg)
        else:
            time.sleep(1)
    if dt_diff >= timeout:
        print(color(f"Account: {sub_account[0]} | Timed out before stack has been created/deleted", "red"))
        return False
    return True


def create_stack_payload(stack_name, sub_account_template_url, custom_tags=None, params=None):
    stack_creation_payload = {
        "StackName": stack_name,
        "Capabilities": ['CAPABILITY_IAM', 'CAPABILITY_NAMED_IAM', 'CAPABILITY_AUTO_EXPAND'],
        "OnFailure": 'ROLLBACK',
        "EnableTerminationProtection": False,
        "TemplateURL": sub_account_template_url,
    }
    if custom_tags:
        stack_creation_payload['Tags'] = custom_tags
        
    if params:
        stack_creation_payload['Parameters'] = params
        
    return stack_creation_payload


def get_active_regions(sub_account_session, regions):
    active_regions = [sub_account_session.region_name]
    for region in regions:
        try:
            ec2_client = sub_account_session.client('ec2', region_name=region)
            instances = ec2_client.describe_instances()["Reservations"][0]["Instances"]
            if len(instances) > 0:
                active_regions.append(region)
        except:
            continue
    if "us-east-1" not in active_regions:
        active_regions.append("us-east-1")
    return list(set(active_regions))

def get_active_eks_regions(sub_account_session, regions):
    active_regions = []
    for region in regions:
        try:
            eks_client = sub_account_session.client('eks', region_name=region)
            eks_clusters = eks_client.list_clusters()
            if len(eks_clusters['clusters']) > 0:
                active_regions.append(region)
        except:
            continue
    return active_regions

def deploy_all_collection_stacks(
        active_regions, sub_account_session, random_int, account_information, sub_account, custom_tags=None):
    print(color(
        f"Account: {sub_account[0]} | Adding collection CFT stack for realtime events for each region in parallel "
        f"(Max 8 workers)", color="blue"))
    # List to hold the concurrent futures
    futures = []
    # Create a ThreadPoolExecutor with max_workers
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        # Iterate over active_regions and submit each task to the executor
        for region in active_regions:
            future = executor.submit(deploy_collection_stack, account_information,
                                     sub_account_session, sub_account, region, random_int, custom_tags, False)
            futures.append(future)
    # Wait for all the tasks to complete
    concurrent.futures.wait(futures)
    print(color(f"Account: {sub_account[0]} | Realtime enabled in regions: {active_regions}", "green"))
    return


def deploy_collection_stack(
        account_information, sub_account_session, sub_account, region, random_int, custom_tags, wait=True):
    # Existing code inside the for loop
    print(color(f"Account: {sub_account[0]} | Adding collection CFT stack for {region}", "blue"))
    region_client = sub_account_session.client('cloudformation', region_name=region)
    stack_creation_payload = create_stack_payload(
        f"LightlyticsStack-collection-{region}-{random_int}",
        account_information["collection_template_url"], custom_tags=custom_tags)
    collection_stack_id = region_client.create_stack(**stack_creation_payload)["StackId"]
    print(color(f"Account: {sub_account[0]} | Collection stack {collection_stack_id} deploying", "blue"))

    if wait:
        print(color(f"Account: {sub_account[0]} | Waiting for the stack to finish deploying successfully", "blue"))
        wait_for_cloudformation(sub_account, collection_stack_id, region_client)

def deploy_response_stack(
        environment_url, account_information, sub_account_session, sub_account, region, random_int, custom_tags, response_exclude_runbooks, wait=True):
    print(color(f"Account: {sub_account[0]} | Adding response CFT stack for {region}", "blue"))
    region_client = sub_account_session.client('cloudformation', region_name=region)
    
    params = [
        {
            "ParameterKey": "APIUrl",
            "ParameterValue": environment_url
        },
        {
            "ParameterKey": "APIToken",
            "ParameterValue": account_information["lightlytics_collection_token"]
        },
        {
            "ParameterKey": "ExternalId",
            "ParameterValue": account_information["external_id"]
        },
        {
            "ParameterKey": "TrustedAccountId",
            "ParameterValue": os.environ.get("STREAM_ACCOUNT_ID", "624907860825")
        }
    ]
    
    if response_exclude_runbooks != "":
        for runbook in response_exclude_runbooks.split(","):
            params.append({
                "ParameterKey": f"{runbook}Enabled",
                "ParameterValue": "false"
            })
    
    
    stack_creation_payload = create_stack_payload(
        f"LightlyticsStack-response-{region}-{random_int}",
        os.environ.get("STREAM_RESPONSE_CFT_URL", f"https://prod-lightlytics-public-cloudformation.s3.amazonaws.com/stream-security-remediation-latest-{region}.yaml"), custom_tags=custom_tags , params=params)
    response_stack_id = region_client.create_stack(**stack_creation_payload)["StackId"]
    print(color(f"Account: {sub_account[0]} | response stack {response_stack_id} deploying", "blue"))
    
    if wait:
        print(color(f"Account: {sub_account[0]} | Waiting for the stack to finish deploying successfully", "blue"))
        wait_for_cloudformation(sub_account, response_stack_id, region_client)
        print(color(f"Account: {sub_account[0]} | response stack deployed successfully", "green"))

def deploy_eks_audit_logs_stacks(
        environment_url, sub_account_information, sub_account_session, sub_account, eks_audit_logs_regions, random_int, custom_tags, wait=True):
    if not eks_audit_logs_regions:
        eks_audit_logs_regions = get_active_eks_regions(sub_account_session, sub_account_information["cloud_regions"])
    
    if not eks_audit_logs_regions:
        print(color(f"Account: {sub_account[0]} | No active EKS regions found, skipping EKS audit logs for {sub_account[0]}", "blue"))
        return
    
    params = [
        {
            "ParameterKey": "APIUrl",
            "ParameterValue": environment_url
        },
        {
            "ParameterKey": "APICollectionToken",
            "ParameterValue": sub_account_information["lightlytics_collection_token"]
        },
        {
            "ParameterKey": "EKSAuditCollectorPrefix",
            "ParameterValue": environment_url.split("//")[1].split(".")[0]
        }
    ]
    
    for region in eks_audit_logs_regions:
        # check if there is already a lambda function in the region
        region_client = sub_account_session.client('lambda', region_name=region)
        region_cloudformation_client = sub_account_session.client('cloudformation', region_name=region)
        try:
            region_client.get_function(FunctionName='StreamSec_EKSCloudWatchSubscriptionsFunction')
            print(color(f"Account: {sub_account[0]} | EKS audit logs lambda already exists in region {region}, skipping", "blue"))
            continue
        except region_client.exceptions.ResourceNotFoundException:
            pass
        
        print(color(f"Account: {sub_account[0]} | Adding EKS audit logs CFT stack for {region}", "blue"))
        stack_creation_payload = create_stack_payload(
            f"StreamSecurity-eks-audit-logs-{region}-{random_int}",
            os.environ.get("STREAM_EKS_AUDIT_LOGS_CFT_URL", f"https://public-lightlytics-cft.s3.amazonaws.com/eks-audit-collector-latest.yaml"), custom_tags=custom_tags, params=params)
        eks_audit_logs_stack_id = region_cloudformation_client.create_stack(**stack_creation_payload)["StackId"]
        print(color(f"Account: {sub_account[0]} | EKS audit logs stack {eks_audit_logs_stack_id} deploying", "blue"))
        
        if wait:
            print(color(f"Account: {sub_account[0]} | Waiting for the stack to finish deploying successfully", "blue"))
            wait_for_cloudformation(sub_account, eks_audit_logs_stack_id, region_cloudformation_client)
            print(color(f"Account: {sub_account[0]} | EKS audit logs stack deployed successfully", "green"))
        else:
            print(color(f"Account: {sub_account[0]} | EKS audit logs stack deployed successfully", "green"))

def deploy_init_stack(account_information, graph_client, sub_account, sub_account_session, random_int, wait=True,
                      custom_tags=None):
    sub_account_template_url = account_information["template_url"]
    print(color(f"Account: {sub_account[0]} | Finished fetching information", "green"))

    # Initializing "cloudformation" boto client
    cf = sub_account_session.client('cloudformation')

    print(color(f"Account: {sub_account[0]} | Creating the CFT stack using Boto", "blue"))
    stack_creation_payload = create_stack_payload(
        f"LightlyticsStack-{random_int}", sub_account_template_url, custom_tags=custom_tags)
    sub_account_stack_id = cf.create_stack(**stack_creation_payload)["StackId"]
    print(color(f"Account: {sub_account[0]} | {sub_account_stack_id} Created successfully", "green"))

    if wait:
        print(color(f"Account: {sub_account[0]} | Waiting for the stack to finish deploying successfully", "blue"))
        wait_for_cloudformation(sub_account, sub_account_stack_id, cf)

        print(color(f"Account: {sub_account[0]} | "
                    f"Waiting for the account to finish integrating with Lightlytics", "blue"))
        account_status = graph_client.wait_for_account_connection(sub_account[0])
        if account_status != "READY":
            print(color(
                f"Account: {sub_account[0]} | Account is in the state of {account_status}, integration failed", "red"))
            return False

    print(color(f"Account: {sub_account[0]} | Integrated successfully with StreamSecurity", "green"))
    return True


def delete_stacks_in_all_regions(sub_account, sub_account_session, regions, ll_url):
    print(color(f"Account: {sub_account[0]} | Deleting all stacks from all regions", "blue"))
    for region in regions:
        ll_stacks = filter_ll_stacks_from_url(sub_account_session, region, ll_url, return_only_names=False)
        if len(ll_stacks) > 0:
            print(color(f"Account: {sub_account[0]} | Deleting {len(ll_stacks)} stacks from region: {region}", "blue"))
        else:
            print(color(f"Account: {sub_account[0]} | No stacks in region: {region}", "green"))
        for ll_stack in ll_stacks:
            print(color(f"Account: {sub_account[0]} | Deleting stack: {ll_stack['StackName']}", "blue"))
            delete_stack(sub_account_session, region, ll_stack["StackName"])
            print(color(f"Account: {sub_account[0]} | Stack began deleting!", "green"))


def delete_stack(sub_account_session, region, stack_name):
    region_client = sub_account_session.client('cloudformation', region_name=region)
    region_client.delete_stack(StackName=stack_name)


def filter_ll_stacks_from_url(sub_account_session, region, ll_url, return_only_names=False):
    ll_stacks_to_return = []
    region_client = sub_account_session.client('cloudformation', region_name=region)
    try:
        stacks = region_client.describe_stacks()["Stacks"]
        if len(stacks) > 0:
            ll_stacks = [s for s in stacks if s["StackStatus"] != "DELETE_COMPLETE"
                         and "Lightlytics" in s["StackName"]
                         and "Parameters" in s]
            for ll_stack in ll_stacks:
                stack_params_url = [p["ParameterValue"] for p in ll_stack["Parameters"]
                                    if p["ParameterKey"] == "LightlyticsApiUrl"][0]
                if stack_params_url in ll_url:
                    ll_stacks_to_return.append(ll_stack)
                    parent_stacks = [s for s in stacks if s["StackId"] == ll_stack["ParentId"]]
                    ll_stacks_to_return.extend(parent_stacks)
        if return_only_names:
            return [s["StackName"] for s in ll_stacks_to_return]
        else:
            return ll_stacks_to_return
    except Exception:
        return []

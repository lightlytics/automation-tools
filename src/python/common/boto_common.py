import datetime
import time
from termcolor import colored as color


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
            raise Exception(f"Account: {sub_account[0]} | Stack {cft_id} failed")
        else:
            time.sleep(1)
    if dt_diff >= timeout:
        print(color(f"Account: {sub_account[0]} | Timed out before stack has been created/deleted", "red"))
        return False
    return True


def create_stack_payload(stack_name, sub_account_template_url):
    stack_creation_payload = {
        "StackName": stack_name,
        "Capabilities": ['CAPABILITY_IAM', 'CAPABILITY_NAMED_IAM', 'CAPABILITY_AUTO_EXPAND'],
        "OnFailure": 'ROLLBACK',
        "EnableTerminationProtection": False,
        "TemplateURL": sub_account_template_url
    }
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


def deploy_collection_stack(
        active_regions, sub_account_session, random_int, account_information, accounts_integrated, sub_account):
    print(color(
        f"Account: {sub_account[0]} | Adding collection CFT stack for realtime events for each region", color="blue"))
    for region in active_regions:
        print(color(f"Account: {sub_account[0]} | Adding collection CFT stack for {region}", "blue"))
        region_client = sub_account_session.client('cloudformation', region_name=region)
        stack_creation_payload = create_stack_payload(
            f"LightlyticsStack-collection-{region}-{random_int}",
            account_information["collection_template_url"])
        collection_stack_id = region_client.create_stack(**stack_creation_payload)["StackId"]
        print(color(f"Account: {sub_account[0]} | Collection stack {collection_stack_id} deploying", "blue"))

        print(color(f"Account: {sub_account[0]} | Waiting for the stack to finish deploying successfully", "blue"))
        wait_for_cloudformation(sub_account, collection_stack_id, region_client)

        # Adding realtime to finished dict
        accounts_integrated[sub_account[0]].append(region)
    print(color(f"Account: {sub_account[0]} | Realtime enabled in regions: {active_regions}", "green"))
    return accounts_integrated


def deploy_init_stack(account_information, graph_client, sub_account, sub_account_session, random_int):
    sub_account_template_url = account_information["template_url"]
    print(color(f"Account: {sub_account[0]} | Finished fetching information", "green"))

    # Initializing "cloudformation" boto client
    cf = sub_account_session.client('cloudformation')

    print(color(f"Account: {sub_account[0]} | Creating the CFT stack using Boto", "blue"))
    stack_creation_payload = create_stack_payload(f"LightlyticsStack-{random_int}", sub_account_template_url)
    sub_account_stack_id = cf.create_stack(**stack_creation_payload)["StackId"]
    print(color(f"Account: {sub_account[0]} | {sub_account_stack_id} Created successfully", "green"))

    print(color(f"Account: {sub_account[0]} | Waiting for the stack to finish deploying successfully", "blue"))
    wait_for_cloudformation(sub_account, sub_account_stack_id, cf)

    print(color(f"Account: {sub_account[0]} | Waiting for the account to finish integrating with Lightlytics", "blue"))
    account_status = graph_client.wait_for_account_connection(sub_account[0])
    if account_status != "READY":
        print(color(
            f"Account: {sub_account[0]} | Account is in the state of {account_status}, integration failed", "red"))
        return False
    print(color(f"Account: {sub_account[0]} | Integrated successfully with Lightlytics", "green"))
    return True


def update_regions(graph_client, sub_account, active_regions):
    print(color(f"Account: {sub_account[0]} | Updating regions in Lightlytics according to active regions", "blue"))
    graph_client.edit_regions(sub_account[0], active_regions)
    print(color(f"Account: {sub_account[0]} | Updated regions to {active_regions}", "green"))

    print(color(f"Account: {sub_account[0]} | Waiting for the account to finish editing regions", "blue"))
    account_status = graph_client.wait_for_account_connection(sub_account[0])
    if account_status != "READY":
        print(color(
            f"Account: {sub_account[0]} | Account is in the state of {account_status}, integration failed", "red"))
        return False
    print(color(f"Account: {sub_account[0]} | Editing regions finished successfully", "green"))
    return True

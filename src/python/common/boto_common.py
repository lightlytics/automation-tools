import datetime
import time
from termcolor import colored


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


def wait_for_cloudformation(cft_id, cf_client, timeout=180):
    """ Wait for stack to be deployed.
        :param timeout (int)        - Max waiting time; Defaults to 180.
        :param cft_id (str)         - Stack ID.
        :param cf_client (object)   - CF Session.
    """
    time.sleep(10)

    dt_start = datetime.datetime.utcnow()
    dt_diff = 0

    print(colored(f"Waiting for stack to finish creating, timeout is {timeout} seconds", "blue"))
    while dt_diff < timeout:
        stack_list = cf_client.list_stacks()
        status = [stack['StackStatus'] for stack in stack_list['StackSummaries'] if stack['StackId'] == cft_id][0]
        dt_finish = datetime.datetime.utcnow()
        dt_diff = (dt_finish - dt_start).total_seconds()

        if status == 'CREATE_COMPLETE':
            print(colored(f'Stack deployed successfully after {dt_diff} seconds', "green"))
            break
        else:
            time.sleep(1)
    if dt_diff >= timeout:
        print(colored("Timed out before stack has been created/deleted", "red"))
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
    return list(set(active_regions))

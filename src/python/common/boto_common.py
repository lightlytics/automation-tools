import datetime
import time


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
    dt_start = datetime.datetime.utcnow()
    dt_diff = 0

    print(f"Waiting for stack to finish creating, timeout is {timeout} seconds")
    while dt_diff < timeout:
        stack_list = cf_client.list_stacks()
        status = [stack['StackStatus'] for stack in stack_list['StackSummaries'] if stack['StackId'] == cft_id][0]
        dt_finish = datetime.datetime.utcnow()
        dt_diff = (dt_finish - dt_start).total_seconds()

        if status == 'CREATE_COMPLETE':
            print(f'Stack deployed successfully after {dt_diff} seconds')
            break
        else:
            time.sleep(1)
            time.sleep(20)
    if dt_diff >= timeout:
        print("Timed out before stack has been created/deleted")
        return False
    return True


def create_init_stack_payload(sub_account_template_url, random_int):
    stack_creation_payload = {
        "StackName": f"LightlyticsStack-{random_int}",
        "Capabilities": ['CAPABILITY_IAM', 'CAPABILITY_NAMED_IAM', 'CAPABILITY_AUTO_EXPAND'],
        "OnFailure": 'ROLLBACK',
        "EnableTerminationProtection": False,
        "TemplateURL": sub_account_template_url
    }
    return stack_creation_payload

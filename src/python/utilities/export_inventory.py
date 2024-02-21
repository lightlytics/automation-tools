import argparse
import concurrent.futures
import csv
import os
import sys

# Add the project root directory to the Python path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')))
try:
    from src.python.common.common import *
except ModuleNotFoundError:
    sys.path.append("../../..")
    from src.python.common.common import *


def main(environment, ll_username, ll_password, ll_f2a, ws_name, resource_type, accounts=None, tags=None, stage=None):
    # Setting up variables
    if accounts:
        accounts = accounts.replace(" ", "").split(",")

    # Connecting to Stream
    graph_client = get_graph_client(environment, ll_username, ll_password, ll_f2a, ws_name, stage)

    log.info("Get all accounts")
    all_accounts_raw = graph_client.get_accounts()
    all_accounts = [a['cloud_account_id'] for a in all_accounts_raw]
    log.info(f"Found {len(all_accounts)} account in workspace: {ws_name}")

    if accounts:
        log.info("Filtering accounts according to provided argument")
        all_accounts = [a for a in all_accounts if a in accounts]
        log.info(f"{len(all_accounts)} accounts remained")

    report_details = {
        "environment_name": environment.upper(),
        "environment_workspace": ws_name,
        "ws_id": graph_client.customer_id,
        "ll_url": graph_client.url,
        "accounts": {}
    }

    parsed_tags = []
    if tags:
        tags = tags.split(",")
        for tag in tags:
            parsed_tags.append(process_tag(tag))

    log.info("Searching resources in each account")
    with concurrent.futures.ThreadPoolExecutor() as executor:
        future_account_mapping = {}
        futures = []
        for account in all_accounts:
            future = executor.submit(graph_client.resources_search, account, resource_type, parsed_tags)
            future_account_mapping[future] = account
            futures.append(future)
        for future in futures:
            account = future_account_mapping[future]
            report_details["accounts"][account] = future.result()
    log.info("Finished adding resources!")
    log.info(f'Found {sum([len(r) for r in report_details["accounts"].values()])} resources of type "{resource_type}"')

    csv_file = f'Stream inventory export - {environment}.csv'

    log.info(f"Generating CSV file, file name: {csv_file}")
    with open(csv_file, 'w', newline='') as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(['Account', 'Account name', 'Resource ID', 'Resource Name', 'Resource Tags'])
        for account, resources in report_details['accounts'].items():
            for resource in resources:
                account_name = [a['display_name'] for a in all_accounts_raw if a['cloud_account_id'] == account][0]
                row = [account, account_name, resource['id'], resource['display_name'], resource['cloud_tags']]
                writer.writerow(row)
    log.info("File generated successfully, export complete!")

    return csv_file


def process_tag(tag):
    tag_key, tag_value = tag.split("|")
    if "~=" in tag_key:
        key_operand = "contains"
    else:
        key_operand = "equals"
    if "~=" in tag_value:
        value_operand = "contains"
    else:
        value_operand = "equals"
    tag_dict = {
        "key": tag_key.split("=")[-1],
        "key_operand": key_operand,
        "value": tag_value.split("=")[-1],
        "value_operand": value_operand
    }
    return tag_dict


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description='This script will integrate Stream environment with every account in the organization.')
    parser.add_argument(
        "--environment_sub_domain", help="The Stream environment sub domain", required=True)
    parser.add_argument(
        "--environment_user_name", help="The Stream environment user name", required=True)
    parser.add_argument(
        "--environment_password", help="The Stream environment password", required=True)
    parser.add_argument(
        "--environment_f2a_token", help="F2A Token if set", default=None)
    parser.add_argument(
        "--ws_name", help="The WS from which to fetch information", required=True)
    parser.add_argument(
        "--resource_type", help="The required resource to return", required=True)
    parser.add_argument(
        "--accounts", help="Accounts list to iterate when creating the report", required=False)
    parser.add_argument(
        "--tags", help="Tags to filter by, example: 'key=Name|value~=test,key=Vendor|value=StreamSec', "
                       "the '~=' means 'contains' instead of 'equal' operand, tags divided by ','",
        required=False)
    parser.add_argument(
        "--stage", action="store_true")
    args = parser.parse_args()
    main(args.environment_sub_domain, args.environment_user_name, args.environment_password, args.environment_f2a_token,
         args.ws_name, args.resource_type, args.accounts, args.tags, args.stage)

import argparse
import concurrent.futures
import csv
import os
import sys

from termcolor import colored as color

# Add the project root directory to the Python path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')))
try:
    from src.python.common.graph_common import GraphCommon
except ModuleNotFoundError:
    sys.path.append("../../..")
    from src.python.common.graph_common import GraphCommon


def main(environment, ll_username, ll_password, ws_name, resource_type, tags, accounts):
    # Setting up variables
    if accounts:
        accounts = accounts.replace(" ", "").split(",")

    print(color("Trying to login into Lightlytics", "blue"))
    ll_url = f"https://{environment}.lightlytics.com"
    ll_graph_url = f"{ll_url}/graphql"
    graph_client = GraphCommon(ll_graph_url, ll_username, ll_password)
    ws_id = graph_client.get_ws_id_by_name(ws_name)
    graph_client.change_client_ws(ws_id)
    print(color("Logged in successfully!", "green"))

    print(color("Get all accounts", "blue"))
    all_accounts = [a['cloud_account_id'] for a in graph_client.get_accounts()]
    print(color(f"Found {len(all_accounts)} account in workspace: {ws_name}", "green"))

    if accounts:
        print(color("Filtering accounts according to provided argument", "blue"))
        all_accounts = [a for a in all_accounts if a in accounts]
        print(color(f"{len(all_accounts)} accounts remained", "green"))

    report_details = {
        "environment_name": environment.upper(),
        "environment_workspace": ws_name,
        "ws_id": ws_id,
        "ll_url": ll_url,
        "accounts": {}
    }

    parsed_tags = []
    if tags:
        tags = tags.split(",")
        for tag in tags:
            parsed_tags.append(process_tag(tag))

    print(color("Searching resources in each account", "blue"))
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
    print(color("Finished adding resources!", "green"))

    csv_file = 'Lightlytics inventory export.csv'

    print(color(f"Generating CSV file, file name: {csv_file}", "blue"))
    with open(csv_file, 'w', newline='') as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(['Account', 'ID'])
        for account, resources in report_details['accounts'].items():
            for resource in resources:
                resource_id = resource['id']
                writer.writerow([account, resource_id])
    print(color("File generated successfully, export complete!", "green"))


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
        description='This script will integrate Lightlytics environment with every account in the organization.')
    parser.add_argument(
        "--environment_sub_domain", help="The Lightlytics environment sub domain", required=True)
    parser.add_argument(
        "--environment_user_name", help="The Lightlytics environment user name", required=True)
    parser.add_argument(
        "--environment_password", help="The Lightlytics environment password", required=True)
    parser.add_argument(
        "--ws_name", help="The WS from which to fetch information", required=True)
    parser.add_argument(
        "--resource_type", help="The required resource to return", required=True)
    parser.add_argument(
        "--tags", help="Tags to filter by, example: 'key=Name|value~=test,key=Vendor|value=Lightlytics', "
                       "the '~=' means 'contains' instead of 'equal' operand, tags divided by ','",
        required=False)
    parser.add_argument(
        "--accounts", help="Accounts list to iterate when creating the report", required=False)
    args = parser.parse_args()
    main(args.environment_sub_domain, args.environment_user_name, args.environment_password,
         args.ws_name, args.resource_type, args.tags, args.accounts)

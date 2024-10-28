import argparse
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


def main(environment, ll_username, ll_password, ll_f2a, ws_name, accounts=None, stage=None):
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

    resources_dict = {}

    log.info("Searching resources in each account")
    for account in all_accounts:
        account_resources = graph_client.get_resources_by_account(account)
        for res in account_resources:
            count_dict = {"account": account, "count": res['count']}
            try:
                resources_dict[res['resource_type']].append(count_dict)
            except KeyError:
                resources_dict[res['resource_type']] = [count_dict]

    csv_file = f'Stream inventory count export - {environment}.csv'

    # Extract unique accounts and resources
    accounts = set()
    resources = {}

    for resource, entries in resources_dict.items():
        for entry in entries:
            accounts.add(entry['account'])
            resources.setdefault(resource, {})[entry['account']] = entry['count']

    # Convert accounts to a sorted list to ensure consistent column order
    accounts = sorted(accounts)

    # Write to CSV
    with open(csv_file, mode='w', newline='') as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(['Resource'] + [f'="{a}"' for a in accounts])
        for resource, counts in resources.items():
            row = [resource] + [counts.get(account, 0) for account in accounts]
            writer.writerow(row)

    log.info("File generated successfully, export complete!")

    return csv_file


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
        "--accounts", help="Accounts list to iterate when creating the report", required=False)
    parser.add_argument(
        "--stage", action="store_true")
    args = parser.parse_args()
    main(args.environment_sub_domain, args.environment_user_name, args.environment_password, args.environment_f2a_token,
         args.ws_name, accounts=args.accounts, stage=args.stage)

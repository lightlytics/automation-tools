#!/usr/bin/python
import argparse
import concurrent.futures
import csv
import os
import sys
from datetime import datetime, timedelta, timezone


# Add the project root directory to the Python path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')))
try:
    from src.python.common.common import *
except ModuleNotFoundError:
    sys.path.append("../../..")
    from src.python.common.common import *


def main(environment, ll_username, ll_password, ll_f2a, ws_name, stage=None):
    # Connecting to Stream
    graph_client = get_graph_client(environment, ll_username, ll_password, ll_f2a, ws_name, stage)

    # Get "Internet facing Load Balancer (NLB)" rule ID
    rules = graph_client.get_all_rules()
    rule_id = [r['id'] for r in rules if r['name'] == "Ensure access keys unused for 90 days are deleted"][0]

    # Get rule violations
    unused_access_keys = graph_client.export_csv_rule(rule_id)
    violations = unused_access_keys['violations']
    log.info(f"Found {len(violations)} violations")

    # Enrich rule violations
    with concurrent.futures.ThreadPoolExecutor() as executor:
        [executor.submit(enrich_violations, graph_client, violation) for violation in violations]

    # Get columns names
    column_names = list(violations[0].keys())

    # Set CSV file name
    csv_file = f'{environment.upper()} enriched violations export.csv'

    log.info(f'Generating CSV file, file name: "{csv_file}"')
    with open(csv_file, mode='w', newline='') as file:
        writer = csv.DictWriter(file, fieldnames=column_names, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(violations)
    log.info("File generated successfully, export complete!")

    return csv_file


def enrich_violations(graph_client, violation):
    resource_details = graph_client.get_resource_configuration_by_id(violation['resource_id'])
    if "access_key_metadata" in resource_details:
        violation['violating_key_ids'] = \
            [k["AccessKeyId"] for k in resource_details['access_key_metadata']
             if datetime.fromisoformat(k['LastUsedDate']) < datetime.now(timezone.utc) - timedelta(days=90)]


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
        "--stage", action="store_true")
    args = parser.parse_args()
    main(args.environment_sub_domain, args.environment_user_name, args.environment_password, args.environment_f2a_token,
         args.ws_name, stage=args.stage)

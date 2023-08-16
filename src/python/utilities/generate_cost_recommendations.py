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


def main(environment, ll_username, ll_password, ws_name, stage=None):
    # Connecting to Lightlytics
    graph_client = get_graph_client(environment, ll_username, ll_password, ws_name, stage)

    log.info("Getting all cost rules")
    cost_rules = graph_client.get_cost_rules()
    log.info(f"Found {len(cost_rules)} cost rules!")

    log.info(f"Processing cost rules violations")
    recommendations = {}
    with concurrent.futures.ThreadPoolExecutor() as executor:
        futures = [executor.submit(get_recommendations, rule_id, graph_client, recommendations) for rule_id in
                   [r["id"] for r in cost_rules]]
        for future in futures:
            future.result()
    log.info(f"Finished processing cost rules violations successfully!")

    csv_file = f'{environment.upper()} cost recommendations.csv'

    fieldnames = [
        'resource_id',
        'account',
        'region',
        'name',
        'predicted_monthly_cost_savings'
    ]

    log.info(f'Generating CSV file, file name: "{csv_file}"')
    with open(csv_file, 'w', newline='') as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        for key, value in recommendations.items():
            for violation in value['violations']:
                writer.writerow({
                    'resource_id': violation['resource_id'],
                    'account': violation['account_id'],
                    'region': violation['region'],
                    'name': value['name'],
                    'predicted_monthly_cost_savings': violation['monthly_cost'] or 0
                })
    log.info("File generated successfully, export complete!")

    return csv_file


def get_recommendations(rule_id, graph_client, recommendations):
    res = graph_client.export_csv_rule(rule_id)
    if res:
        log.info(f"Found {res['violation_count']} violations in rule: {res['rule_name']}")
        recommendations[rule_id] = {"name": res["rule_name"]}
        recommendations[rule_id]["violations"] = res["violations"]


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
        "--stage", action="store_true")
    args = parser.parse_args()
    main(args.environment_sub_domain, args.environment_user_name, args.environment_password,
         args.ws_name, args.stage)

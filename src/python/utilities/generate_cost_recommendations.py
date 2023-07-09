import argparse
import os
import sys

# Add the project root directory to the Python path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')))
try:
    from src.python.common.boto_common import *
    from src.python.common.graph_common import GraphCommon
    from src.python.common.xlsx_tools import XlsxFile
except ModuleNotFoundError:
    sys.path.append("../../..")
    from src.python.common.boto_common import *
    from src.python.common.graph_common import GraphCommon
    from src.python.common.xlsx_tools import XlsxFile


def main(environment, ll_username, ll_password, ws_name):
    print(color("Trying to login into Lightlytics", "blue"))
    ll_url = f"https://{environment}.lightlytics.com"
    ll_graph_url = f"{ll_url}/graphql"
    graph_client = GraphCommon(ll_graph_url, ll_username, ll_password)
    ws_id = graph_client.get_ws_id_by_name(ws_name)
    graph_client = GraphCommon(ll_graph_url, ll_username, ll_password, customer_id=ws_id)
    print(color("Logged in successfully!", "green"))

    print(color("Getting all cost rules", "blue"))
    cost_rules = graph_client.get_cost_rules()
    print(color(f"Found {len(cost_rules)} cost rules!", "green"))

    recommendations = {}
    for rule in cost_rules:
        violations = graph_client.get_rule_violations(rule["id"])
        if len(violations) > 0:
            print(color(f"Processing {len(violations)} violations for rule: {rule['name']}", "blue"))
            recommendations[rule["id"]] = {"name": rule["name"]}
            recommendations[rule["id"]]["violations"] = []
            with concurrent.futures.ThreadPoolExecutor() as executor:
                futures = [executor.submit(process_violation, violation, graph_client, recommendations, rule)
                           for violation in violations]
                concurrent.futures.wait(futures)
            print(color(f"Finished processing violations for rule: {rule['name']}!", "green"))


def process_violation(violation, graph_client, recommendations, rule):
    try:
        violation_metadata = graph_client.get_resource_metadata(violation)
        recommendations[rule["id"]]["violations"].append({
            "resource_id": violation,
            "account": violation_metadata["account_id"],
            "region": violation_metadata["region"]
        })
    except TypeError:
        pass


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
    args = parser.parse_args()
    main(args.environment_sub_domain, args.environment_user_name, args.environment_password,
         args.ws_name)

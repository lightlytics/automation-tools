import argparse
import itertools
import os
import sys

from datetime import date
from pprint import pprint

# Add the project root directory to the Python path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')))
try:
    from src.python.common.boto_common import *
    from src.python.common.graph_common import GraphCommon
except ModuleNotFoundError:
    sys.path.append("../../..")
    from src.python.common.boto_common import *
    from src.python.common.graph_common import GraphCommon


def main(environment, ll_username, ll_password, ws_name, compliance, accounts, label):
    # Setting up variables
    if accounts:
        accounts = accounts.replace(" ", "").split(",")

    print(color("Trying to login into Lightlytics", "blue"))
    ll_url = f"https://{environment}.lightlytics.com/graphql"

    graph_client = GraphCommon(ll_url, ll_username, ll_password)
    ws_id = graph_client.get_ws_id_by_name(ws_name)
    graph_client = GraphCommon(ll_url, ll_username, ll_password, customer_id=ws_id)
    print(color("Logged in successfully!", "green"))

    print(color(f"Verifying that '{compliance}' compliance standard exist", "blue"))
    compliance_list = graph_client.get_compliance_standards()
    if compliance not in compliance_list:
        print(color(f'Compliance "{compliance}" not found', "red"))
        print(color(f"Available compliance standards: {compliance_list}", "blue"))
        raise Exception(f"Unsupported compliance standard: {compliance}")
    print(color("Compliance standard OK!", "green"))

    print(color(f"Getting all compliance rules", "blue"))
    compliance_rules = graph_client.get_rules_by_compliance(compliance)
    compliance_rules_count = len(compliance_rules)
    print(color(f"Found {compliance_rules_count} compliance rules!", "green"))

    if label:
        print(color(f"Verifying that this label exist: '{label}'", "blue"))
        all_labels = list(set(itertools.chain.from_iterable([c["labels"] for c in compliance_rules])))
        if label not in all_labels:
            err_msg = f"Can't find label: '{label}'"
            print(color(err_msg, "red"))
            print(color(f"Available labels: {all_labels}", "blue"))
            raise Exception(err_msg)
        else:
            print(color(f"Filtering rules using this label: '{label}'", "blue"))
            compliance_rules = [c for c in compliance_rules if label in c["labels"]]
            compliance_rules_count = len(compliance_rules)
            print(color(f"There are {compliance_rules_count} compliance rules matching the label '{label}'", "green"))

    report_details = {
        "name": f"{environment.upper()} - {compliance.upper()}"
                f"{f' (Label: {label})' if label else ''} Compliance Report",
        "generation_date": date.today().strftime("%d/%m/%Y"),
        "total_rules": compliance_rules_count,
        "total_rules_violated": 0,
        "total_violations": 0
    }

    print(color(f"Getting violation for each rule", "blue"))
    for rule in compliance_rules:
        rule["violations"] = graph_client.get_rule_violations(rule["id"], filter_path_violations=True)
        violations_count = len(rule["violations"])
        report_details["total_violations"] += violations_count
        if violations_count > 0:
            report_details["total_rules_violated"] += 1

    pprint(report_details)

    print(color("Getting accounts list from the workspace", "blue"))
    ws_accounts = graph_client.get_accounts()
    print(color(f"Accounts in the selected workspace: {[a['cloud_account_id'] for a in ws_accounts]}", "green"))

    # Filtering accounts according to parameter
    if accounts:
        ws_accounts = [a for a in ws_accounts if a['cloud_account_id'] in accounts]
        print(color(f"Accounts included in the report: {[a['cloud_account_id'] for a in ws_accounts]}", "blue"))


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
        "--compliance", help="The report will be generated for this compliance (Case Sensitive)", required=True)
    parser.add_argument(
        "--accounts", help="Accounts list to iterate when creating the report", required=False)
    parser.add_argument(
        "--label", help="Filter compliance rules by using a label", required=False)
    args = parser.parse_args()
    main(args.environment_sub_domain, args.environment_user_name, args.environment_password,
         args.ws_name, args.compliance, args.accounts, args.label)

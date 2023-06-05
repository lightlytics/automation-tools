import argparse
import itertools
import os
import sys

from datetime import date
from urllib.parse import quote_plus

# Add the project root directory to the Python path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')))
try:
    from src.python.common.boto_common import *
    from src.python.common.graph_common import GraphCommon
    from src.python.common.xlsx_tools import CsvFile
except ModuleNotFoundError:
    sys.path.append("../../..")
    from src.python.common.boto_common import *
    from src.python.common.graph_common import GraphCommon
    from src.python.common.xlsx_tools import CsvFile


def main(environment, ll_username, ll_password, ws_name, compliance, accounts, label):
    # Setting up variables
    if accounts:
        accounts = accounts.replace(" ", "").split(",")

    print(color("Trying to login into Lightlytics", "blue"))
    ll_url = f"https://{environment}.lightlytics.com"
    ll_graph_url = f"{ll_url}/graphql"
    graph_client = GraphCommon(ll_graph_url, ll_username, ll_password)
    ws_id = graph_client.get_ws_id_by_name(ws_name)
    graph_client = GraphCommon(ll_graph_url, ll_username, ll_password, customer_id=ws_id)
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
        "environment_name": environment.upper(),
        "environment_workspace": ws_name,
        "ws_id": ws_id,
        "ll_url": ll_url,
        "compliance_name": compliance.upper(),
        "compliance_label": label,
        "generation_date": date.today().strftime("%d/%m/%Y"),
        "total_rules": compliance_rules_count,
        "total_rules_violated": 0,
        "total_violations": 0,
        "violated_rules": []
    }

    print(color(f"Getting violations for each rule", "blue"))
    for rule in compliance_rules:
        rule["violations"] = graph_client.get_rule_violations(rule["id"], filter_path_violations=True)
        violations_count = len(rule["violations"])
        rule["metadata"] = graph_client.get_rule_metadata(rule["id"])
        report_details["total_violations"] += violations_count
        if violations_count > 0:
            print(color(f"Generating report for rule '{rule['name']}'", "blue"))
            print(color(f"Adding report for {violations_count} violations", "blue"))

            # Create a ThreadPoolExecutor
            with concurrent.futures.ThreadPoolExecutor() as executor:
                # Create a list to store the futures of each worker
                futures = []
                # Iterate over the violations
                for violation in rule["violations"]:
                    # Submit each violation to the executor and store the future object
                    future = executor.submit(process_violation, violation, graph_client, ll_url, ws_id)
                    futures.append(future)
                # Create a dictionary to store the results
                rule_details = {
                    "name": rule["name"],
                    "id": rule["id"],
                    "violated_resources": {}
                }
                # Iterate over the completed futures and process the results
                for future in concurrent.futures.as_completed(futures):
                    violation_account, violation_details = future.result()
                    try:
                        rule_details["violated_resources"][violation_account]["resource_ids"].append(violation_details)
                    except KeyError:
                        try:
                            if rule["metadata"]["resource_predicate"]:
                                resource_type = rule["metadata"]["resource_predicate"]["resource_type"]
                                rule_details["resource_type"] = resource_type
                            else:
                                resource_type = rule["metadata"]["path_source_predicate"]["resource_type"]
                                rule_details["resource_type"] = resource_type
                            rule_details["violated_resources"][violation_account] = {
                                "resource_ids": [violation_details],
                                "total_resources": graph_client.get_resources_type_count_by_account(
                                    resource_type, violation_account)
                            }
                        except IndexError:
                            resource_type = rule["metadata"]["path_destination_predicate"]["resource_type"] or \
                                            rule["metadata"]["path_intermediate_predicate"]["resource_type"]
                            rule_details["resource_type"] = resource_type
                            rule_details["violated_resources"][violation_account] = {
                                "resource_ids": [violation_details],
                                "total_resources": graph_client.get_resources_type_count_by_account(
                                    resource_type, violation_account)
                            }

            report_details["violated_rules"].append(rule_details)
            report_details["total_rules_violated"] += 1
            print(color(f"Finished generating report for rule '{rule['name']}'!", "green"))

    print(color("Getting accounts list from the workspace", "blue"))
    ws_accounts = graph_client.get_accounts()
    print(color(f"Accounts in the selected workspace: {[a['cloud_account_id'] for a in ws_accounts]}", "green"))

    # Filtering accounts according to parameter
    if accounts:
        ws_accounts = [a for a in ws_accounts if a['cloud_account_id'] in accounts]
        print(color(f"Accounts included in the report: {[a['cloud_account_id'] for a in ws_accounts]}", "blue"))
    report_details["total_accounts"] = len(ws_accounts)

    print(color("Enriching rules with accounts information", "blue"))
    enrich_accounts(report_details, ws_accounts, graph_client)
    print(color("Enriching finished successfully", "green"))

    print(color("Generating XLSX file", "blue"))
    xlsx_file_name = f"{environment.upper()} {compliance}{f' {label}' if label else ''} Compliance report.xlsx"
    xlsx = CsvFile(xlsx_file_name, report_details)
    for i, violated_rule in enumerate(report_details["violated_rules"]):
        rule_number = i + 1
        xlsx.create_new_rule_sheet(violated_rule, rule_number, ws_accounts)
    xlsx.save_csv()


def process_violation(violation, graph_client, ll_url, ws_id):
    encoded_query_url = quote_plus("i[resourceId]") + "=" + quote_plus(violation['id'])
    violation_account = graph_client.get_resource_cloud_account_id(violation["id"])
    violation_details = {
        "id": violation["id"],
        "url": f"{ll_url}/w/{ws_id}/discovery?{encoded_query_url}",
    }
    return violation_account, violation_details


def enrich_accounts(report_details, ws_accounts, graph_client):
    with concurrent.futures.ThreadPoolExecutor() as executor:
        futures = []
        for r in report_details["violated_rules"]:
            all_accounts_to_report = sorted([a["cloud_account_id"] for a in ws_accounts])
            all_accounts_in_rule = sorted(list(r.get("violated_resources").keys()))
            if all_accounts_to_report != all_accounts_in_rule:
                missing_accounts = [a for a in all_accounts_to_report if a not in all_accounts_in_rule]
                for missing_account in missing_accounts:
                    future = executor.submit(update_violated_resources, r, missing_account, graph_client)
                    futures.append(future)
        concurrent.futures.wait(futures)


def update_violated_resources(r, missing_account, graph_client):
    r.get("violated_resources")[missing_account] = {
        "resource_ids": [],
        "total_resources": graph_client.get_resources_type_count_by_account(
            r.get("resource_type"), missing_account)
    }


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

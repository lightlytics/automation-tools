import argparse
import concurrent.futures
import itertools
import os
import sys

from datetime import date
from urllib.parse import quote_plus

# Add the project root directory to the Python path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')))
try:
    from src.python.common.common import *
    from src.python.common.xlsx_tools import XlsxFile
except ModuleNotFoundError:
    sys.path.append("../../..")
    from src.python.common.common import *
    from src.python.common.xlsx_tools import XlsxFile


def main(environment, ll_username, ll_password, ll_f2a, ws_name, compliance, accounts=None, label=None, stage=None):
    # Setting up variables
    if accounts:
        accounts = accounts.replace(" ", "").split(",")

    # Connecting to Stream
    graph_client = get_graph_client(environment, ll_username, ll_password, ll_f2a, ws_name, stage)

    log.info(f"Verifying that '{compliance}' compliance standard exist")
    compliance_list = graph_client.get_compliance_standards()
    if compliance not in compliance_list:
        msg = f'Compliance "{compliance}" not found, available compliance standards: {compliance_list}'
        log.error(msg)
        raise Exception(msg)
    log.info("Compliance standard OK!")

    log.info(f"Getting all compliance rules")
    compliance_rules = graph_client.get_rules_by_compliance(compliance)
    compliance_rules_count = len(compliance_rules)
    log.info(f"Found {compliance_rules_count} compliance rules!")

    if label:
        log.info(f"Verifying that this label exist: '{label}'")
        all_labels = list(set(itertools.chain.from_iterable([c["labels"] for c in compliance_rules])))
        if label not in all_labels:
            err_msg = f"Can't find label: '{label}', available labels: {all_labels}"
            log.error(err_msg)
            raise Exception(err_msg)
        else:
            log.info(f"Filtering rules using this label: '{label}'")
            compliance_rules = [c for c in compliance_rules if label in c["labels"]]
            compliance_rules_count = len(compliance_rules)
            log.info(f"There are {compliance_rules_count} compliance rules matching the label '{label}'")

    report_details = {
        "environment_name": environment.upper(),
        "environment_workspace": ws_name,
        "ws_id": graph_client.customer_id,
        "ll_url": graph_client.url,
        "compliance_name": compliance.upper(),
        "compliance_label": label,
        "generation_date": date.today().strftime("%d/%m/%Y"),
        "all_rules": compliance_rules,
        "total_rules": compliance_rules_count,
        "total_rules_violated": 0,
        "total_violations": 0,
        "violated_rules": []
    }

    log.info(f"Getting violations for each rule")
    with concurrent.futures.ThreadPoolExecutor() as executor:
        futures = [executor.submit(process_rule, rule, graph_client, report_details) for rule in compliance_rules]
        # Wait for all threads to complete
        concurrent.futures.wait(futures)

    log.info("Getting accounts list from the workspace")
    ws_accounts = graph_client.get_accounts()
    log.info(f"Accounts in the selected workspace: {[a['cloud_account_id'] for a in ws_accounts]}")

    # Filtering accounts according to parameter
    if accounts:
        ws_accounts = [a for a in ws_accounts if a['cloud_account_id'] in accounts]
        log.info(f"Accounts included in the report: {[a['cloud_account_id'] for a in ws_accounts]}")
    report_details["total_accounts"] = len(ws_accounts)

    log.info("Enriching rules with accounts information")
    enrich_accounts(report_details, ws_accounts, graph_client)
    log.info("Enriching finished successfully")

    log.info("Generating XLSX file")
    xlsx_file_name = f"{environment.upper()} {compliance}{f' {label}' if label else ''} Compliance report.xlsx"
    xlsx = XlsxFile(xlsx_file_name)
    xlsx.create_compliance_report_template(report_details)
    for i, violated_rule in enumerate(report_details["violated_rules"]):
        rule_number = i + 1
        xlsx.create_new_rule_sheet(report_details, violated_rule, rule_number, ws_accounts)
    xlsx.save_xlsx()

    return xlsx_file_name


def process_rule(rule, graph_client, report_details):
    rule_data = graph_client.export_csv_rule(rule["id"])
    violations_count = len(rule_data['violations'])
    rule["metadata"] = graph_client.get_rule_metadata(rule["id"])
    report_details["total_violations"] += violations_count
    if violations_count > 0:
        add_violation_to_report(rule, rule_data, violations_count, graph_client, report_details)


def add_violation_to_report(rule, rule_data, violations_count, graph_client, report_details):
    log.info(f"{rule['name']} | Generating report")
    log.info(f"{rule['name']} | Adding report for {violations_count} violations")
    rule_details = {
        "name": rule["name"],
        "id": rule["id"],
        "violated_resources": {}
    }
    for violation in rule_data['violations']:
        encoded_query_url = quote_plus("i[resourceId]") + "=" + quote_plus(violation["resource_id"])
        violation_account = violation["account_id"].split('"')[1]
        violation_details = {
            "id": violation["resource_id"],
            "url": f"{graph_client.url.replace('/graphql', '')}/w/"
                   f"{graph_client.customer_id}/discovery?{encoded_query_url}",
        }
        add_violation_details(rule, rule_details, violation_account, violation_details, graph_client)
    report_details["violated_rules"].append(rule_details)
    report_details["total_rules_violated"] += 1
    log.info(f"{rule['name']} | Finished generating report!")


def add_violation_details(rule, rule_details, violation_account, violation_details, graph_client):
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
    try:
        r.get("violated_resources")[missing_account] = {
            "resource_ids": [],
            "total_resources": graph_client.get_resources_type_count_by_account(
                r.get("resource_type"), missing_account)
        }
    except IndexError:
        r.get("violated_resources")[missing_account] = {"resource_ids": [], "total_resources": 0}


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
        "--compliance", help="The report will be generated for this compliance (Case Sensitive)", required=True)
    parser.add_argument(
        "--accounts", help="Accounts list to iterate when creating the report", required=False)
    parser.add_argument(
        "--label", help="Filter compliance rules by using a label", required=False)
    parser.add_argument(
        "--stage", action="store_true")
    args = parser.parse_args()
    main(args.environment_sub_domain, args.environment_user_name, args.environment_password, args.environment_f2a_token,
         args.ws_name, args.compliance, accounts=args.accounts, label=args.label, stage=args.stage)

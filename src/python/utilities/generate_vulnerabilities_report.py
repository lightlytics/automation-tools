import argparse
import concurrent.futures
import csv
import logging
import os
import sys

SEVERITIES = {
    1: "Low",
    2: "Medium",
    3: "High",
    4: "Critical"
}

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

    log.info("Getting all CVEs")
    cve_list = graph_client.get_cves()
    log.info(f"Found {len(cve_list)} CVEs")

    cve_data = [
        [
            "CVE ID", "Severity", "Score", "Packages Names", "Publicly Exposed", "Fix Available", "Has Exploit",
            "Resource Name", "Resource Type", "Account ID"
        ]
    ]
    completed_threads = 0
    filename = f"{environment}_vulnerabilities.csv"

    with open(filename, mode='w', newline='') as file:
        writer = csv.writer(file)
        writer.writerows(cve_data)
        with concurrent.futures.ThreadPoolExecutor() as executor:
            # Submit each cve for processing and store the Future objects
            futures = [executor.submit(process_cve, graph_client, cve) for cve in cve_list]
            # Retrieve results as they become available
            for future in concurrent.futures.as_completed(futures):
                cve_data = future.result()
                if cve_data:
                    writer.writerows(cve_data)
                completed_threads += 1
                if completed_threads % 50 == 0:
                    log.info(f"{completed_threads} threads completed")


def process_cve(graph_client, cve):
    try:
        cve_resources = graph_client.get_affected_resources(cve['cve_id'])
        return [process_resource(cve, r) for r in cve_resources]
    except Exception as e:
        log.error(f"Something went wrong when getting resources from {cve['cve_id']} | Error: {e}")
        return []


def process_resource(cve, resource):
    return [
        cve['cve_id'],
        SEVERITIES[cve['severity']],
        cve['cvss_score'],
        cve['packages'],
        resource['public_exposed'],
        cve['fix_available'],
        cve['exploit_available'],
        resource['resource_id'],
        resource['resource_type'],
        resource['account_id']
    ]


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

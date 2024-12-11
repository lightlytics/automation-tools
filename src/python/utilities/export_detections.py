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


def main(environment, ll_username, ll_password, ll_f2a, ws_name, stage=None):
    # Connecting to Stream
    graph_client = get_graph_client(environment, ll_username, ll_password, ll_f2a, ws_name, stage)

    # Get all detections
    log.info("Get all detections")
    all_detections = graph_client.get_detections()
    log.info(f"Found {len(all_detections)} detections")

    # Enrich detections
    with concurrent.futures.ThreadPoolExecutor() as executor:
        [executor.submit(enrich_detections, graph_client, detection) for detection in all_detections]

    # Get columns names
    column_names = list(all_detections[0].keys())

    # Set CSV file name
    csv_file = f'{environment.upper()} enriched detections export.csv'

    log.info(f'Generating CSV file, file name: "{csv_file}"')
    with open(csv_file, mode='w', newline='') as file:
        writer = csv.DictWriter(file, fieldnames=column_names, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(all_detections)
    log.info("File generated successfully, export complete!")

    return csv_file


def enrich_detections(graph_client, detection):
    detection_enrichment = graph_client.get_detection_enrichment(detection['_id'])[0]
    detection["enrichment"] = {k: v for k, v in detection_enrichment.items() if k not in detection}


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

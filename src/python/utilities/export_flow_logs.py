#!/usr/bin/python
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


def main(environment, ll_username, ll_password, ll_f2a, ws_name, action=None, dst_resource_id=None, start_time=None,
         end_time=None, src_public=None, protocols=None, stage=None):
    # Connecting to Stream
    graph_client = get_graph_client(environment, ll_username, ll_password, ll_f2a, ws_name, stage)

    # Setting up variables
    if start_time:
        start_time += "T00:00:00.000Z"
    if end_time:
        end_time += "T23:59:59.999Z"

    # Get flow logs
    flow_logs = graph_client.get_flow_logs(
        action=action, dst_resource_id=dst_resource_id, start_time=start_time,
        end_time=end_time, src_public=src_public, protocols=protocols
    )

    # Check if there are results
    if len(flow_logs) == 0:
        raise Exception("Couldn't find flow logs for the requested filters")

    # Get columns names
    column_names = list(flow_logs[0].keys())[0:-1]

    # Set CSV file name
    csv_file = f'{environment.upper()} flow logs export.csv'

    log.info(f'Generating CSV file, file name: "{csv_file}"')
    with open(csv_file, mode='w', newline='') as file:
        writer = csv.DictWriter(file, fieldnames=column_names, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(flow_logs)
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
        "--stage", action="store_true")
    parser.add_argument(
        "--action", help="Select flow logs action, could be 'ACCEPT' or 'REJECT', for both leave blank")
    parser.add_argument(
        "--dst_resource_id", help="Choose the destination resource ID to filter by")
    parser.add_argument(
        "--start_time", help="Choose the starting time, format: 'YYYY-MM-DD'")
    parser.add_argument(
        "--end_time", help="Choose the ending time, format: 'YYYY-MM-DD'")
    parser.add_argument(
        "--src_public", action="store_true", help="Pass this arg to get only Internet access")
    parser.add_argument(
        "--protocols", help="Filter by transport protocols, could be 'TCP' or 'UDP', for both leave blank")
    args = parser.parse_args()
    main(args.environment_sub_domain, args.environment_user_name, args.environment_password, args.environment_f2a_token,
         args.ws_name, stage=args.stage, action=args.action, dst_resource_id=args.dst_resource_id,
         start_time=args.start_time, end_time=args.end_time, src_public=args.src_public, protocols=args.protocols)

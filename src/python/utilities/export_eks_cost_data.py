#!/usr/bin/python
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


def main(environment, ll_username, ll_password, ll_f2a, ws_name, start_timestamp, end_timestamp, stage=None):
    # Connecting to Stream
    graph_client = get_graph_client(environment, ll_username, ll_password, ll_f2a, ws_name, stage)

    eks_clusters = graph_client.get_resources_by_type("eks")
    eks_cost_dict = dict()

    with concurrent.futures.ThreadPoolExecutor() as executor:
        [executor.submit(get_clusters_cost, graph_client, eks_cost_dict, eks_cluster, start_timestamp, end_timestamp)
         for eks_cluster in eks_clusters]

    # Define the headers based on the keys of the inner dictionary
    headers = ['cluster name'] + list(next(iter(eks_cost_dict.values())).keys())

    # Set CSV file name
    csv_file = f'{environment.upper()} kubernetes cost export.csv'

    # Write to CSV
    with open(csv_file, 'w', newline='') as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=headers)
        writer.writeheader()
        for cluster, data in eks_cost_dict.items():
            row = {'cluster name': cluster}
            row.update(data)
            writer.writerow(row)


def get_clusters_cost(graph_client, eks_cost_dict, eks_cluster, start_timestamp, end_timestamp):
    cost_info = graph_client.get_kubernetes_cost(
        eks_cluster['id'], f"{start_timestamp}T00:00:00.000Z", f"{end_timestamp}T09:22:03.370Z")
    cost_info_cluster = graph_client.get_kubernetes_cluster_cost(
        eks_cluster['id'], f"{start_timestamp}T00:00:00.000Z", f"{end_timestamp}T09:22:03.370Z")
    if cost_info['total_count'] == 0:
        return
    else:
        cost_res = cost_info['results'][0]
        del cost_res['__typename']
        del cost_res['timestamp']
        del cost_info_cluster['__typename']
        eks_cost_dict[eks_cluster['id']] = cost_info_cluster | cost_res


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
        "--start_timestamp", help="Timestamp to start from, format: YYYY-MM-DD", required=True)
    parser.add_argument(
        "--end_timestamp", help="Timestamp to start from, format: YYYY-MM-DD", required=True)
    args = parser.parse_args()
    main(args.environment_sub_domain, args.environment_user_name, args.environment_password, args.environment_f2a_token,
         args.ws_name, args.start_timestamp, args.end_timestamp, stage=args.stage)

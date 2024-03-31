#!/usr/bin/python
import argparse
import concurrent.futures
import csv
import os
import sys
from termcolor import colored as color


# Add the project root directory to the Python path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')))
try:
    from src.python.common.common import *
except ModuleNotFoundError:
    sys.path.append("../../..")
    from src.python.common.common import *

AMIS = dict()


def main(environment, ll_username, ll_password, ll_f2a, ws_name, stage=None):
    print(color("Trying to login into Stream Security", "blue"))
    graph_client = get_graph_client(environment, ll_username, ll_password, ll_f2a, ws_name, stage)
    print(color("Logged in successfully!", "green"))

    print(color("Getting all EC2 instances", "blue"))
    ec2_instances = [{"id": i["id"]} for i in graph_client.get_resources_by_type("instance")]
    print(color(f"Found {len(ec2_instances)} EC2 instances", "green"))

    print(color("Enriching each EC2 with AMI information", "blue"))
    with concurrent.futures.ThreadPoolExecutor() as executor:
        futures = [executor.submit(enrich_instances_info, graph_client, instance) for instance in ec2_instances]
        print(color(f"Number of threads created: {len(futures)}", "blue"))
        completed_count = 0
        for _ in concurrent.futures.as_completed(futures):
            completed_count += 1
            if completed_count % 50 == 0:
                completed_percentage = int(completed_count / len(futures) * 100)
                print(f"{completed_count} threads completed out of {len(futures)} ({completed_percentage}%)")
        print(color("All threads completed"), "green")
    print(color("Enrichment finished successfully!", "green"))

    # Get columns names
    column_names = list(ec2_instances[0].keys())

    # Set CSV file name
    csv_file = f'{environment.upper()} EC2 OS info.csv'

    print(color(f'Generating CSV file, file name: "{csv_file}"'), "blue")
    with open(csv_file, mode='w', newline='') as file:
        writer = csv.DictWriter(file, fieldnames=column_names, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(ec2_instances)
    print(color("File generated successfully, export complete!", "green"))

    return csv_file


def enrich_instances_info(graph_client, instance):
    resource_details = graph_client.get_resource_configuration_by_id(instance['id'])
    instance['ami_id'] = resource_details.get("ImageId")
    if instance['ami_id'] in AMIS:
        ami_metadata = AMIS[instance['ami_id']]
    else:
        ami_metadata = graph_client.get_resource_configuration_by_id(instance['ami_id'])
        AMIS[instance['ami_id']] = ami_metadata
    instance['ami_platform'] = ami_metadata.get("PlatformDetails", "N/A")
    instance['ami_name'] = ami_metadata.get("Name", "N/A")
    instance['ami_description'] = ami_metadata.get("Description", "N/A")


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

import argparse
import concurrent.futures
import os
import sys

# TODO REMOVE
from pprint import pprint


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

    log.info("Getting all ENIs")
    enis = graph_client.get_resources_by_type("network_interface")
    log.info(f"Found {len(enis)} ENIs")

    # Create IP Addresses list
    ip_addresses = []

    # Add all ENIs IP addresses
    for ip_list in [ip['addresses'] for ip in enis]:
        ip_addresses.extend(ip_list)

    log.info("Getting all Elastic IPs")
    ip_addresses.extend([eip['id'] for eip in graph_client.get_resources_by_type("elastic_ip")])

    log.info("Filtering Internal IPs")
    external_ip_addresses = [ip for ip in list(set(ip_addresses)) if is_external_ip(ip)]
    log.info(f"Found {len(external_ip_addresses)} IPs to process")

    log.info("Processing single IPs")
    ext_dict = {}
    with concurrent.futures.ThreadPoolExecutor() as executor:
        futures = [executor.submit(process_eni, ext_dict, ext_ip, graph_client) for ext_ip in external_ip_addresses]
        log.info(f"Number of threads created: {len(futures)}")
        completed_count = 0
        for _ in concurrent.futures.as_completed(futures):
            completed_count += 1
            if completed_count % 50 == 0:
                completed_percentage = int(completed_count / len(futures) * 100)
                log.info(f"{completed_count} threads completed out of {len(futures)} ({completed_percentage}%)")
        log.info("All threads completed")

    pprint(ext_dict)


def process_eni(ext_dict, ext_ip, graph_client):
    ext_dict[ext_ip] = [ip for ip in graph_client.general_resource_search(ext_ip, get_only_ids=True)
                        if ip != ext_ip]
    if len(ext_dict[ext_ip]) == 0:
        ext_dict[ext_ip] = 'Elastic IP'


def is_external_ip(ip):
    octets = ip.split('.')
    first_octet = int(octets[0])
    second_octet = int(octets[1])

    if first_octet == 10:
        return False
    elif first_octet == 172 and 16 <= second_octet <= 31:
        return False
    elif first_octet == 192 and second_octet == 168:
        return False
    else:
        return True


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
         args.ws_name, args.stage)

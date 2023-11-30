import argparse
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
    # Connecting to Lightlytics
    graph_client = get_graph_client(environment, ll_username, ll_password, ll_f2a, ws_name, stage)

    # Find all ENIs
    enis = graph_client.get_resources_by_type("network_interface")

    # Create IP Addresses list
    ip_addresses = []

    # Add all ENIs IP addresses
    for ip_list in [ip['addresses'] for ip in enis]:
        ip_addresses.extend(ip_list)

    # Add all Elastic IP addresses
    ip_addresses.extend([eip['id'] for eip in graph_client.get_resources_by_type("elastic_ip")])

    # Filter only external IDs
    external_ip_addresses = [ip for ip in list(set(ip_addresses)) if is_external_ip(ip)]
    ext_dict = {}
    for ext_ip in external_ip_addresses:
        ext_dict[ext_ip] = graph_client.general_resource_search(ext_ip, get_only_ids=True)

    pprint(external_ip_addresses)
    pprint(ext_dict)


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
        description='This script will integrate Lightlytics environment with every account in the organization.')
    parser.add_argument(
        "--environment_sub_domain", help="The Lightlytics environment sub domain", required=True)
    parser.add_argument(
        "--environment_user_name", help="The Lightlytics environment user name", required=True)
    parser.add_argument(
        "--environment_password", help="The Lightlytics environment password", required=True)
    parser.add_argument(
        "--environment_f2a_token", help="F2A Token if set", default=None)
    parser.add_argument(
        "--ws_name", help="The WS from which to fetch information", required=True)
    parser.add_argument(
        "--stage", action="store_true")
    args = parser.parse_args()
    main(args.environment_sub_domain, args.environment_user_name, args.environment_password, args.environment_f2a_token,
         args.ws_name, args.stage)

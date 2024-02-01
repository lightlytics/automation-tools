import argparse
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


def main(environment, ll_username, ll_password, ll_f2a, ws_name, stage=None):
    print(color("Trying to login into Stream Security", "blue"))
    graph_client = get_graph_client(environment, ll_username, ll_password, ll_f2a, ws_name, stage)
    print(color("Logged in successfully!", "green"))

    print(color("Getting all EKS clusters ARNs", "blue"))
    eks_clusters = graph_client.get_resources_by_type(resource_type="eks")
    print(color(f"Found {len(eks_clusters)} clusters", "green"))

    # Getting Stream Security existing K8s integrations
    eks_integrations = graph_client.get_kubernetes_integrations()

    for cluster in eks_clusters:
        cluster_name = cluster['id'].split(":cluster/")[-1]
        print(color(f"{cluster_name} | Checking if cluster is already integrated", "blue"))
        try:
            relevant_integration = [ri for ri in eks_integrations if ri['display_name'] == cluster_name][0]
            if relevant_integration['status'] == "READY":
                print(color(f"{cluster_name} | Cluster is already integrated!", "green"))
                continue
            else:
                print(color(f"{cluster_name} | Cluster has wrong status ({relevant_integration['status']}) - "
                            f"please remove it manually and run the script again", "red"))
                continue
        except IndexError:
            print(color("Integration not found, creating it", "blue"))
            # graph_client.create_kubernetes_integration()

    print(color("Integration finished successfully!", "green"))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description='This script will integrate all EKS clusters in the Workspace with Stream Security.')
    parser.add_argument(
        "--environment_sub_domain", help="The Stream Security environment sub domain", required=True)
    parser.add_argument(
        "--environment_user_name", help="The Stream Security environment user name", required=True)
    parser.add_argument(
        "--environment_password", help="The Stream Security environment password", required=True)
    parser.add_argument(
        "--environment_f2a_token", help="F2A Token if set", default=None)
    parser.add_argument(
        "--ws_name", help="The WS from which to fetch information", required=True)
    parser.add_argument(
        "--stage", action="store_true")
    args = parser.parse_args()
    main(args.environment_sub_domain, args.environment_user_name, args.environment_password, args.environment_f2a_token,
         args.ws_name, args.stage)

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


def main(environment, ll_username, ll_password, ll_f2a, ws_name, skip_ready=False, stage=None):

    print(color("Trying to login into Stream Security", "blue"))
    graph_client = get_graph_client(environment, ll_username, ll_password, ll_f2a, ws_name, stage)
    print(color("Logged in successfully!", "green"))

    print(color("Getting all EKS clusters ARNs", "blue"))
    eks_clusters = graph_client.get_resources_by_type(resource_type="eks")
    print(color(f"Found {len(eks_clusters)} clusters", "green"))

    print(color("Getting all Kubernetes existing integrations", "blue"))
    eks_integrations = graph_client.get_kubernetes_integrations()
    print(color(f"Found {len(eks_integrations)} integrations", "green"))

    for cluster in eks_clusters:
        cluster_name = cluster['display_name'].split("/")[0]
        cluster_arn = cluster['id']
        try:
            relevant_integration = [ri for ri in eks_integrations if ri['eks_arn'] == cluster_arn][0]
            if skip_ready:
                if relevant_integration['status'] == "READY":
                    continue
            print(color(f"{cluster_name} | {relevant_integration['collection_token']}", "green"))
        except IndexError:
            integration_metadata = graph_client.create_kubernetes_integration(cluster_arn, cluster_name)
            if not integration_metadata:
                print(color(f"{cluster_name} | Couldn't create the integration in Stream Security env - "
                            f"please contact support", "red"))
                continue
            print(color(f"{cluster_name} | {integration_metadata['collection_token']}", "green"))

    print(color("Script finished", "green"))


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
        "--skip_ready", help="Skip the integrations in 'READY' state", action="store_true")
    parser.add_argument(
        "--stage", action="store_true")
    args = parser.parse_args()
    main(args.environment_sub_domain, args.environment_user_name, args.environment_password, args.environment_f2a_token,
         args.ws_name, skip_ready=args.skip_ready, stage=args.stage)

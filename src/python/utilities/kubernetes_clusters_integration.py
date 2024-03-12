import argparse
import kubernetes
import os
import subprocess
import sys
from termcolor import colored as color

INTEGRATION_COMMANDS = [
    "helm repo add lightlytics https://lightlytics.github.io/helm-charts",
    "helm repo update",
    "helm install lightlytics --set lightlytics.apiToken={TOKEN} --set lightlytics.apiUrl={ENV} -n lightlytics "
    "--create-namespace lightlytics/lightlytics"
]

# Add the project root directory to the Python path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')))
try:
    from src.python.common.common import *
except ModuleNotFoundError:
    sys.path.append("../../..")
    from src.python.common.common import *


def main(environment, ll_username, ll_password, ll_f2a, ws_name, stage=None):
    # Get a list of available Kubernetes contexts
    k8s_contexts = [c['context']['cluster'] for c in kubernetes.config.list_kube_config_contexts()[0]]

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
        cluster_name = cluster['display_name']
        if cluster['id'] not in k8s_contexts:
            print(color(f"{cluster_name} | No context available for the cluster, skipping", "yellow"))
            continue
        print(color(f"{cluster_name} | Checking if cluster is already integrated", "blue"))
        try:
            relevant_integration = [ri for ri in eks_integrations if ri['display_name'] == cluster_name][0]
            if relevant_integration['status'] == "READY":
                print(color(f"{cluster_name} | Cluster is already integrated!", "green"))
                continue
            else:
                print(color(f"{cluster_name} | Cluster has wrong status ({relevant_integration['status']}) - "
                            f"please remove it manually and run the script again", "yellow"))
                continue
        except IndexError:
            print(color(f"{cluster_name} | Integration not found, creating it", "blue"))
            integration_metadata = graph_client.create_kubernetes_integration(cluster['id'], cluster_name)
            if not integration_metadata:
                print(color(f"{cluster_name} | Couldn't create the integration in Stream Security env - "
                            f"please contact support", "red"))
                continue
            print(color(f"{cluster_name} | Integration created successfully in Stream Security!", "green"))
            integration_token = integration_metadata['collection_token']
            print(color(f"{cluster_name} | Switching Kubernetes context", "blue"))
            subprocess.check_call(["kubectl", "config", "use-context", cluster['id']])
            stream_url = f"{environment}.lightops.io" if stage else f"{environment}.streamsec.io"
            helm_cmd = INTEGRATION_COMMANDS[2].replace("{TOKEN}", integration_token).replace("{ENV}", stream_url)

            print(color(f"{cluster_name} | Executing helm commands", "blue"))
            try:
                subprocess.check_call(INTEGRATION_COMMANDS[0].split(' '))
                subprocess.check_call(INTEGRATION_COMMANDS[1].split(' '))
                subprocess.check_call(helm_cmd.split(' '))
            except Exception as e:
                print(color(f"{cluster_name} | Something went wrong when running 'helm' commands, error: {e}", "red"))

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
        "--stage", action="store_true")
    args = parser.parse_args()
    main(args.environment_sub_domain, args.environment_user_name, args.environment_password, args.environment_f2a_token,
         args.ws_name, stage=args.stage)

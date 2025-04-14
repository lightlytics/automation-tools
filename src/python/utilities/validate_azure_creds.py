import sys
import argparse
from azure.mgmt.resource import SubscriptionClient
from azure.identity import ClientSecretCredential
import json

def main():
    parser = argparse.ArgumentParser(description='Get Azure subscription details')
    parser.add_argument('--tenant-id', required=True, help='Azure tenant ID')
    parser.add_argument('--client-id', required=True, help='Azure client ID')
    parser.add_argument('--client-secret', required=True, help='Azure client secret')
    parser.add_argument('--subscription-id', required=True, help='Azure subscription ID')
    
    args = parser.parse_args()
    
    credential = ClientSecretCredential(
        args.tenant_id,
        args.client_id,
        args.client_secret)
    
    subscription_client = SubscriptionClient(credential)
    
    try:
        response = subscription_client.subscriptions.get(args.subscription_id)
        print("Subscription details:")
        print(f"ID: {response.subscription_id}")
        print(f"Display name: {response.display_name}")
        print(f"State: {response.state}")
        print(f"Tenant ID: {response.tenant_id}")
    except Exception as e:
        print(f"Error: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main()
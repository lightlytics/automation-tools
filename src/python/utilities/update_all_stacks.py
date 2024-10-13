import argparse
import botocore
import boto3
import concurrent.futures
import os
import termcolor
from botocore.exceptions import ClientError


def main(aws_profile_name, control_role="OrganizationAccountAccessRole",
         region=None, avoid_waiting=False, custom_tags=None):
    # Prepare tags if provided
    if custom_tags:
        custom_tags = [{'Key': k.split("|")[0], 'Value': k.split("|")[1]} for k in custom_tags.split(",")]
    # Set the AWS_PROFILE environment variable
    os.environ['AWS_PROFILE'] = aws_profile_name
    # Set up the Organizations client
    org_client = boto3.client('organizations')
    # Set up the STS client
    sts_client = boto3.client('sts')
    try:
        # Set up org account variable
        org_account_id = sts_client.get_caller_identity().get('Account')
    except Exception as e:
        org_account_id = None
        print(f"Could not get org account ID: {e}")
    # Set up an empty list to store the sub_account IDs
    sub_accounts = []
    # Set up a paginator for the list_accounts operation
    paginator = org_client.get_paginator('list_accounts')

    # Iterate over the pages of results
    print(termcolor.colored(f"Getting all accounts", "blue"))
    for page in paginator.paginate():
        # Iterate over the accounts in the page
        for account in page['Accounts']:
            # If the account is a sub_account and is not the one to be ignored, add its ID to the list
            if (account['Id'] != org_client.describe_organization()['Organization']['Id']
                    and account['Id']
                    and account['Status'] == "ACTIVE"):
                sub_accounts.append(account['Id'])
    print(termcolor.colored(f"Found {len(sub_accounts)} accounts", "green"))

    # Now you can use the sub_accounts list to iterate over the sub_accounts and print a success message if the
    # assume_role call and the creation of the Boto3 session were successful
    for sub_account in sub_accounts:
        try:
            if sub_account == org_account_id:
                sub_account_session = boto3.Session()
            else:
                assumed_role = sts_client.assume_role(
                    RoleArn=f'arn:aws:iam::{sub_account}:role/{control_role}',
                    RoleSessionName='MySessionName'
                )
                sub_account_session = boto3.Session(
                    aws_access_key_id=assumed_role['Credentials']['AccessKeyId'],
                    aws_secret_access_key=assumed_role['Credentials']['SecretAccessKey'],
                    aws_session_token=assumed_role['Credentials']['SessionToken']
                )
            if region:
                regions = [region]
            else:
                # Get the list of all regions
                regions = [region['RegionName'] for region in
                           sub_account_session.client('ec2').describe_regions()['Regions']]
            # set CloudFormation stack name prefix
            prefix = "-lightlytics-"
            prefix_2 = "LightlyticsStack-"
            prefix_3 = "-streamsec-"

            with concurrent.futures.ThreadPoolExecutor() as executor:
                [executor.submit(
                    update_stack, sub_account_session, region, prefix, prefix_2, prefix_3,
                    sub_account, avoid_waiting, custom_tags) for region in regions]

        except botocore.exceptions.ClientError as e:
            # Print an error message
            print(f"Error for sub_account {sub_account}: {e}")


def update_stack(sub_account_session, region, prefix, prefix_2, prefix_3, sub_account, avoid_waiting, custom_tags):
    stacks = []
    cfn_client = ""
    try:
        # Set up a new CloudFormation client for the current region
        cfn_client = sub_account_session.client('cloudformation', region_name=region)
        # Get the list of stacks in the region
        stacks = cfn_client.list_stacks()['StackSummaries']
    except Exception as e:
        print(termcolor.colored(f"Failed to list stacks in {region}: {e}", "red"))

    # Rolling back "UPDATE_ROLLBACK_FAILED" stacks
    rollback_stacks = [stack for stack in stacks if
                       ((prefix in stack['StackName'] or
                         prefix_2 in stack['StackName'] or
                         prefix_3 in stack['StackName']) and
                        stack['StackStatus'] == 'UPDATE_ROLLBACK_FAILED') and
                       'ParentId' not in stack]
    for rb_stack in rollback_stacks:
        print(termcolor.colored(f"Rolling back the stack: '{rb_stack}'", "blue"))
        cfn_client.continue_update_rollback(StackName=rb_stack)
        if not avoid_waiting:
            cfn_client.get_waiter('stack_rollback_complete').wait(StackName=rb_stack)

    # Filter the list of stacks to only include a specific prefix
    # and status is complete create or update complete
    stacks = [stack for stack in stacks if
              ((prefix in stack['StackName'] or
                prefix_2 in stack['StackName'] or
                prefix_3 in stack['StackName']) and
               (stack['StackStatus'] == 'CREATE_COMPLETE' or
                stack['StackStatus'] == 'UPDATE_COMPLETE' or
                stack['StackStatus'] == 'UPDATE_ROLLBACK_COMPLETE')) and
              'ParentId' not in stack]

    if len(stacks) == 0:
        print(termcolor.colored(f"Account: {sub_account} | The region '{region}' has no Lightlytics stacks", "blue"))
        return False
    else:
        print(termcolor.colored(
            f"Account: {sub_account} | Found Lightlytics Stacks in region '{region}': "
            f"{[stack['StackName'] for stack in stacks]}", "blue"))

    # Create a ThreadPoolExecutor to run the update_single_stack function concurrently
    with concurrent.futures.ThreadPoolExecutor() as executor:
        futures = [executor.submit(update_single_stack, cfn_client, stack,
                                   region, avoid_waiting, custom_tags) for stack in stacks]

    # Wait for all threads to complete
    concurrent.futures.wait(futures)


def update_single_stack(cfn_client, stack, region, avoid_waiting, custom_tags):
    stack_name = stack['StackName']
    try:
        print(f"Updating stack: {stack_name}")
        cfn_client.update_stack(StackName=stack_name, UsePreviousTemplate=True, Tags=custom_tags)
        if not avoid_waiting:
            # Wait for the update to complete
            cfn_client.get_waiter('stack_update_complete').wait(StackName=stack_name)
        # Print the name of the stack that was successfully updated
        print(termcolor.colored(f"Successfully updated stack {stack_name} in {region}", "green"))
    except ClientError as e:
        # Print an error message if the stack no longer exists
        print(termcolor.colored(f"Failed to update stack {stack_name} in {region}: {e}", "red"))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="This script will integrate StreamSecurity environment with every account in the organization.")
    parser.add_argument(
        "--aws_profile_name", help="The AWS profile with admin permissions in organization account", default="default")
    parser.add_argument(
        "--control_role", help="Specify a role for control", default="OrganizationAccountAccessRole")
    parser.add_argument(
        "--region", help="Select only a specific region to update")
    parser.add_argument(
        "--avoid_waiting", help="Don't wait for the stacks to update", action="store_true")
    parser.add_argument(
        "--custom_tags", help="Add custom tags to CFT Stacks and all resources, format: Name|Test,Env|Dev",
        required=False)
    args = parser.parse_args()
    main(args.aws_profile_name, control_role=args.control_role,
         region=args.region, avoid_waiting=args.avoid_waiting, custom_tags=args.custom_tags)

import argparse
import botocore
import boto3
import concurrent.futures
import os
import termcolor
import traceback
import logging
from botocore.exceptions import ClientError
from datetime import datetime

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

def log_with_color(message, color="white", level="info"):
    """Helper function to log messages with color and proper logging level"""
    colored_message = termcolor.colored(message, color)
    if level == "error":
        logger.error(colored_message)
    elif level == "warning":
        logger.warning(colored_message)
    else:
        logger.info(colored_message)

def main(aws_profile_name, control_role="OrganizationAccountAccessRole",
         region=None, avoid_waiting=False, custom_tags=None, include_collection_stacks=False, accounts=None, max_workers=5):
    start_time = datetime.now()
    log_with_color(f"Starting stack update process at {start_time}", "blue")
    
    # Prepare tags if provided
    if custom_tags:
        try:
            custom_tags = [{'Key': k.split("|")[0], 'Value': k.split("|")[1]} for k in custom_tags.split(",")]
            log_with_color(f"Parsed custom tags: {custom_tags}", "blue")
        except Exception as e:
            log_with_color(f"Failed to parse custom tags: {str(e)}", "red", "error")
            raise
    
    # Set the AWS_PROFILE environment variable
    os.environ['AWS_PROFILE'] = aws_profile_name
    log_with_color(f"Using AWS profile: {aws_profile_name}", "blue")
    
    sts_client = boto3.client('sts')
    try:
        # Set up org account variable
        org_account_id = sts_client.get_caller_identity().get('Account')
        log_with_color(f"Organization account ID: {org_account_id}", "blue")
    except Exception as e:
        org_account_id = None
        log_with_color(f"Could not get org account ID: {str(e)}", "red", "error")
        log_with_color(f"Stack trace: {traceback.format_exc()}", "red", "error")
        raise
    
    if not accounts:
        try:
            # Set up the Organizations client
            org_client = boto3.client('organizations')
            # Set up the STS client

            # Set up an empty list to store the sub_account IDs
            sub_accounts = []
            # Set up a paginator for the list_accounts operation
            paginator = org_client.get_paginator('list_accounts')

            # Iterate over the pages of results
            log_with_color("Retrieving all accounts from organization", "blue")
            for page in paginator.paginate():
                # Iterate over the accounts in the page
                for account in page['Accounts']:
                    # If the account is a sub_account and is not the one to be ignored, add its ID to the list
                    if (account['Id'] != org_client.describe_organization()['Organization']['Id']
                            and account['Id']
                            and account['Status'] == "ACTIVE"):
                        sub_accounts.append(account['Id'])
            log_with_color(f"Found {len(sub_accounts)} active accounts", "green")
    
        except Exception as e:
            log_with_color(f"Failed to retrieve organization accounts: {str(e)}", "red", "error")
            log_with_color(f"Stack trace: {traceback.format_exc()}", "red", "error")
            raise
    else:
        try:
            accounts = accounts.replace(" ", "").split(",")
            sub_accounts = accounts
            log_with_color(f"Using specified accounts: {accounts}", "green")
        except Exception as e:
            log_with_color(f"Failed to parse account list: {str(e)}", "red", "error")
            raise

    # Process each account
    for sub_account in sub_accounts:
        try:
            if sub_account == org_account_id:
                sub_account_session = boto3.Session()
                log_with_color(f"Using existing session for org account {sub_account}", "blue")
            else:
                try:
                    assumed_role = sts_client.assume_role(
                        RoleArn=f'arn:aws:iam::{sub_account}:role/{control_role}',
                        RoleSessionName='MySessionName'
                    )
                    sub_account_session = boto3.Session(
                        aws_access_key_id=assumed_role['Credentials']['AccessKeyId'],
                        aws_secret_access_key=assumed_role['Credentials']['SecretAccessKey'],
                        aws_session_token=assumed_role['Credentials']['SessionToken']
                    )
                    log_with_color(f"Successfully assumed role for account {sub_account}", "green")
                except ClientError as e:
                    log_with_color(f"Failed to assume role for account {sub_account}: {str(e)}", "red", "error")
                    continue

            if region:
                regions = [region]
                log_with_color(f"Using specified region: {region}", "blue")
            else:
                try:
                    # Get the list of all regions
                    regions = [region['RegionName'] for region in
                               sub_account_session.client('ec2').describe_regions()['Regions']]
                    log_with_color(f"Retrieved {len(regions)} regions for account {sub_account}", "blue")
                except Exception as e:
                    log_with_color(f"Failed to get regions for account {sub_account}: {str(e)}", "red", "error")
                    continue

            include_filters = ["-streamsec-", "-lightlytics-", "LightlyticsStack-"]
            exclude_filters = ["-collection-", "LightlyticsCollectionLambdas"]
            if include_collection_stacks:
                exclude_filters = []
                log_with_color("Including collection stacks in update", "yellow", "warning")

            with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = [executor.submit(
                    update_stack, sub_account_session, region, include_filters, exclude_filters,
                    sub_account, avoid_waiting, custom_tags) for region in regions]
                
                # Wait for all futures to complete and handle any exceptions
                for future in concurrent.futures.as_completed(futures):
                    try:
                        future.result()
                    except Exception as e:
                        log_with_color(f"Error in thread: {str(e)}", "red", "error")
                        log_with_color(f"Stack trace: {traceback.format_exc()}", "red", "error")

        except Exception as e:
            log_with_color(f"Error processing account {sub_account}: {str(e)}", "red", "error")
            log_with_color(f"Stack trace: {traceback.format_exc()}", "red", "error")
            continue

    end_time = datetime.now()
    duration = end_time - start_time
    log_with_color(f"Stack update process completed in {duration}", "green")


def update_stack(sub_account_session, region, include_filters, exclude_filters, sub_account, avoid_waiting, custom_tags):
    stacks = []
    cfn_client = ""
    try:
        # Set up a new CloudFormation client for the current region
        cfn_client = sub_account_session.client('cloudformation', region_name=region)
        # Get the list of stacks in the region
        stacks = cfn_client.list_stacks()['StackSummaries']
        log_with_color(f"Retrieved {len(stacks)} total stacks in region {region}", "blue")
    except Exception as e:
        log_with_color(f"Failed to list stacks in {region}: {str(e)}", "red", "error")
        log_with_color(f"Stack trace: {traceback.format_exc()}", "red", "error")
        return False

    # Count stacks matching include filters
    matching_include = [stack for stack in stacks if any(include_filter in stack['StackName'] for include_filter in include_filters)]
    log_with_color(f"Found {len(matching_include)} stacks matching include filters: {include_filters}", "blue")

    # Count stacks matching exclude filters
    matching_exclude = [stack for stack in matching_include if any(exclude_filter in stack['StackName'] for exclude_filter in exclude_filters)]
    log_with_color(f"Found {len(matching_exclude)} stacks matching exclude filters: {exclude_filters}", "blue")

    # Rolling back "UPDATE_ROLLBACK_FAILED" stacks
    rollback_stacks = [stack for stack in stacks if
                       ((any(include_filter in stack['StackName'] for include_filter in include_filters)) and
                        not any(exclude_filter in stack['StackName'] for exclude_filter in exclude_filters) and
                        stack['StackStatus'] == 'UPDATE_ROLLBACK_FAILED') and
                       'ParentId' not in stack]
    
    log_with_color(f"Found {len(rollback_stacks)} stacks in need of rollback", "yellow", "warning")
    if rollback_stacks:
        log_with_color(f"Stacks requiring rollback: {[stack['StackName'] for stack in rollback_stacks]}", "yellow", "warning")
    
    for rb_stack in rollback_stacks:
        try:
            log_with_color(f"Rolling back stack: '{rb_stack['StackName']}'", "yellow", "warning")
            cfn_client.continue_update_rollback(StackName=rb_stack['StackName'])
            if not avoid_waiting:
                cfn_client.get_waiter('stack_rollback_complete').wait(StackName=rb_stack['StackName'])
            log_with_color(f"Successfully rolled back stack: '{rb_stack['StackName']}'", "green")
        except Exception as e:
            log_with_color(f"Failed to rollback stack {rb_stack['StackName']}: {str(e)}", "red", "error")
            log_with_color(f"Stack trace: {traceback.format_exc()}", "red", "error")

    # Filter the list of stacks for update
    update_stacks = [stack for stack in stacks if
                       ((any(include_filter in stack['StackName'] for include_filter in include_filters)) and
                        not any(exclude_filter in stack['StackName'] for exclude_filter in exclude_filters) and
               (stack['StackStatus'] == 'CREATE_COMPLETE' or
                stack['StackStatus'] == 'UPDATE_COMPLETE' or
                stack['StackStatus'] == 'UPDATE_ROLLBACK_COMPLETE')) and
              'ParentId' not in stack]

    log_with_color(f"Found {len(update_stacks)} stacks eligible for update", "blue")
    if update_stacks:
        log_with_color(f"Stacks to be updated: {[stack['StackName'] for stack in update_stacks]}", "blue")

    if len(update_stacks) == 0:
        log_with_color(f"Account: {sub_account} | The region '{region}' has no Lightlytics stacks to update", "blue")
        return False
    else:
        log_with_color(
            f"Account: {sub_account} | Processing {len(update_stacks)} Lightlytics Stacks in region '{region}'", "blue")

    # Create a ThreadPoolExecutor to run the update_single_stack function concurrently
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        futures = [executor.submit(update_single_stack, cfn_client, stack,
                                   region, avoid_waiting, custom_tags) for stack in update_stacks]

        # Wait for all futures to complete and handle any exceptions
        for future in concurrent.futures.as_completed(futures):
            try:
                future.result()
            except Exception as e:
                log_with_color(f"Error in thread: {str(e)}", "red", "error")
                log_with_color(f"Stack trace: {traceback.format_exc()}", "red", "error")


def update_single_stack(cfn_client, stack, region, avoid_waiting, custom_tags):
    stack_name = stack['StackName']
    try:
        log_with_color(f"Starting update for stack: {stack_name}", "blue")
        
        # Get current stack parameters
        try:
            stack_details = cfn_client.describe_stacks(StackName=stack_name)['Stacks'][0]
            current_parameters = stack_details.get('Parameters', [])
            # Get required capabilities from the stack
            required_capabilities = stack_details.get('Capabilities', [])
            log_with_color(f"Retrieved {len(current_parameters)} parameters and {len(required_capabilities)} capabilities from stack {stack_name}", "blue")
        except Exception as e:
            log_with_color(f"Failed to get current parameters for stack {stack_name}: {str(e)}", "red", "error")
            log_with_color(f"Stack trace: {traceback.format_exc()}", "red", "error")
            current_parameters = []
            required_capabilities = ['CAPABILITY_IAM', 'CAPABILITY_NAMED_IAM']  # Default to most common capabilities

        if custom_tags:
            cfn_client.update_stack(
                StackName=stack_name,
                UsePreviousTemplate=True,
                Parameters=current_parameters,
                Tags=custom_tags,
                Capabilities=required_capabilities
            )
            log_with_color(f"Updated stack {stack_name} with custom tags and previous parameters", "blue")
        else:
            cfn_client.update_stack(
                StackName=stack_name,
                UsePreviousTemplate=True,
                Parameters=current_parameters,
                Capabilities=required_capabilities
            )
            log_with_color(f"Updated stack {stack_name} with previous parameters", "blue")
            
        if not avoid_waiting:
            log_with_color(f"Waiting for stack {stack_name} update to complete...", "blue")
            cfn_client.get_waiter('stack_update_complete').wait(StackName=stack_name)
            log_with_color(f"Stack {stack_name} update completed successfully", "green")
        else:
            log_with_color(f"Stack {stack_name} update initiated (not waiting for completion)", "yellow", "warning")
            
    except ClientError as e:
        error_code = e.response['Error']['Code']
        error_message = e.response['Error']['Message']
        
        # Handle "No updates are to be performed" as a warning
        if error_code == 'ValidationError' and 'No updates are to be performed' in error_message:
            log_with_color(f"Stack {stack_name} in {region} is already up to date", "green")
        else:
            log_with_color(f"Failed to update stack {stack_name} in {region}: {error_code} - {error_message}", "red", "error")
            log_with_color(f"Stack trace: {traceback.format_exc()}", "red", "error")
    except Exception as e:
        log_with_color(f"Unexpected error updating stack {stack_name}: {str(e)}", "red", "error")
        log_with_color(f"Stack trace: {traceback.format_exc()}", "red", "error")


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
        "--accounts", help="Select only specific accounts to update, format: 123456789012,123456789013", required=False)
    parser.add_argument(
        "--avoid_waiting", help="Don't wait for the stacks to update", action="store_true")
    parser.add_argument(
        "--include_collection_stacks", help="Update also the collection stacks (use with caution as it might require resetting the lambda triggers and permissions)", action="store_true")
    parser.add_argument(
        "--custom_tags", help="Add custom tags to CFT Stacks and all resources, format: Name|Test,Env|Dev",
        required=False)
    parser.add_argument(
        "--max_workers", help="Maximum number of concurrent workers for stack updates", type=int, default=5)
    args = parser.parse_args()
    main(args.aws_profile_name, control_role=args.control_role,
         region=args.region, avoid_waiting=args.avoid_waiting, custom_tags=args.custom_tags, include_collection_stacks=args.include_collection_stacks, accounts=args.accounts,
         max_workers=args.max_workers)

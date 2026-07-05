import argparse
import botocore
import boto3
import collections
import concurrent.futures
import os
import sys
import termcolor
import traceback
import logging
from botocore.exceptions import ClientError, WaiterError
from datetime import datetime

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# Stack statuses this script acts on: UPDATE_STATUSES are eligible for a
# template update, ROLLBACK_STATUSES first need continue_update_rollback.
UPDATE_STATUSES = ['CREATE_COMPLETE', 'UPDATE_COMPLETE', 'UPDATE_ROLLBACK_COMPLETE']
ROLLBACK_STATUSES = ['UPDATE_ROLLBACK_FAILED']

# Per-stack outcomes collected during the run for the end-of-run summary
# (list.append is atomic under CPython, so worker threads record directly).
RUN_RESULTS = []


def record_result(account, region, stack_name, outcome, reason=""):
    RUN_RESULTS.append({"account": account, "region": region,
                        "stack": stack_name, "outcome": outcome, "reason": reason})


def print_summary():
    """Print counts for all outcomes and details only for failures, so the
    summary stays readable on large (250+ account) runs. Returns the number
    of stacks needing attention (failures plus rollbacks that still require
    a re-run), which drives the process exit code."""
    counts = collections.Counter(r["outcome"] for r in RUN_RESULTS)
    failed = [r for r in RUN_RESULTS if r["outcome"] == "failed"]
    log_with_color("=" * 60, "blue")
    log_with_color(
        f"Run summary: {counts['updated']} updated | {counts['initiated']} update initiated (not waited) | "
        f"{counts['up_to_date']} already up to date | {counts['rollback_initiated']} rollback initiated (not waited) | "
        f"{counts['failed']} failed", "blue")
    for r in failed:
        log_with_color(
            f"  FAILED | account {r['account']} | {r['region']} | {r['stack']} | {r['reason']}", "red", "error")
    if failed:
        log_with_color(
            "Inspect the failed stacks' events in the CloudFormation console, then re-run for those accounts.",
            "yellow", "warning")
    if counts['rollback_initiated']:
        log_with_color(
            f"{counts['rollback_initiated']} stack(s) had a rollback initiated and were NOT updated "
            f"(--avoid_waiting) — re-run this script for them once the rollbacks finish.",
            "yellow", "warning")
    return len(failed) + counts['rollback_initiated']

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
    
    # Set the AWS_PROFILE environment variable only if explicitly provided
    if aws_profile_name:
        os.environ['AWS_PROFILE'] = aws_profile_name
        log_with_color(f"Using AWS profile: {aws_profile_name}", "blue")
    else:
        log_with_color("No AWS profile specified, using default credential chain", "blue")
    
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
                    record_result(sub_account, "-", "-", "failed", "could not assume control role")
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
                    record_result(sub_account, "-", "-", "failed", "could not list regions")
                    continue

            include_filters = ["-streamsec-", "-lightlytics-", "LightlyticsStack-", "LightlyticsCostModule"]
            exclude_filters = ["-collection-", "LightlyticsCollectionLambdas"]
            if include_collection_stacks:
                exclude_filters = []
                log_with_color("Including collection stacks in update", "yellow", "warning")

            with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_to_region = {executor.submit(
                    update_stack, sub_account_session, region, include_filters, exclude_filters,
                    sub_account, avoid_waiting, custom_tags): region for region in regions}

                # Wait for all futures to complete and handle any exceptions
                for future in concurrent.futures.as_completed(future_to_region):
                    try:
                        future.result()
                    except Exception as e:
                        failed_region = future_to_region[future]
                        log_with_color(f"Error in thread for region {failed_region}: {str(e)}", "red", "error")
                        log_with_color(f"Stack trace: {traceback.format_exc()}", "red", "error")
                        record_result(sub_account, failed_region, "-", "failed", f"region worker error: {str(e)}"[:200])

        except Exception as e:
            log_with_color(f"Error processing account {sub_account}: {str(e)}", "red", "error")
            log_with_color(f"Stack trace: {traceback.format_exc()}", "red", "error")
            record_result(sub_account, "-", "-", "failed", f"unexpected error: {str(e)}"[:200])
            continue

    needs_attention = print_summary()
    end_time = datetime.now()
    duration = end_time - start_time
    log_with_color(f"Stack update process completed in {duration}", "green")
    return needs_attention


def update_stack(sub_account_session, region, include_filters, exclude_filters, sub_account, avoid_waiting, custom_tags):
    stacks = []
    cfn_client = ""
    try:
        # Set up a new CloudFormation client for the current region
        cfn_client = sub_account_session.client('cloudformation', region_name=region)
        # Get the list of stacks in the region. Paginate (a single list_stacks
        # call returns at most 100 summaries) and filter to the statuses this
        # script acts on — an unfiltered call also returns stacks deleted in
        # the last 90 days, which can push live stacks past the first page.
        for page in cfn_client.get_paginator('list_stacks').paginate(
                StackStatusFilter=UPDATE_STATUSES + ROLLBACK_STATUSES):
            stacks.extend(page['StackSummaries'])
        log_with_color(f"Retrieved {len(stacks)} stacks in actionable statuses in region {region}", "blue")
    except Exception as e:
        log_with_color(f"Failed to list stacks in {region}: {str(e)}", "red", "error")
        log_with_color(f"Stack trace: {traceback.format_exc()}", "red", "error")
        record_result(sub_account, region, "-", "failed", "could not list stacks in region")
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
                        stack['StackStatus'] in ROLLBACK_STATUSES) and
                       'ParentId' not in stack]
    
    log_with_color(f"Found {len(rollback_stacks)} stacks in need of rollback", "yellow", "warning")
    if rollback_stacks:
        log_with_color(f"Stacks requiring rollback: {[stack['StackName'] for stack in rollback_stacks]}", "yellow", "warning")
    
    for rb_stack in rollback_stacks:
        try:
            log_with_color(f"Rolling back stack: '{rb_stack['StackName']}'", "yellow", "warning")
            cfn_client.continue_update_rollback(StackName=rb_stack['StackName'])
            if avoid_waiting:
                # The rollback runs unattended, so this stack cannot be updated
                # in this run — surface it in the summary instead of dropping it.
                log_with_color(f"Rollback of '{rb_stack['StackName']}' initiated (not waiting); "
                               f"re-run later to update this stack", "yellow", "warning")
                record_result(sub_account, region, rb_stack['StackName'], "rollback_initiated")
                continue
            cfn_client.get_waiter('stack_rollback_complete').wait(StackName=rb_stack['StackName'])
            # The cached summary still shows the pre-rollback status; correct it
            # so the update filter below picks this stack up.
            rb_stack['StackStatus'] = 'UPDATE_ROLLBACK_COMPLETE'
            log_with_color(f"Successfully rolled back stack: '{rb_stack['StackName']}'", "green")
        except Exception as e:
            # The waiter also fails on timeout, so re-check the actual status
            # before recording: the rollback may have completed just after the
            # last poll (same re-check pattern as the update waiter below).
            try:
                final_status = cfn_client.describe_stacks(
                    StackName=rb_stack['StackName'])['Stacks'][0]['StackStatus']
            except Exception:
                final_status = "UNKNOWN"
            if final_status == 'UPDATE_ROLLBACK_COMPLETE':
                rb_stack['StackStatus'] = 'UPDATE_ROLLBACK_COMPLETE'
                log_with_color(f"Successfully rolled back stack: '{rb_stack['StackName']}'", "green")
                continue
            log_with_color(f"Failed to rollback stack {rb_stack['StackName']}: {str(e)}", "red", "error")
            log_with_color(f"Stack trace: {traceback.format_exc()}", "red", "error")
            record_result(sub_account, region, rb_stack['StackName'], "failed",
                          f"rollback did not complete (status {final_status}): {str(e)}"[:200])

    # Filter the list of stacks for update (stacks successfully rolled back
    # above had their cached status corrected, so they are included here)
    update_stacks = [stack for stack in stacks if
                       ((any(include_filter in stack['StackName'] for include_filter in include_filters)) and
                        not any(exclude_filter in stack['StackName'] for exclude_filter in exclude_filters) and
               stack['StackStatus'] in UPDATE_STATUSES) and
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
                                   region, avoid_waiting, custom_tags, sub_account) for stack in update_stacks]

        # Wait for all futures to complete and handle any exceptions
        for future in concurrent.futures.as_completed(futures):
            try:
                future.result()
            except Exception as e:
                log_with_color(f"Error in thread: {str(e)}", "red", "error")
                log_with_color(f"Stack trace: {traceback.format_exc()}", "red", "error")


def update_single_stack(cfn_client, stack, region, avoid_waiting, custom_tags, sub_account="-"):
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
            record_result(sub_account, region, stack_name, "updated")
        else:
            log_with_color(f"Stack {stack_name} update initiated (not waiting for completion)", "yellow", "warning")
            record_result(sub_account, region, stack_name, "initiated")

    except WaiterError as e:
        # The waiter gives up on terminal states AND on timeout, so check the
        # stack's actual status before telling the operator what happened.
        try:
            final_status = cfn_client.describe_stacks(StackName=stack_name)['Stacks'][0]['StackStatus']
        except Exception:
            final_status = "UNKNOWN"
        if final_status in ('UPDATE_COMPLETE', 'UPDATE_COMPLETE_CLEANUP_IN_PROGRESS'):
            # The update finished between the waiter's last poll (or timeout)
            # and this re-check — it succeeded. CLEANUP_IN_PROGRESS only occurs
            # after a successful update, while replaced resources are removed.
            log_with_color(f"Stack {stack_name} update completed successfully", "green")
            record_result(sub_account, region, stack_name, "updated")
            return
        if final_status == 'UPDATE_ROLLBACK_COMPLETE':
            msg = (f"Stack {stack_name} in {region}: update failed and was rolled back by CloudFormation "
                   f"(stack restored to its previous state). Check the stack's events in the "
                   f"CloudFormation console for the failing resource.")
            reason = "update rolled back by CloudFormation"
        elif final_status == 'UPDATE_ROLLBACK_FAILED':
            msg = (f"Stack {stack_name} in {region}: update failed and the rollback also failed — the stack "
                   f"is stuck in UPDATE_ROLLBACK_FAILED. A re-run will attempt continue_update_rollback, "
                   f"or fix the blocking resource in the CloudFormation console first.")
            reason = "update failed and rollback failed (UPDATE_ROLLBACK_FAILED)"
        elif 'ROLLBACK' in final_status:
            # UPDATE_ROLLBACK_IN_PROGRESS / _CLEANUP_IN_PROGRESS: the update
            # already failed and CloudFormation is still reverting it — it can
            # never finish successfully.
            msg = (f"Stack {stack_name} in {region}: update failed and CloudFormation is rolling it back "
                   f"(status {final_status}). Check the stack's events in the CloudFormation console "
                   f"for the failing resource.")
            reason = f"update failed; rollback in progress ({final_status})"
        elif final_status.endswith('_IN_PROGRESS'):
            msg = (f"Stack {stack_name} in {region}: gave up waiting but the update is still running "
                   f"(status {final_status}) — it may yet finish; check the CloudFormation console later. "
                   f"Waiter reason: {e}")
            reason = f"timed out waiting; stack still {final_status}"
        else:
            msg = (f"Stack {stack_name} in {region}: update did not reach UPDATE_COMPLETE "
                   f"(final status: {final_status}). Waiter reason: {e}")
            reason = f"update ended in {final_status}"
        log_with_color(msg, "red", "error")
        record_result(sub_account, region, stack_name, "failed", reason)
    except ClientError as e:
        error_code = e.response['Error']['Code']
        error_message = e.response['Error']['Message']

        # Handle "No updates are to be performed" as a warning
        if error_code == 'ValidationError' and 'No updates are to be performed' in error_message:
            log_with_color(f"Stack {stack_name} in {region} is already up to date", "green")
            record_result(sub_account, region, stack_name, "up_to_date")
        else:
            log_with_color(f"Failed to update stack {stack_name} in {region}: {error_code} - {error_message}", "red", "error")
            log_with_color(f"Stack trace: {traceback.format_exc()}", "red", "error")
            record_result(sub_account, region, stack_name, "failed", f"{error_code}: {error_message}"[:200])
    except Exception as e:
        log_with_color(f"Unexpected error updating stack {stack_name}: {str(e)}", "red", "error")
        log_with_color(f"Stack trace: {traceback.format_exc()}", "red", "error")
        record_result(sub_account, region, stack_name, "failed", str(e)[:200])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="This script will integrate StreamSecurity environment with every account in the organization.")
    parser.add_argument(
        "--aws_profile_name", help="The AWS profile with admin permissions in organization account (optional, uses default credential chain if not specified)", default=None)
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
    needs_attention = main(args.aws_profile_name, control_role=args.control_role,
                           region=args.region, avoid_waiting=args.avoid_waiting, custom_tags=args.custom_tags, include_collection_stacks=args.include_collection_stacks, accounts=args.accounts,
                           max_workers=args.max_workers)
    sys.exit(1 if needs_attention else 0)

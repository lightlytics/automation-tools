import botocore
import boto3
import tqdm
import termcolor
from botocore.exceptions import ClientError
import os

# Set the AWS_PROFILE environment variable, you aws configure profile name
os.environ['AWS_PROFILE'] = 'orgroot'

# Set up the Organizations client
org_client = boto3.client('organizations')

# Set up the STS client
sts_client = boto3.client('sts')

# Set up an empty list to store the sub_account IDs
sub_accounts = []

# Set up a paginator for the list_accounts operation
paginator = org_client.get_paginator('list_accounts')

# Iterate over the pages of results
for page in paginator.paginate():
    # Iterate over the accounts in the page
    for account in page['Accounts']:
        # If the account is a sub_account and is not the one to be ignored, add its ID to the list
        if account['Id'] != org_client.describe_organization()['Organization']['Id'] and account['Id']:
            sub_accounts.append(account['Id'])

# Now you can use the sub_accounts list to iterate over the sub_accounts and print a success message if the
# assume_role call and the creation of the Boto3 session were successful
for sub_account in sub_accounts:
    try:
        # Assume the role in the sub_account
        assumed_role = sts_client.assume_role(
            RoleArn='arn:aws:iam::{}:role/OrganizationAccountAccessRole'.format(sub_account),
            RoleSessionName='MySessionName'
        )

        # Create a Boto3 session using the assumed role credentials
        sub_account_session = boto3.Session(
            aws_access_key_id=assumed_role['Credentials']['AccessKeyId'],
            aws_secret_access_key=assumed_role['Credentials']['SecretAccessKey'],
            aws_session_token=assumed_role['Credentials']['SessionToken']
        )

        # Set up the CloudFormation client , use this in case you have an account connected via aws configure cli
        cfn_client = sub_account_session.client('cloudformation')

        # Get the list of all regions
        regions = [region['RegionName'] for region in sub_account_session.client('ec2').describe_regions()['Regions']]

        # set CloudFormation stackname prefix
        prefix = "-lightlytics-"

        # set CloudFormation prefix of nested stack to ignore it
        n1prefix = "-LightlyticsCollectionLambdas-"

        # set CloudFormation prefix of nested stack to ignore it
        n2prefix = "-LightlyticsInitLambdas-"

        # Iterate over each region
        for region in regions:
            # Set up a new CloudFormation client for the current region
            cfn_client = sub_account_session.client('cloudformation', region_name=region)

            # Get the list of stacks in the region
            stacks = cfn_client.list_stacks()['StackSummaries']

            # Filter the list of stacks to only include a specific prefix
            # and status is complete create or update complete

            stacks = [stack for stack in stacks if
                      (prefix in stack['StackName'] and
                       (stack['StackStatus'] == 'CREATE_COMPLETE' or
                        stack['StackStatus'] == 'UPDATE_COMPLETE')) and
                      not n1prefix in stack['StackName'] and not n2prefix in stack['StackName']]

            # print all found stacks names
            print([stack['StackName'] for stack in stacks])

            # Iterate over each stack and update it
            for stack in tqdm.tqdm(stacks, desc=f"Updating stacks in {region}"):
                stack_name = stack['StackName']
                try:
                    # Update the stack using the existing template
                    cfn_client.update_stack(StackName=stack_name, UsePreviousTemplate=True)

                    # Wait for the update to complete
                    cfn_client.get_waiter('stack_update_complete').wait(StackName=stack_name)

                    # Print the name of the stack that was successfully updated
                    print(termcolor.colored(f"Successfully updated stack {stack_name} in {region}", "green"))

                except ClientError as e:

                    # Print an error message if the stack no longer exists
                    print(termcolor.colored(f"Failed to update stack {stack_name} in {region}: {e}", "red"))

        # Print a success message
        print("Success for sub_account {}".format(sub_account))
    except botocore.exceptions.ClientError as e:
        # Print an error message
        print("Error for sub_account {}: {}".format(sub_account, e))

#!/bin/bash

# Check if the required parameters are provided
if [ $# -lt 4 ]; then
    echo "Usage: $0 {ENVIRONMENT} {ENVIRONMENT_USER_NAME} {ENVIRONMENT_PASSWORD} {WS_ID} {CUSTOM_TAGS}"
    echo "Example: $0 production admin_user my_password 12345 'tag1=value1,tag2=value2'"
    echo ""
    echo "Parameters:"
    echo "  ENVIRONMENT            - The environment name in which the Lambda function will operate (usualy that's the subdomain of your StreamSecurity Env.)."
    echo "  ENVIRONMENT_USER_NAME  - The username for the environment."
    echo "  ENVIRONMENT_PASSWORD   - The password for the environment."
    echo "  WS_ID                  - The workspace ID."
    echo "  CUSTOM_TAGS            - Custom tags to be applied to the Lambda function, in the format 'key1=value1,key2=value2'."
    exit 1
fi

ENVIRONMENT=$1
ENVIRONMENT_USER_NAME=$2
ENVIRONMENT_PASSWORD=$3
WS_ID=$4
CUSTOM_TAGS=$5

echo "Welcome to the Streamsec Organization Lambda Setup Script!"
echo "The purpose of this script is to create an AWS Lambda function that will be triggered by EventBridge when a new AWS account is created."
echo "This script will perform the following actions:"
echo "1. Create an IAM policy with permissions to list AWS accounts and describe EC2 regions (required to get the list of regions in the new account)."
echo "2. Create an IAM role for the Lambda function with the necessary assume role policy (required to assume the OrganizationAccountAccessRole in the new account)."
echo "3. Attach the created policy and the AWS Lambda basic execution role policy to the IAM role."
echo "4. Create a Lambda function with the specified configurations."
echo "5. Create an EventBridge rule to trigger the Lambda function when a new AWS account is created."
echo "6. Add necessary permissions for EventBridge to invoke the Lambda function."
echo "7. Set the EventBridge rule target to the Lambda function."

echo "Before we start make sure that you have the AWS CLI installed and configured with the necessary permissions for your organization account."

read -p "Do you want to proceed with these actions? (yes/no): " user_input

if [ "$user_input" != "yes" ]; then
    echo "Script execution aborted by the user."
    exit 1
fi

echo "Starting the setup process..."

aws_account_id=$(aws sts get-caller-identity --query Account --output text)
region=$(aws configure get region)

# Policy
aws iam create-policy \
    --output text \
    --policy-name streamsec-organization-lambda-policy \
    --policy-document '{
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "VisualEditor0",
                "Effect": "Allow",
                "Action": [
                    "organizations:ListAccounts",
                    "ec2:DescribeRegions"
                ],
                "Resource": "*"
            },
            {
                "Sid": "VisualEditor1",
                "Effect": "Allow",
                "Action": "sts:AssumeRole",
                "Resource": "arn:aws:iam::*:role/OrganizationAccountAccessRole"
            }
        ]
    }'

# Role
aws iam create-role \
    --output text \
    --role-name streamsec-organization-lambda-role \
    --assume-role-policy-document '{
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {
                    "Service": "lambda.amazonaws.com"
                },
                "Action": "sts:AssumeRole"
            }
        ]
    }'

# Attach policy to role
aws iam attach-role-policy \
    --output text \
    --role-name streamsec-organization-lambda-role \
    --policy-arn arn:aws:iam::${aws_account_id}:policy/streamsec-organization-lambda-policy

# Attach lambda execution role policy
aws iam attach-role-policy \
    --output text \
    --role-name streamsec-organization-lambda-role \
    --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole

sleep 5

aws lambda create-function \
    --output text \
    --function-name streamsec-organization-lambda \
    --runtime python3.12 \
    --role arn:aws:iam::${aws_account_id}:role/streamsec-organization-lambda-role \
    --handler app.lambda_handler \
    --code S3Bucket=prod-lightlytics-artifacts-us-east-1,S3Key=organization_script/lambda.zip \
    --memory-size 2048 \
    --timeout 900 \
    --environment Variables="{ENVIRONMENT=$ENVIRONMENT,ENVIRONMENT_USER_NAME=$ENVIRONMENT_USER_NAME,ENVIRONMENT_PASSWORD=$ENVIRONMENT_PASSWORD,WS_ID=$WS_ID,CUSTOM_TAGS=$CUSTOM_TAGS,PARALLEL=8}" \
    --publish

# Create EventBridge rule for new AWS accounts
aws events put-rule \
    --name streamsec-organization-newaccount-rule \
    --event-pattern '{
        "source": ["aws.organizations"],
        "detail-type": ["AWS API Call via CloudTrail"],
        "detail": {
            "eventName": ["CreateAccountResult"]
        }
    }' \
    --description "Rule to trigger Lambda when a new AWS account is created"

# Add Lambda permission for EventBridge
aws lambda add-permission \
    --function-name streamsec-organization-lambda \
    --statement-id EventBridgeInvokeLambda \
    --action "lambda:InvokeFunction" \
    --principal events.amazonaws.com \
    --source-arn arn:aws:events:${region}:${aws_account_id}:rule/streamsec-organization-newaccount-rule

# Set EventBridge rule target to Lambda function
aws events put-targets \
    --rule streamsec-organization-newaccount-rule \
    --targets "Id"="1","Arn"="arn:aws:lambda:${region}:${aws_account_id}:function:streamsec-organization-lambda"


echo "Setup completed successfully!"
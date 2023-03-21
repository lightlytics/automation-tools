# automation-tools
Automation tools for easier Lightlytics Integration

## Installation
To install the dependencies, run the following command:

```pip install -r requirements.txt```
This will install all the required libraries listed in the `requirements.txt` file.

## "organization based integration" tool usage
You need to have "aws-cli" installed.
Before running the script, set a profile named "staging" with access/secret of the root or an IAM user (admin permissions) on the organization account.
To do that:

```aws configure --profile staging```
 
To run the script, simply execute:

```python src/python/utilities/organization_integration.py --environment_sub_domain <ENV_NAME> --environment_user_name <ENV_USERNAME> --environment_password <ENV_PASSWORD>```

Note that the script will use the `staging` AWS profile - make sure that it has the proper organization level IAM permissions

## Prerequisites
- Python 3.7 or higher
- pip
- All dependencies listed in the `requirements.txt` file
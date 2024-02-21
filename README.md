# automation-tools
This repository provides various Automation Tools for the Stream Security platform

## Installation
To install the dependencies, run the following command:

```pip install -r requirements.txt```
This will install all the required libraries listed in the `requirements.txt` file.

## "organization based integration" tool usage
You need to have "aws-cli" installed.

 
To run the script, simply execute:

```python src/python/utilities/organization_integration.py --environment_sub_domain <ENV_NAME> --environment_user_name <ENV_USERNAME> --environment_password <ENV_PASSWORD>```

Note that the script will use the `staging` AWS profile by default - make sure that it has the proper organization level IAM permissions, if you want to point to another AWS profile, you can add the `aws_profile_name` flag.

Script execution with the AWS profile flag:

```python src/python/utilities/organization_integration.py --environment_sub_domain <ENV_NAME> --environment_user_name <ENV_USERNAME> --environment_password <ENV_PASSWORD> --aws_profile_name <AWS_PROFILE_NAME>```

## Prerequisites
- Python 3.9 or higher
- pip
- All dependencies listed in the `requirements.txt` file
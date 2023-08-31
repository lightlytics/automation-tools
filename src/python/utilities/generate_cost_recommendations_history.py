import argparse
import csv
import os
import pandas as pd
import sys
from datetime import datetime

# Add the project root directory to the Python path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')))
try:
    from src.python.common.common import *
except ModuleNotFoundError:
    sys.path.append("../../..")
    from src.python.common.common import *


def main(environment, ll_username, ll_password, ws_name, request_date, stage=None):
    # Connecting to Lightlytics
    graph_client = get_graph_client(environment, ll_username, ll_password, ws_name, stage)

    # Verify if the request_date is in the correct format
    if not verify_date_format(request_date):
        raise ValueError("Incorrect date format. Please use YYYY/MM/DD.")

    # Get all available dates to query history from
    available_dates = graph_client.get_all_recommendations_history_dates()

    # Log the available dates for the WS
    first_date, last_date, missing_dates = get_date_range(available_dates)
    date_range = f"{first_date.strftime('%Y-%m-%d')} to {last_date.strftime('%Y-%m-%d')}"
    log.info(f"Available dates - {date_range}")
    if len(missing_dates) > 0:
        log.warning(f"Missing dates: {missing_dates}")

    # Verify if date is in range and not missing
    valid = verify_date_in_range(request_date, (first_date, last_date), missing_dates)

    if valid:
        recommendations = graph_client.get_recommendations_history_by_date(request_date)
    else:
        err_msg = f"Recommendations wasn't found for date: {request_date}, " \
                  f"available dates range - {date_range}, " \
                  f"missing dates - {missing_dates}"
        log.error(err_msg)
        raise Exception(err_msg)

    csv_file = f"{environment.upper()} cost recommendations history.csv"

    fieldnames = [
        'resource_id',
        'account',
        'region',
        'name',
        'predicted_monthly_cost_savings'
    ]

    log.info(f'Generating CSV file, file name: "{csv_file}"')
    with open(csv_file, 'w', newline='') as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        for key, value in recommendations.items():
            for violation in value['violations']:
                writer.writerow({
                    'resource_id': violation['resource_id'],
                    'account': violation['account_id'],
                    'region': violation['region'],
                    'name': value['name'],
                    'predicted_monthly_cost_savings': violation.get('monthly_cost', 0) or 0
                })
    log.info("File generated successfully, export complete!")

    return csv_file


def get_recommendations(rule_id, graph_client, recommendations):
    res = graph_client.export_csv_rule(rule_id)
    if res:
        log.info(f"Found {res['violation_count']} violations in rule: {res['rule_name']}")
        recommendations[rule_id] = {"name": res["rule_name"]}
        recommendations[rule_id]["violations"] = res["violations"]


def verify_date_format(date_str):
    try:
        datetime.strptime(date_str, '%Y/%m/%d')
        return True
    except ValueError:
        return False


def get_date_range(dates):
    # Convert the list of dates to datetime objects
    datetime_dates = [datetime.strptime(date, '%Y/%m/%d') for date in dates]

    # Get the first and last dates in the list
    first_date = min(datetime_dates)
    last_date = max(datetime_dates)

    # Check for missing dates
    missing_dates = []
    date_range = pd.date_range(first_date, last_date)
    for i in date_range:
        if i not in datetime_dates:
            missing_dates.append(i.strftime('%Y-%m-%d'))

    # Print the range of dates and missing dates
    return first_date, last_date, missing_dates


def verify_date_in_range(date, date_range, missing_dates):
    datetime_date = datetime.strptime(date, '%Y/%m/%d')

    if date_range[0] <= datetime_date <= date_range[1] and datetime_date.strftime('%Y-%m-%d') not in missing_dates:
        return True
    else:
        return False


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description='This script will integrate Lightlytics environment with every account in the organization.')
    parser.add_argument(
        "--environment_sub_domain", help="The Lightlytics environment sub domain", required=True)
    parser.add_argument(
        "--environment_user_name", help="The Lightlytics environment user name", required=True)
    parser.add_argument(
        "--environment_password", help="The Lightlytics environment password", required=True)
    parser.add_argument(
        "--ws_name", help="The WS from which to fetch information", required=True)
    parser.add_argument(
        "--request_date", help="The date of the cost recommendation requested (YYYY/MM/DD)", required=True)
    parser.add_argument(
        "--stage", action="store_true")
    args = parser.parse_args()
    main(args.environment_sub_domain, args.environment_user_name, args.environment_password,
         args.ws_name, args.request_date, args.stage)

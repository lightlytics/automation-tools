import argparse
import csv
import os
import sys
from datetime import datetime


# Add the project root directory to the Python path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')))
try:
    from src.python.common.common import *
except ModuleNotFoundError:
    sys.path.append("../../..")
    from src.python.common.common import *


def main(environment, ll_username, ll_password, ll_f2a, ws_name, start_timestamp, end_timestamp, period,
         ignore_discounts=False, stage=None):
    for date_to_check in [start_timestamp, end_timestamp]:
        if not verify_date_format(date_to_check):
            raise ValueError(f"The date: {date_to_check} is not in the correct format: YYYY-MM-DD")

    if datetime.strptime(start_timestamp, "%Y-%m-%d") > datetime.strptime(end_timestamp, "%Y-%m-%d"):
        raise ValueError("Start Date is not prior to End Date")

    # Setting up variables
    start_ts = start_timestamp + "T00:00:00.000Z"
    end_ts = end_timestamp + "T23:59:59.999Z"

    if period not in ["day", "month", "year"]:
        msg = f"Wrong period value: {period}! available values: 'day', 'month', 'year'"
        log.error(msg)
        raise Exception(msg)

    # Connecting to Lightlytics
    graph_client = get_graph_client(environment, ll_username, ll_password, ll_f2a, ws_name, stage)

    log.info(f"Checking if cost is integrated in WS: {ws_name}")
    if not graph_client.check_cost_integration():
        msg = "Cost is not integrated in the workspace, exiting"
        log.error(msg)
        raise Exception(msg)
    log.info("Cost integrated, continuing!")

    log.info(f"Getting cost data, from: {start_timestamp}, to: {end_timestamp}")
    cost_chart = graph_client.get_cost_chart(start_ts, end_ts, group_by=period)
    log.info("Fetched cost information successfully!")

    if ignore_discounts:
        cost_chart = [row for row in cost_chart if row['total_cost'] > 0]

    csv_file = f'{environment.upper()} cost report {start_timestamp} {end_timestamp}.csv'

    fieldnames = [
        period,
        'resource_type',
        'product_family',
        'account',
        'region',
        'pricing_term',
        'total_cost'
    ]

    log.info(f'Generating CSV file, file name: "{csv_file}"')
    with open(csv_file, mode='w', newline='') as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(cost_chart)
    log.info("File generated successfully, export complete!")

    return csv_file


def verify_date_format(date_string):
    try:
        # Attempt to parse the date string using the specified format
        datetime.strptime(date_string, '%Y-%m-%d')
        return True  # Date is in the correct format
    except ValueError:
        return False  # Date is not in the correct format


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
        "--environment_f2a_token", help="F2A Token if set", default=None)
    parser.add_argument(
        "--ws_name", help="The WS from which to fetch information", required=True)
    parser.add_argument(
        "--start_timestamp", help="Starting date for report in Zulu format (YYYY-MM-DD)", required=True)
    parser.add_argument(
        "--end_timestamp", help="End date for report in Zulu format (YYYY-MM-DD)", required=True)
    parser.add_argument(
        "--period", help="day/month/year", required=True)
    parser.add_argument(
        "--ignore_discounts", help="Ignore all negative pricing fields", action="store_true")
    parser.add_argument(
        "--stage", action="store_true")
    args = parser.parse_args()
    main(args.environment_sub_domain, args.environment_user_name, args.environment_password, args.environment_f2a_token,
         args.ws_name, args.start_timestamp, args.end_timestamp, args.period, args.ignore_discounts, args.stage)

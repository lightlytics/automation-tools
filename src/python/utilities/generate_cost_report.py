import argparse
import csv
import os
import sys
from termcolor import colored as color


# Add the project root directory to the Python path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')))
try:
    from src.python.common.graph_common import GraphCommon
except ModuleNotFoundError:
    sys.path.append("../../..")
    from src.python.common.graph_common import GraphCommon


def main(environment, ll_username, ll_password, ws_name, start_timestamp, end_timestamp, period, stage):

    if period not in ["day", "month", "year"]:
        print(color(f"Wrong period value: {period}! available values: 'day', 'month', 'year'", "red"))
        sys.exit()

    # Setting up variables
    start_ts = start_timestamp + "T00:00:00.000Z"
    end_ts = end_timestamp + "T23:59:59.999Z"

    print(color("Trying to login into Lightlytics", "blue"))
    ll_url = f"https://{environment}.lightlytics.com"
    if stage:
        ll_url = f"https://{environment}.lightops.io"
    ll_graph_url = f"{ll_url}/graphql"
    graph_client = GraphCommon(ll_graph_url, ll_username, ll_password)
    ws_id = graph_client.get_ws_id_by_name(ws_name)
    graph_client.change_client_ws(ws_id)
    print(color("Logged in successfully!", "green"))

    print(color(f"Checking if cost is integrated in WS: {ws_name}", "blue"))
    if not graph_client.check_cost_integration():
        print(color("Cost is not integrated in the workspace, exiting", "red"))
        sys.exit()
    print(color("Cost integrated, continuing!", "green"))

    print(color(f"Getting cost data, from: {start_timestamp}, to: {end_timestamp}", "blue"))
    cost_chart = graph_client.get_cost_chart(start_ts, end_ts, group_by=period)
    print(color("Fetched cost information successfully!", "green"))

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

    print(color(f"Generating CSV file, file name: {csv_file}", "blue"))
    with open(csv_file, mode='w', newline='') as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(cost_chart)
    print(color("File generated successfully, export complete!", "green"))

    return csv_file


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
        "--start_timestamp", help="Starting date for report in Zulu format (YYYY-MM-DD)", required=True)
    parser.add_argument(
        "--end_timestamp", help="End date for report in Zulu format (YYYY-MM-DD)", required=True)
    parser.add_argument(
        "--period", help="day/month/year", required=True)
    parser.add_argument(
        "--stage", action="store_true")
    args = parser.parse_args()
    main(args.environment_sub_domain, args.environment_user_name, args.environment_password,
         args.ws_name, args.start_timestamp, args.end_timestamp, args.period, args.stage)

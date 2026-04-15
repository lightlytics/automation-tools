import argparse
import concurrent.futures
import csv
import os
import sys
from datetime import datetime, timezone

# Add the project root directory to the Python path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')))
try:
    from src.python.common.common import *
except ModuleNotFoundError:
    sys.path.append("../../..")
    from src.python.common.common import *


def _parse_timestamp(ts):
    if ts is None:
        return datetime.min.replace(tzinfo=timezone.utc)
    if isinstance(ts, (int, float)):
        # Unix epoch: detect milliseconds vs seconds
        if ts > 1e12:
            ts = ts / 1000
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    if isinstance(ts, str):
        dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
        # Force UTC on naive datetimes (e.g. "2024-01-15T10:30:00" with no offset)
        # so the later comparison against tz-aware bounds doesn't crash.
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    raise ValueError(f"Unsupported timestamp type: {type(ts).__name__}")


def enrich_detections(graph_client, detection):
    detection_enrichment = graph_client.get_detection_enrichment(detection['_id'])[0]
    detection["enrichment"] = {k: v for k, v in detection_enrichment.items() if k not in detection}


def main(environment, ll_username, ll_password, ll_f2a, ws_name, start_time, end_time, token=None, stage=None):
    # Parse and validate dates once (ValueError surfaces as 400 in main.py)
    try:
        start_dt = datetime.strptime(start_time, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        end_dt = datetime.strptime(end_time, "%Y-%m-%d").replace(
            hour=23, minute=59, second=59, microsecond=999999, tzinfo=timezone.utc)
    except ValueError as e:
        raise ValueError(f"Dates must be in YYYY-MM-DD format: {e}")
    if start_dt > end_dt:
        raise ValueError(f"Start time {start_time} is after end time {end_time}")

    # Connecting to Stream
    graph_client = get_graph_client(environment, ll_username, ll_password, ll_f2a, ws_name, stage, token=token)

    # Get all detections
    # TODO: push the timestamp filter into the GraphQL `DetectionsFilters` input
    # and drop the client-side filter once the schema is verified against a live env.
    log.info("Get all detections")
    all_detections = graph_client.get_detections()
    log.info(f"Found {len(all_detections)} detections")

    # Filter by time range (client-side; see TODO above)
    filtered_detections = [d for d in all_detections
                           if start_dt <= _parse_timestamp(d.get('timestamp')) <= end_dt]
    log.info(f"Filtered to {len(filtered_detections)} detections between {start_time} and {end_time}")

    if not filtered_detections:
        # LookupError is mapped to HTTP 404 in main.py — request was valid, nothing matched.
        raise LookupError(f"No detections found in the range {start_time} to {end_time}")

    # Enrich detections — surface individual failures in the log rather than silently discarding
    with concurrent.futures.ThreadPoolExecutor() as executor:
        futures = [executor.submit(enrich_detections, graph_client, detection)
                   for detection in filtered_detections]
        for future in concurrent.futures.as_completed(futures):
            exc = future.exception()
            if exc is not None:
                log.warning(f"Detection enrichment failed: {exc}")

    # Get columns names
    column_names = list(filtered_detections[0].keys())

    # Set CSV file name
    csv_file = f'{environment.upper()} enriched detections export {start_time} {end_time}.csv'

    log.info(f'Generating CSV file, file name: "{csv_file}"')
    try:
        with open(csv_file, mode='w', newline='') as file:
            writer = csv.DictWriter(file, fieldnames=column_names, extrasaction='ignore')
            writer.writeheader()
            writer.writerows(filtered_detections)
    except Exception:
        # Clean up partially-written file so it doesn't linger on disk
        if os.path.exists(csv_file):
            try:
                os.unlink(csv_file)
            except OSError:
                pass
        raise
    log.info("File generated successfully, export complete!")

    return csv_file


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description='This script will integrate Stream environment with every account in the organization.')
    parser.add_argument(
        "--environment_sub_domain", help="The Stream environment sub domain", required=True)
    parser.add_argument(
        "--environment_user_name", help="The Stream environment user name", default=None)
    parser.add_argument(
        "--environment_password", help="The Stream environment password", default=None)
    parser.add_argument(
        "--environment_f2a_token", help="F2A Token if set", default=None)
    parser.add_argument(
        "--ws_name", help="The WS from which to fetch information", required=True)
    parser.add_argument(
        "--start_time", help="Start date for detections, format: 'YYYY-MM-DD'", required=True)
    parser.add_argument(
        "--end_time", help="End date for detections, format: 'YYYY-MM-DD'", required=True)
    parser.add_argument(
        "--token", help="API token; alternative to user/password login", default=None)
    parser.add_argument(
        "--stage", action="store_true")
    args = parser.parse_args()
    if not args.token and not (args.environment_user_name and args.environment_password):
        parser.error("Must provide either --token or both --environment_user_name and --environment_password")
    main(args.environment_sub_domain, args.environment_user_name, args.environment_password, args.environment_f2a_token,
         args.ws_name, args.start_time, args.end_time, token=args.token, stage=args.stage)

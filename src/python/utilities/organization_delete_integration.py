import argparse
import concurrent.futures
import os
import sys
import time

# Add the project root directory to the Python path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..')))
try:
    from src.python.common.boto_common import *
except ModuleNotFoundError:
    sys.path.append("../../..")
    from src.python.common.boto_common import *

import boto3


class _DeleteIntegrationParser(argparse.ArgumentParser):
    """Parser that rejects mixing lambda-only mode with the stack-only flags,
    regardless of the order the flags appear in."""
    def parse_args(self, args=None, namespace=None):
        ns = super().parse_args(args, namespace)
        if ns.lambda_name_contains and (ns.force_delete_failed or ns.stack_name_contains):
            self.error(
                "--lambda_name_contains cannot be combined with --force_delete_failed "
                "or --stack_name_contains (lambda-only mode does not touch stacks).")
        if ns.lambda_name_contains:
            try:
                validate_lambda_pattern(ns.lambda_name_contains)
            except ValueError as e:
                self.error(str(e))
        return ns


def build_arg_parser():
    parser = _DeleteIntegrationParser(
        description="Delete Stream Security integration from organization accounts. "
                    "Default mode deletes the CloudFormation stacks (which removes the "
                    "integration). Lambda-only mode (--lambda_name_contains) deletes only "
                    "matching Lambda functions and does NOT remove the integration.")
    parser.add_argument(
        "--accounts", help="Account IDs to target, e.g. '111111111111,222222222222' "
        "(default: all ACTIVE org accounts)", required=False)
    parser.add_argument(
        "--regions", help="Regions to target, e.g. 'us-east-1,eu-west-1' "
        "(default: all enabled regions)", required=False)
    parser.add_argument(
        "--aws_profile_name", help="AWS profile with admin permissions on the org account. "
        "Omit to use the default credential chain / SSO.", default=None)
    parser.add_argument(
        "--just_print", action="store_true",
        help="Dry run - list what would be deleted, delete nothing")
    # Stack-only flags (CF mode)
    parser.add_argument(
        "--force_delete_failed", action="store_true",
        help="CF mode only: target DELETE_FAILED stacks with FORCE_DELETE_STACK")
    parser.add_argument(
        "--stack_name_contains",
        help="CF mode only: filter stacks by name (case-insensitive)", required=False)
    # Lambda-only mode
    parser.add_argument(
        "--lambda_name_contains",
        help="LAMBDA-ONLY MODE: delete only Lambda functions whose name contains this "
        "string (case-insensitive, min 3 chars). Does NOT touch CloudFormation stacks and "
        "does NOT remove the Stream Security integration. Mutually exclusive with the "
        "stack-only flags.", required=False)
    return parser


def _session_for_account(sub_account, sts_client, management_account_id):
    """Return a boto3 Session for the account, or raise on assume-role failure.
    The management account uses the current session (no assume-role)."""
    if sub_account[0] == management_account_id:
        return boto3.Session()
    assumed_role = sts_client.assume_role(
        RoleArn=f'arn:aws:iam::{sub_account[0]}:role/OrganizationAccountAccessRole',
        RoleSessionName='MySessionName')
    return boto3.Session(
        aws_access_key_id=assumed_role['Credentials']['AccessKeyId'],
        aws_secret_access_key=assumed_role['Credentials']['SecretAccessKey'],
        aws_session_token=assumed_role['Credentials']['SessionToken'])


def _scan_account_lambdas(sub_account, session, regions, pattern):
    """Scan all regions of one account in parallel; return (to_delete, skipped)
    with account id+name stamped on each result dict."""
    to_delete, skipped = [], []
    if not regions:
        return to_delete, skipped
    # Warm the session's client-creation caches single-threaded; boto3 Session
    # is not thread-safe for concurrent first-time client creation.
    session.client("lambda", region_name=regions[0])
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        future_to_region = {
            executor.submit(scan_lambdas_in_region, session, region, pattern): region
            for region in regions}
        for future in concurrent.futures.as_completed(future_to_region):
            region = future_to_region[future]
            try:
                region_delete, region_skipped = future.result()
            except Exception as e:
                print(color(f"Account: {sub_account[0]} | Failed to scan region "
                            f"{region}: {e}", "red"))
                continue
            for d in region_delete:
                d.update({"account": sub_account[0], "name": sub_account[1]})
                to_delete.append(d)
            for s in region_skipped:
                s.update({"account": sub_account[0], "name": sub_account[1]})
                skipped.append(s)
    return to_delete, skipped


def _run_lambda_mode(sub_accounts, sts_client, management_account_id, regions,
                     pattern, just_print):
    pattern = validate_lambda_pattern(pattern)
    print(color(
        "LAMBDA-ONLY MODE: only Lambda functions will be deleted. CloudFormation "
        "stacks are NOT touched — to remove the Stream Security integration itself, "
        "run without --lambda_name_contains.", "yellow"))

    all_to_delete, all_skipped, assume_role_failures = [], [], []

    # Scan phase
    for sub_account in sub_accounts:
        try:
            session = _session_for_account(sub_account, sts_client, management_account_id)
        except Exception as e:
            print(color(f"Account: {sub_account[0]} | Can't assume role, skipping. "
                        f"Error: {e}", "red"))
            assume_role_failures.append((sub_account[0], sub_account[1], str(e)))
            continue
        print(color(f"Account: {sub_account[0]} | Scanning {len(regions)} regions", "blue"))
        to_delete, skipped = _scan_account_lambdas(sub_account, session, regions, pattern)
        all_to_delete.extend(to_delete)
        all_skipped.extend(skipped)

    # Listing + plan file
    print_lambda_plan(all_to_delete, all_skipped)
    plan_path = os.path.join(
        os.getcwd(), f"lambda_delete_plan_{time.strftime('%Y%m%d-%H%M%S')}.txt")
    if all_to_delete:
        try:
            write_plan_file(all_to_delete, plan_path)
            print(color(f"Full plan written to: {plan_path}", "blue"))
        except Exception as e:
            print(color(f"Could not write plan file to {plan_path}: {e} "
                        "(continuing - the plan above is still valid)", "yellow"))

    def _surface_assume_role_failures():
        return print_lambda_summary([], [], [], all_skipped, assume_role_failures)

    if just_print:
        print(color("Dry run (--just_print) - nothing deleted.", "green"))
        return _surface_assume_role_failures()
    if not all_to_delete:
        print(color("No matching lambda functions found - nothing to delete.", "green"))
        return _surface_assume_role_failures()

    account_count = len({d["account"] for d in all_to_delete})
    if not confirm_deletion(len(all_to_delete), account_count, sys.stdin.isatty, input):
        return _surface_assume_role_failures()

    # Delete phase - re-assume roles fresh (the scan can outlive 1h STS creds)
    deleted, already_gone, failed = [], [], []
    by_account = {}
    for d in all_to_delete:
        by_account.setdefault((d["account"], d["name"]), []).append(d)

    try:
        for (account_id, name), items in by_account.items():
            sub_account = (account_id, name)
            try:
                session = _session_for_account(sub_account, sts_client, management_account_id)
            except Exception as e:
                print(color(f"Account: {account_id} | Can't assume role for delete, "
                            f"skipping. Error: {e}", "red"))
                assume_role_failures.append((account_id, name, str(e)))
                continue
            if not items:
                continue
            # Warm the session's client-creation caches single-threaded; boto3 Session
            # is not thread-safe for concurrent first-time client creation.
            session.client("lambda", region_name=items[0]["region"])
            with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
                future_to_item = {
                    executor.submit(delete_lambda_function, session, it["region"],
                                    it["function"]): it for it in items}
                try:
                    for future in concurrent.futures.as_completed(future_to_item):
                        it = future_to_item[future]
                        try:
                            outcome = future.result()
                            if outcome == "already gone":
                                already_gone.append(it)
                            else:
                                deleted.append(it)
                                print(color(f"Account: {account_id} | Deleted "
                                            f"{it['function']} ({it['region']})", "green"))
                        except Exception as e:
                            it2 = dict(it, reason=str(e)[:200])
                            failed.append(it2)
                            print(color(f"Account: {account_id} | Failed to delete "
                                        f"{it['function']} ({it['region']}): {e}", "red"))
                except KeyboardInterrupt:
                    executor.shutdown(wait=False, cancel_futures=True)
                    raise
    except KeyboardInterrupt:
        print(color("\nInterrupted - stopping. Summary of work done so far:", "yellow"))

    return print_lambda_summary(deleted, already_gone, failed, all_skipped,
                                assume_role_failures)


def _run_cf_mode(sub_accounts, sts_client, management_account_id, regions,
                 just_print, force_delete_failed, stack_name_contains):
    for sub_account in sub_accounts:
        try:
            session = _session_for_account(sub_account, sts_client, management_account_id)
        except Exception as e:
            print(color(f"Account: {sub_account[0]} | Can't assume role, skipping. "
                        f"Error: {e}", "red"))
            continue
        print(color(f"Account: {sub_account[0]} | Session initialized", "green"))
        delete_stacks_in_all_regions(sub_account, session, regions, just_print,
                                     force_delete_failed, stack_name_contains)
    return 0


def main(accounts, aws_profile_name, regions=None, just_print=False,
         force_delete_failed=False, stack_name_contains=None, lambda_name_contains=None):
    # Adaptive retries for every client created below (both modes)
    os.environ["AWS_RETRY_MODE"] = "adaptive"
    os.environ["AWS_MAX_ATTEMPTS"] = "10"

    if aws_profile_name:
        os.environ['AWS_PROFILE'] = aws_profile_name
        print(color(f"Using AWS profile: {aws_profile_name}", "blue"))
    else:
        print(color("No AWS profile specified - using default credential chain", "blue"))

    account_filter = accounts.replace(" ", "").split(",") if accounts else None

    org_client = boto3.client('organizations', region_name='us-east-1')
    sts_client = boto3.client('sts', region_name='us-east-1')

    if regions:
        regions = regions.replace(" ", "").split(",")
    else:
        regions = [r['RegionName'] for r in
                   boto3.client('ec2', region_name='us-east-1').describe_regions()['Regions']]
    print(color(f"Targeting {len(regions)} region(s)", "blue"))

    print("Fetching all accounts connected to the organization")
    list_accounts = get_all_accounts(org_client)
    management_account_id = org_client.describe_organization()['Organization']['MasterAccountId']
    sub_accounts = [(a["Id"], a["Name"]) for a in list_accounts if a["Status"] == "ACTIVE"]
    if account_filter:
        sub_accounts = [sa for sa in sub_accounts if sa[0] in account_filter]
    print(color(f"Accounts to process: {[sa[0] for sa in sub_accounts]}", "blue"))

    if lambda_name_contains:
        return _run_lambda_mode(sub_accounts, sts_client, management_account_id,
                                regions, lambda_name_contains, just_print)
    return _run_cf_mode(sub_accounts, sts_client, management_account_id, regions,
                        just_print, force_delete_failed, stack_name_contains)


if __name__ == "__main__":
    parser = build_arg_parser()
    args = parser.parse_args()
    exit_code = main(
        args.accounts, args.aws_profile_name, regions=args.regions,
        just_print=args.just_print, force_delete_failed=args.force_delete_failed,
        stack_name_contains=args.stack_name_contains,
        lambda_name_contains=args.lambda_name_contains)
    sys.exit(1 if exit_code else 0)

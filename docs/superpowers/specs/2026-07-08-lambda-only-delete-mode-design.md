# Lambda-only delete mode for `organization_delete_integration.py`

**Date:** 2026-07-08 · **Status:** Approved

## Goal

Delete specific Lambda functions (not managed by CloudFormation) matched by a name
string across an AWS Organization (250+ accounts), filterable by accounts and regions,
with a full listing and an explicit confirmation before deleting.

## Approach

Extend `organization_delete_integration.py` with a **lambda-only mode**; keep the current
CloudFormation (CF) stack-deletion as the default mode. The script stays **pure AWS** —
no Stream Security API calls, so no URL/token/ws_id/user-pass args (the unused
`GraphCommon` import is removed). Rationale: CF mode's stack deletion already removes the
integration; lambda-only mode must NOT remove the integration.

## Modes

- **CF mode (default, unchanged):** deletes Stream Security / Lightlytics stacks. Keeps
  `--just_print`, `--force_delete_failed`, `--stack_name_contains`.
- **Lambda-only mode (`--lambda_name_contains <str>`):** deletes only matching Lambda
  functions, never stacks. Prints a banner + help text stating it does NOT remove the
  integration (customers usually need CF mode for that). Mutually exclusive with the
  stack-only flags (errors if combined). Match is case-insensitive substring, min 3 chars.
  Functions tagged `aws:cloudformation:stack-name` are skipped as CFN-managed and reported.

## Shared flags (both modes)

- `--accounts 111,222` (existing) — default all ACTIVE accounts.
- `--regions us-east-1,...` (new) — default all enabled regions.
- `--aws_profile_name` now optional, **no default** (was `"staging"`); omitted = default
  credential chain / SSO, like `update_all_stacks.py`. Management account uses the current
  session instead of assume-role.
- `--just_print` — dry run (scan + list only).

## Lambda-only flow

1. **Scan** each target account (assume `OrganizationAccountAccessRole`; mgmt = current
   session); regions in a thread pool (8 workers). Per region: paginated `ListFunctions`
   → name match → `ListTags` on matches for the CFN check. Collect account/region/name.
2. **List** the plan, designed to stay reviewable at 160+ functions:
   - **Per-account roll-up** — one line per account (`<id> (<name>)  <N> functions`),
     sorted by count descending, so the biggest blast radius is on top.
   - **Grand total** — `Total: N functions across M accounts`.
   - **Full flat table** — `account | region | function` for spot-checking / scrollback.
   - **CFN-skipped** functions listed separately with their owning stack name.
   - **Plan file** — the full flat list is also written to
     `lambda_delete_plan_<timestamp>.txt` and its path printed, so the plan can be
     grepped/diffed/shared and serves as an audit record. `--just_print` writes this
     file and stops here.
3. **Confirm** — exit silently if no matches; else echo the totals
   (`About to delete N functions across M accounts — type 'delete' to proceed`) and
   require typing `delete` exactly.
4. **Delete** — re-assume roles fresh per account (scan can outlive 1h STS creds),
   `DeleteFunction` per match. Already-gone functions = `already gone`, not a failure.

## Error handling & scale

- Boto `Config(retries={'max_attempts':10,'mode':'adaptive'}, connect_timeout=15,
  read_timeout=60)`.
- Every failure recorded and skipped past; colored errors with account/region context.
- **End-of-run summary** (`update_all_stacks.py` style): counts of
  `deleted | failed | skipped-CFN | already-gone`, per-item detail for failures, and an
  explicit list of **every account where assume-role failed** (ID, name, error) for easy
  `--accounts` re-run. Exit code 1 on any failure.

## Terminal safety

- **Non-TTY guard:** if `sys.stdin.isatty()` is false, refuse to delete (message + exit),
  don't hang on `input()`.
- **Prompt:** `EOFError`/`KeyboardInterrupt` = abort, delete nothing.
- **Ctrl+C mid-run:** catch, `shutdown(cancel_futures=True)`, print summary of what was
  already done, exit.

## Testing

`--just_print` on a small `--accounts` set; real delete of a throwaway lambda; verify a
CFN-created match is skipped; verify mode-mixing flags error; verify non-TTY refuses
instead of hanging; CF-mode regression with the new region filter + optional profile.

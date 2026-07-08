# Lambda-only delete mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a lambda-only mode to `organization_delete_integration.py` that deletes specific Lambda functions (not CloudFormation-managed) by name across a 250+ account AWS Organization, filterable by account/region, with a reviewable plan listing and an explicit typed confirmation before deleting.

**Architecture:** Pure, unit-testable helper functions (matching, validation, roll-up/plan formatting, confirmation) plus two boto-touching helpers (scan, delete) live in `src/python/common/boto_common.py`, mirroring the existing stack-deletion helpers there. `organization_delete_integration.py` gains argument parsing, mode dispatch, and the scan → list → confirm → delete orchestration. The script stays pure AWS — no Stream Security API calls.

**Tech Stack:** Python 3, boto3/botocore (`lambda`, `sts`, `organizations`, `ec2` clients), termcolor for output, stdlib `unittest` + `unittest.mock` for tests (no new dependencies), `concurrent.futures.ThreadPoolExecutor` for per-account region parallelism.

## Global Constraints

- **No new dependencies.** Tests use stdlib `unittest`/`unittest.mock` only; runtime adds nothing to `requirements.txt`.
- **Pure AWS.** No Stream Security / GraphCommon calls anywhere in the delete script. Remove the unused `GraphCommon` import.
- **House style:** `from termcolor import colored as color` for output; account context in every message as `Account: <id> | ...` (match existing script/`boto_common.py`).
- **Case-insensitive substring** matching for lambda names; reject patterns shorter than **3 characters**.
- **CFN protection:** any function whose tags include `aws:cloudformation:stack-name` is never deleted in lambda mode.
- **Adaptive retries** for both modes: set `AWS_RETRY_MODE=adaptive` and `AWS_MAX_ATTEMPTS=10` at startup; lambda clients additionally use `Config(connect_timeout=15, read_timeout=60)`.
- **Confirmation word** is the literal string `delete`.
- **Branch:** all work on `feature/lambda-only-delete-mode`. Never commit to `master`.
- Run tests with: `python -m unittest discover -s tests -v` from repo root.

---

### Task 1: Matching + validation helpers

**Files:**
- Modify: `src/python/common/boto_common.py` (add constants + 3 pure functions near the existing stack helpers)
- Test: `tests/test_lambda_delete_helpers.py` (new)

**Interfaces:**
- Consumes: nothing (pure stdlib).
- Produces:
  - `CFN_STACK_NAME_TAG = "aws:cloudformation:stack-name"` (module constant)
  - `LAMBDA_MIN_PATTERN_LEN = 3` (module constant)
  - `validate_lambda_pattern(pattern: str | None) -> str` — returns the stripped pattern, raises `ValueError` if `None`/blank/shorter than 3 chars after strip.
  - `lambda_name_matches(function_name: str, pattern: str) -> bool` — case-insensitive substring.
  - `is_cfn_managed(tags: dict | None) -> bool` — True iff `CFN_STACK_NAME_TAG` is a key.

- [ ] **Step 1: Write the failing test**

Create `tests/test_lambda_delete_helpers.py`:

```python
import os
import sys
import unittest

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from src.python.common.boto_common import (
    validate_lambda_pattern,
    lambda_name_matches,
    is_cfn_managed,
    CFN_STACK_NAME_TAG,
)


class TestValidateLambdaPattern(unittest.TestCase):
    def test_valid_pattern_returned_stripped(self):
        self.assertEqual(validate_lambda_pattern("  StreamSec  "), "StreamSec")

    def test_none_raises(self):
        with self.assertRaises(ValueError):
            validate_lambda_pattern(None)

    def test_too_short_raises(self):
        with self.assertRaises(ValueError):
            validate_lambda_pattern("ab")

    def test_blank_raises(self):
        with self.assertRaises(ValueError):
            validate_lambda_pattern("   ")


class TestLambdaNameMatches(unittest.TestCase):
    def test_case_insensitive_substring(self):
        self.assertTrue(lambda_name_matches("StreamSec_Collector", "streamsec"))

    def test_no_match(self):
        self.assertFalse(lambda_name_matches("my-prod-fn", "streamsec"))


class TestIsCfnManaged(unittest.TestCase):
    def test_true_when_tag_present(self):
        self.assertTrue(is_cfn_managed({CFN_STACK_NAME_TAG: "LightlyticsStack-abc"}))

    def test_false_when_absent(self):
        self.assertFalse(is_cfn_managed({"env": "prod"}))

    def test_false_when_none(self):
        self.assertFalse(is_cfn_managed(None))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_lambda_delete_helpers -v`
Expected: FAIL with `ImportError: cannot import name 'validate_lambda_pattern'`

- [ ] **Step 3: Write minimal implementation**

Append to `src/python/common/boto_common.py` (after the existing `delete_stack`/`filter_ll_stacks_from_url` helpers):

```python
CFN_STACK_NAME_TAG = "aws:cloudformation:stack-name"
LAMBDA_MIN_PATTERN_LEN = 3


def validate_lambda_pattern(pattern):
    """Return the stripped pattern, or raise ValueError if it is missing or
    shorter than LAMBDA_MIN_PATTERN_LEN characters (guards against a typo like
    's' matching hundreds of functions)."""
    if pattern is None or len(pattern.strip()) < LAMBDA_MIN_PATTERN_LEN:
        raise ValueError(
            f"--lambda_name_contains must be at least {LAMBDA_MIN_PATTERN_LEN} characters")
    return pattern.strip()


def lambda_name_matches(function_name, pattern):
    """Case-insensitive substring match of pattern within function_name."""
    return pattern.lower() in function_name.lower()


def is_cfn_managed(tags):
    """True if the Lambda's tags mark it as CloudFormation-managed."""
    return CFN_STACK_NAME_TAG in (tags or {})
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_lambda_delete_helpers -v`
Expected: PASS (9 tests)

- [ ] **Step 5: Commit**

```bash
git add src/python/common/boto_common.py tests/test_lambda_delete_helpers.py
git commit -m "Add lambda name matching, pattern validation, and CFN-managed helpers"
```

---

### Task 2: Roll-up + plan-line formatting helpers

**Files:**
- Modify: `src/python/common/boto_common.py`
- Test: `tests/test_lambda_delete_helpers.py` (add a test class)

**Interfaces:**
- Consumes: nothing (pure).
- Produces (result dicts have keys `account`, `name`, `region`, `function`):
  - `build_account_rollup(results: list[dict]) -> list[tuple[str, str, int]]` — `(account_id, account_name, count)` sorted by count desc, then account id asc.
  - `format_plan_lines(results: list[dict]) -> list[str]` — `"<account> | <region> | <function>"` sorted by (account, region, function).

- [ ] **Step 1: Write the failing test**

Add to `tests/test_lambda_delete_helpers.py` (before the `if __name__` block):

```python
from src.python.common.boto_common import build_account_rollup, format_plan_lines


class TestBuildAccountRollup(unittest.TestCase):
    def _results(self):
        return [
            {"account": "111", "name": "acme-prod", "region": "us-east-1", "function": "a"},
            {"account": "111", "name": "acme-prod", "region": "us-east-1", "function": "b"},
            {"account": "222", "name": "acme-dev", "region": "eu-west-1", "function": "c"},
        ]

    def test_counts_and_sort_desc(self):
        rollup = build_account_rollup(self._results())
        self.assertEqual(rollup[0], ("111", "acme-prod", 2))
        self.assertEqual(rollup[1], ("222", "acme-dev", 1))

    def test_empty(self):
        self.assertEqual(build_account_rollup([]), [])


class TestFormatPlanLines(unittest.TestCase):
    def test_sorted_lines(self):
        results = [
            {"account": "222", "name": "d", "region": "us-east-1", "function": "z"},
            {"account": "111", "name": "p", "region": "us-east-1", "function": "a"},
        ]
        lines = format_plan_lines(results)
        self.assertEqual(lines[0], "111 | us-east-1 | a")
        self.assertEqual(lines[1], "222 | us-east-1 | z")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_lambda_delete_helpers -v`
Expected: FAIL with `ImportError: cannot import name 'build_account_rollup'`

- [ ] **Step 3: Write minimal implementation**

Append to `src/python/common/boto_common.py`:

```python
def build_account_rollup(results):
    """Group delete-plan results by account into (account_id, account_name, count)
    tuples, sorted by count descending then account id, so the accounts losing the
    most functions appear first."""
    counts = {}
    names = {}
    for r in results:
        counts[r["account"]] = counts.get(r["account"], 0) + 1
        names[r["account"]] = r.get("name", "")
    rollup = [(acc, names[acc], cnt) for acc, cnt in counts.items()]
    rollup.sort(key=lambda t: (-t[2], t[0]))
    return rollup


def format_plan_lines(results):
    """One 'account | region | function' line per result, sorted for stable output
    and easy diffing/grepping of the written plan file."""
    return [f"{r['account']} | {r['region']} | {r['function']}"
            for r in sorted(results, key=lambda r: (r["account"], r["region"], r["function"]))]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_lambda_delete_helpers -v`
Expected: PASS (13 tests)

- [ ] **Step 5: Commit**

```bash
git add src/python/common/boto_common.py tests/test_lambda_delete_helpers.py
git commit -m "Add account roll-up and plan-line formatting helpers for lambda delete"
```

---

### Task 3: Boto-touching scan + delete helpers

**Files:**
- Modify: `src/python/common/boto_common.py`
- Test: `tests/test_lambda_delete_boto.py` (new)

**Interfaces:**
- Consumes: `lambda_name_matches`, `is_cfn_managed`, `CFN_STACK_NAME_TAG` (Task 1).
- Produces:
  - `LAMBDA_CLIENT_CONFIG` — a `botocore.config.Config(connect_timeout=15, read_timeout=60, retries={'max_attempts': 10, 'mode': 'adaptive'})`.
  - `scan_lambdas_in_region(session, region, pattern) -> tuple[list[dict], list[dict]]` — returns `(to_delete, skipped_cfn)`. `to_delete` items: `{"region", "function"}`. `skipped_cfn` items: `{"region", "function", "stack"}`. Uses the `list_functions` paginator, calls `list_tags` only on name-matched functions.
  - `delete_lambda_function(session, region, function_name) -> str` — returns `"deleted"`, or `"already gone"` if the function is missing (`ResourceNotFoundException`). Other exceptions propagate.

- [ ] **Step 1: Write the failing test**

Create `tests/test_lambda_delete_boto.py`:

```python
import os
import sys
import unittest
from unittest.mock import MagicMock

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from src.python.common.boto_common import (
    scan_lambdas_in_region,
    delete_lambda_function,
    CFN_STACK_NAME_TAG,
)


def _session_with_lambda(client):
    session = MagicMock()
    session.client.return_value = client
    return session


class TestScanLambdasInRegion(unittest.TestCase):
    def test_splits_matches_and_cfn_managed(self):
        client = MagicMock()
        paginator = MagicMock()
        paginator.paginate.return_value = [{
            "Functions": [
                {"FunctionName": "StreamSec_A", "FunctionArn": "arn:A"},
                {"FunctionName": "StreamSec_B", "FunctionArn": "arn:B"},
                {"FunctionName": "unrelated",   "FunctionArn": "arn:C"},
            ]
        }]
        client.get_paginator.return_value = paginator
        client.list_tags.side_effect = lambda Resource: (
            {"Tags": {CFN_STACK_NAME_TAG: "LightlyticsStack-x"}} if Resource == "arn:B"
            else {"Tags": {}}
        )
        session = _session_with_lambda(client)

        to_delete, skipped = scan_lambdas_in_region(session, "us-east-1", "streamsec")

        self.assertEqual([d["function"] for d in to_delete], ["StreamSec_A"])
        self.assertEqual(len(skipped), 1)
        self.assertEqual(skipped[0]["function"], "StreamSec_B")
        self.assertEqual(skipped[0]["stack"], "LightlyticsStack-x")
        # list_tags must be called only for name-matched functions (A and B), not C
        self.assertEqual(client.list_tags.call_count, 2)


class TestDeleteLambdaFunction(unittest.TestCase):
    def test_deleted(self):
        client = MagicMock()
        client.exceptions.ResourceNotFoundException = type(
            "ResourceNotFoundException", (Exception,), {})
        session = _session_with_lambda(client)
        self.assertEqual(delete_lambda_function(session, "us-east-1", "fn"), "deleted")

    def test_already_gone(self):
        client = MagicMock()
        not_found = type("ResourceNotFoundException", (Exception,), {})
        client.exceptions.ResourceNotFoundException = not_found
        client.delete_function.side_effect = not_found()
        session = _session_with_lambda(client)
        self.assertEqual(delete_lambda_function(session, "us-east-1", "fn"), "already gone")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_lambda_delete_boto -v`
Expected: FAIL with `ImportError: cannot import name 'scan_lambdas_in_region'`

- [ ] **Step 3: Write minimal implementation**

Add near the top imports of `src/python/common/boto_common.py` (the file already imports `concurrent.futures`, `datetime`, `time`, `os`, and `color`):

```python
from botocore.config import Config
```

Append to `src/python/common/boto_common.py`:

```python
LAMBDA_CLIENT_CONFIG = Config(
    connect_timeout=15,
    read_timeout=60,
    retries={"max_attempts": 10, "mode": "adaptive"},
)


def scan_lambdas_in_region(sub_account_session, region, pattern):
    """List Lambda functions in a region, keep those whose name matches pattern,
    and split them into (to_delete, skipped_cfn). A function tagged as
    CloudFormation-managed goes to skipped_cfn with its owning stack name; it is
    never deleted. list_tags is called only for name-matched functions."""
    client = sub_account_session.client("lambda", region_name=region, config=LAMBDA_CLIENT_CONFIG)
    to_delete, skipped_cfn = [], []
    for page in client.get_paginator("list_functions").paginate():
        for fn in page["Functions"]:
            name = fn["FunctionName"]
            if not lambda_name_matches(name, pattern):
                continue
            tags = client.list_tags(Resource=fn["FunctionArn"]).get("Tags", {})
            if is_cfn_managed(tags):
                skipped_cfn.append(
                    {"region": region, "function": name, "stack": tags[CFN_STACK_NAME_TAG]})
            else:
                to_delete.append({"region": region, "function": name})
    return to_delete, skipped_cfn


def delete_lambda_function(sub_account_session, region, function_name):
    """Delete a Lambda function. Returns 'deleted', or 'already gone' if it was
    already removed between the scan and now. Other errors propagate to the caller."""
    client = sub_account_session.client("lambda", region_name=region, config=LAMBDA_CLIENT_CONFIG)
    try:
        client.delete_function(FunctionName=function_name)
        return "deleted"
    except client.exceptions.ResourceNotFoundException:
        return "already gone"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_lambda_delete_boto -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add src/python/common/boto_common.py tests/test_lambda_delete_boto.py
git commit -m "Add region-scoped lambda scan and delete helpers with adaptive retry config"
```

---

### Task 4: Confirmation prompt with TTY guard

**Files:**
- Modify: `src/python/common/boto_common.py`
- Test: `tests/test_lambda_delete_confirm.py` (new)

**Interfaces:**
- Consumes: nothing (uses injected `input`/`isatty` for testability).
- Produces:
  - `confirm_deletion(total, account_count, isatty_fn, input_fn) -> bool` — returns True only when stdin is a TTY (`isatty_fn()` True) and the user types exactly `delete`. Returns False (no exception) on non-TTY, wrong word, `EOFError`, or `KeyboardInterrupt`. Prints a clear reason on refusal via `color`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_lambda_delete_confirm.py`:

```python
import os
import sys
import unittest

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from src.python.common.boto_common import confirm_deletion


class TestConfirmDeletion(unittest.TestCase):
    def test_typed_delete_on_tty_confirms(self):
        self.assertTrue(confirm_deletion(5, 2, lambda: True, lambda _p: "delete"))

    def test_wrong_word_aborts(self):
        self.assertFalse(confirm_deletion(5, 2, lambda: True, lambda _p: "yes"))

    def test_non_tty_refuses_without_prompting(self):
        def _input(_p):
            raise AssertionError("input must not be called on a non-tty")
        self.assertFalse(confirm_deletion(5, 2, lambda: False, _input))

    def test_eof_aborts(self):
        def _input(_p):
            raise EOFError()
        self.assertFalse(confirm_deletion(5, 2, lambda: True, _input))

    def test_keyboard_interrupt_aborts(self):
        def _input(_p):
            raise KeyboardInterrupt()
        self.assertFalse(confirm_deletion(5, 2, lambda: True, _input))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_lambda_delete_confirm -v`
Expected: FAIL with `ImportError: cannot import name 'confirm_deletion'`

- [ ] **Step 3: Write minimal implementation**

Append to `src/python/common/boto_common.py`:

```python
def confirm_deletion(total, account_count, isatty_fn, input_fn):
    """Interactive safety gate. Returns True only on an interactive terminal when
    the operator types exactly 'delete'. On a non-TTY (nohup/pipe/CI) it refuses
    instead of blocking forever on input(); EOF/Ctrl+C also abort. isatty_fn and
    input_fn are injected so this is unit-testable."""
    if not isatty_fn():
        print(color(
            "No interactive terminal detected — refusing to delete. "
            "Run interactively, or use --just_print to preview.", "red"))
        return False
    try:
        answer = input_fn(
            f"About to delete {total} lambda functions across {account_count} accounts. "
            f"Type 'delete' to proceed: ")
    except (EOFError, KeyboardInterrupt):
        print(color("\nAborted — nothing was deleted.", "yellow"))
        return False
    if answer.strip() == "delete":
        return True
    print(color("Confirmation did not match 'delete' — nothing was deleted.", "yellow"))
    return False
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_lambda_delete_confirm -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add src/python/common/boto_common.py tests/test_lambda_delete_confirm.py
git commit -m "Add confirm_deletion gate with non-TTY guard and EOF/Ctrl+C handling"
```

---

### Task 5: Plan listing + end-of-run summary printers

**Files:**
- Modify: `src/python/common/boto_common.py`
- Test: `tests/test_lambda_delete_report.py` (new)

**Interfaces:**
- Consumes: `build_account_rollup`, `format_plan_lines` (Task 2).
- Produces:
  - `write_plan_file(results, path) -> None` — writes one `format_plan_lines` entry per line to `path`.
  - `print_lambda_plan(results, skipped_cfn) -> None` — prints the per-account roll-up, grand total, full flat table, and the CFN-skipped section. Safe with empty inputs.
  - `print_lambda_summary(deleted, already_gone, failed, skipped_cfn, assume_role_failures) -> int` — prints counts, per-item failure detail, and an explicit list of accounts where assume-role failed (`(id, name, error)` tuples). Returns `len(failed) + len(assume_role_failures)` to drive the exit code.

- [ ] **Step 1: Write the failing test**

Create `tests/test_lambda_delete_report.py`:

```python
import os
import sys
import tempfile
import unittest

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from src.python.common.boto_common import (
    write_plan_file,
    print_lambda_plan,
    print_lambda_summary,
)


class TestWritePlanFile(unittest.TestCase):
    def test_writes_sorted_lines(self):
        results = [
            {"account": "222", "name": "d", "region": "us-east-1", "function": "z"},
            {"account": "111", "name": "p", "region": "us-east-1", "function": "a"},
        ]
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "plan.txt")
            write_plan_file(results, path)
            with open(path) as f:
                lines = f.read().splitlines()
        self.assertEqual(lines, ["111 | us-east-1 | a", "222 | us-east-1 | z"])


class TestPrintSummaryExitCount(unittest.TestCase):
    def test_returns_failure_plus_assume_role_count(self):
        code = print_lambda_summary(
            deleted=[{"account": "1"}],
            already_gone=[],
            failed=[{"account": "2", "region": "us-east-1", "function": "f", "reason": "boom"}],
            skipped_cfn=[{"account": "3", "function": "g", "stack": "s"}],
            assume_role_failures=[("9", "acc9", "denied")],
        )
        self.assertEqual(code, 2)

    def test_clean_run_returns_zero(self):
        code = print_lambda_summary([{"account": "1"}], [], [], [], [])
        self.assertEqual(code, 0)


class TestPrintPlanEmptySafe(unittest.TestCase):
    def test_no_crash_on_empty(self):
        print_lambda_plan([], [])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_lambda_delete_report -v`
Expected: FAIL with `ImportError: cannot import name 'write_plan_file'`

- [ ] **Step 3: Write minimal implementation**

Append to `src/python/common/boto_common.py`:

```python
def write_plan_file(results, path):
    """Write the full delete plan (one 'account | region | function' per line) to
    path so it can be grepped, diffed, shared, and kept as an audit record."""
    with open(path, "w") as f:
        f.write("\n".join(format_plan_lines(results)) + "\n")


def print_lambda_plan(results, skipped_cfn):
    """Print the delete plan: a per-account roll-up (biggest blast radius first),
    the grand total, the full flat table, and the CFN-managed functions skipped."""
    rollup = build_account_rollup(results)
    print(color("Lambda functions to delete (per account):", "blue"))
    for account_id, name, count in rollup:
        print(f"  {account_id} ({name})  {count} functions")
    print(color(
        f"Total: {len(results)} functions across {len(rollup)} accounts", "blue"))
    if results:
        print(color("Full list:", "blue"))
        for line in format_plan_lines(results):
            print(f"  {line}")
    if skipped_cfn:
        print(color(
            f"Skipped {len(skipped_cfn)} CloudFormation-managed function(s) "
            f"(not deleted):", "yellow"))
        for s in sorted(skipped_cfn, key=lambda x: (x["account"], x["region"], x["function"])):
            print(f"  {s['account']} | {s['region']} | {s['function']} "
                  f"(stack: {s['stack']})")


def print_lambda_summary(deleted, already_gone, failed, skipped_cfn, assume_role_failures):
    """Print end-of-run counts with per-item detail for failures and an explicit
    list of accounts where assume-role failed (copy them into --accounts for a
    re-run). Returns the number of items needing attention, for the exit code."""
    print(color("=" * 60, "blue"))
    print(color(
        f"Run summary: {len(deleted)} deleted | {len(already_gone)} already gone | "
        f"{len(failed)} failed | {len(skipped_cfn)} skipped (CFN-managed) | "
        f"{len(assume_role_failures)} accounts unreachable (assume-role failed)", "blue"))
    for r in failed:
        print(color(
            f"  FAILED | account {r['account']} | {r['region']} | {r['function']} | "
            f"{r['reason']}", "red"))
    for account_id, name, err in assume_role_failures:
        print(color(
            f"  ASSUME-ROLE FAILED | account {account_id} ({name}) | {err}", "red"))
    return len(failed) + len(assume_role_failures)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m unittest tests.test_lambda_delete_report -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add src/python/common/boto_common.py tests/test_lambda_delete_report.py
git commit -m "Add lambda delete plan listing, plan-file writer, and run summary"
```

---

### Task 6: Wire the mode into `organization_delete_integration.py`

**Files:**
- Modify: `src/python/utilities/organization_delete_integration.py` (full rewrite of `main` + arg parsing; remove unused `GraphCommon` import)
- Test: `tests/test_delete_integration_cli.py` (new — CLI-level smoke, no AWS calls)

**Interfaces:**
- Consumes: everything from Tasks 1–5 (imported via `from src.python.common.boto_common import *`), plus existing `get_all_accounts`, `delete_stacks_in_all_regions`.
- Produces: a `build_arg_parser()` function (so argument wiring is unit-testable) and a `main(...)` orchestration. `build_arg_parser` enforces that `--lambda_name_contains` is mutually exclusive with `--force_delete_failed`/`--stack_name_contains`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_delete_integration_cli.py`:

```python
import os
import sys
import unittest

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from src.python.utilities.organization_delete_integration import build_arg_parser


class TestArgParser(unittest.TestCase):
    def test_lambda_mode_parses(self):
        args = build_arg_parser().parse_args(
            ["--lambda_name_contains", "StreamSec"])
        self.assertEqual(args.lambda_name_contains, "StreamSec")

    def test_regions_and_accounts_parse(self):
        args = build_arg_parser().parse_args(
            ["--accounts", "111,222", "--regions", "us-east-1,eu-west-1"])
        self.assertEqual(args.accounts, "111,222")
        self.assertEqual(args.regions, "us-east-1,eu-west-1")

    def test_profile_defaults_to_none(self):
        args = build_arg_parser().parse_args([])
        self.assertIsNone(args.aws_profile_name)

    def test_lambda_mode_conflicts_with_stack_flags(self):
        parser = build_arg_parser()
        with self.assertRaises(SystemExit):
            parser.parse_args(
                ["--lambda_name_contains", "StreamSec", "--stack_name_contains", "Light"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_delete_integration_cli -v`
Expected: FAIL with `ImportError: cannot import name 'build_arg_parser'`

- [ ] **Step 3: Write minimal implementation**

Replace the entire contents of `src/python/utilities/organization_delete_integration.py` with:

```python
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
        write_plan_file(all_to_delete, plan_path)
        print(color(f"Full plan written to: {plan_path}", "blue"))

    if just_print:
        print(color("Dry run (--just_print) - nothing deleted.", "green"))
        return 0
    if not all_to_delete:
        print(color("No matching lambda functions found - nothing to delete.", "green"))
        return 0

    account_count = len({d["account"] for d in all_to_delete})
    if not confirm_deletion(len(all_to_delete), account_count, sys.stdin.isatty, input):
        return 0

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
            with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
                future_to_item = {
                    executor.submit(delete_lambda_function, session, it["region"],
                                    it["function"]): it for it in items}
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
```

The mutual-exclusion check lives in `_DeleteIntegrationParser.parse_args`, so it fires regardless of flag order (the CLI test passes `--lambda_name_contains` before `--stack_name_contains`).

- [ ] **Step 4: Run the CLI test to verify it passes**

Run: `python -m unittest tests.test_delete_integration_cli -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Verify `--help` renders and the banner text is present**

Run: `python src/python/utilities/organization_delete_integration.py --help`
Expected: help text shows `--regions`, `--lambda_name_contains` with the "does NOT remove the Stream Security integration" wording, and `--aws_profile_name` with no default.

- [ ] **Step 6: Run the full test suite**

Run: `python -m unittest discover -s tests -v`
Expected: PASS (all tests from Tasks 1-6).

- [ ] **Step 7: Commit**

```bash
git add src/python/utilities/organization_delete_integration.py tests/test_delete_integration_cli.py
git commit -m "Wire lambda-only mode into organization_delete_integration with region filter and optional profile"
```

---

### Task 7: End-to-end dry-run verification against a real org

**Files:** none (verification only)

**Interfaces:** none.

This task uses real AWS credentials (SSO or a profile) and must be run by someone with org access. It confirms the wiring works against real APIs without deleting anything.

- [ ] **Step 1: Lambda-mode dry run on a small account set**

Run (substitute a real account id and an SSO login / profile):
```bash
python src/python/utilities/organization_delete_integration.py \
  --accounts <one-account-id> --regions us-east-1 \
  --lambda_name_contains StreamSec --just_print
```
Expected: the LAMBDA-ONLY banner, per-account roll-up, `Total: N functions...`, full list, a `lambda_delete_plan_<ts>.txt` path, and `Dry run (--just_print) - nothing deleted.` No delete occurs.

- [ ] **Step 2: Inspect the plan file**

Run: `cat lambda_delete_plan_*.txt`
Expected: one `account | region | function` line per listed function, matching the on-screen list.

- [ ] **Step 3: Confirm CFN-managed exclusion (if any CFN lambdas match)**

Review the "Skipped ... CloudFormation-managed" section. If a known stack-created function matching the pattern is absent from the delete list and present in the skipped list, exclusion works. If no CFN lambda matches the pattern, note this step as not-applicable.

- [ ] **Step 4: CF-mode regression dry run**

Run:
```bash
python src/python/utilities/organization_delete_integration.py \
  --accounts <one-account-id> --regions us-east-1 --just_print
```
Expected: existing stack-listing behavior, honoring the new `--regions` filter, nothing deleted.

- [ ] **Step 5: Non-TTY guard check**

Run: `echo "" | python src/python/utilities/organization_delete_integration.py --accounts <one-account-id> --regions us-east-1 --lambda_name_contains StreamSec`
Expected: scan runs, then `No interactive terminal detected — refusing to delete.` and a non-zero exit — no hang, no deletion.

- [ ] **Step 6: Clean up plan files if undesired**

Run: `rm -f lambda_delete_plan_*.txt` (only if you don't want to keep the dry-run artifacts).

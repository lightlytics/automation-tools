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

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
from src.python.common.boto_common import build_account_rollup, format_plan_lines


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


if __name__ == "__main__":
    unittest.main()

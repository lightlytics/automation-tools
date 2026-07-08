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

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

    def test_lambda_pattern_too_short_rejected_at_parse_time(self):
        parser = build_arg_parser()
        with self.assertRaises(SystemExit):
            parser.parse_args(["--lambda_name_contains", "ab"])


if __name__ == "__main__":
    unittest.main()

import os
import sys
import unittest
from unittest.mock import patch

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from src.python.utilities import organization_delete_integration as mod


class TestLambdaScanErrorsAffectExit(unittest.TestCase):
    def test_scan_gap_causes_nonzero_exit_even_on_just_print(self):
        accounts = [("111", "acct-a")]

        def fake_scan(sub_account, session, regions, pattern):
            # No deletable functions, but one region/function couldn't be scanned.
            return [], [], [{"account": "111", "name": "acct-a", "region": "us-east-1",
                             "function": "f", "reason": "could not read tags"}]

        with patch.object(mod, "_session_for_account", return_value=object()), \
                patch.object(mod, "_scan_account_lambdas", side_effect=fake_scan):
            rc = mod._run_lambda_mode(accounts, sts_client=None, management_account_id="999",
                                      regions=["us-east-1"], pattern="stream", just_print=True)

        self.assertEqual(rc, 1)   # scan gap surfaced -> non-zero, not a silent success

    def test_clean_scan_returns_zero(self):
        accounts = [("111", "acct-a")]

        def fake_scan(sub_account, session, regions, pattern):
            return [], [], []

        with patch.object(mod, "_session_for_account", return_value=object()), \
                patch.object(mod, "_scan_account_lambdas", side_effect=fake_scan):
            rc = mod._run_lambda_mode(accounts, sts_client=None, management_account_id="999",
                                      regions=["us-east-1"], pattern="stream", just_print=True)

        self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()

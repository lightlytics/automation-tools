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

    def test_non_tty_refusal_with_pending_work_exits_nonzero(self):
        accounts = [("111", "acct-a")]

        def fake_scan(sub_account, session, regions, pattern):
            # A clean scan (no gaps) that DID find a function to delete.
            return ([{"account": "111", "name": "acct-a", "region": "us-east-1",
                      "function": "target"}], [], [])

        with patch.object(mod, "_session_for_account", return_value=object()), \
                patch.object(mod, "_scan_account_lambdas", side_effect=fake_scan), \
                patch.object(mod.sys.stdin, "isatty", return_value=False):
            # just_print=False so it reaches confirm_deletion, which refuses on the
            # non-TTY stdin — the run must NOT report success.
            rc = mod._run_lambda_mode(accounts, sts_client=None, management_account_id="999",
                                      regions=["us-east-1"], pattern="stream", just_print=False)

        self.assertGreaterEqual(rc, 1)

    def test_account_scan_crash_is_recorded_not_fatal(self):
        accounts = [("111", "acct-a"), ("222", "acct-b")]

        def fake_scan(sub_account, session, regions, pattern):
            if sub_account[0] == "111":
                raise RuntimeError("boom")   # one account blows up mid-scan
            return [], [], []

        with patch.object(mod, "_session_for_account", return_value=object()), \
                patch.object(mod, "_scan_account_lambdas", side_effect=fake_scan):
            # Must not raise; the crashing account becomes a scan gap (exit non-zero),
            # the other account is still scanned.
            rc = mod._run_lambda_mode(accounts, sts_client=None, management_account_id="999",
                                      regions=["us-east-1"], pattern="stream", just_print=True)

        self.assertGreaterEqual(rc, 1)


if __name__ == "__main__":
    unittest.main()

import os
import sys
import unittest
from unittest.mock import patch

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from src.python.utilities import organization_delete_integration as mod


class TestCfModeExitCode(unittest.TestCase):
    def test_unreachable_account_reported_but_does_not_fail_exit(self):
        accounts = [("111", "acct-a"), ("222", "acct-b")]

        def fake_session(sub_account, sts_client, mgmt):
            if sub_account[0] == "222":
                raise Exception("access denied")
            return object()

        with patch.object(mod, "_session_for_account", side_effect=fake_session), \
                patch.object(mod, "delete_stacks_in_all_regions") as del_stacks:
            rc = mod._run_cf_mode(accounts, sts_client=None, management_account_id="111",
                                  regions=["us-east-1"], just_print=True,
                                  force_delete_failed=False, stack_name_contains=None)

        # An unreachable account is a reported gap, not an operation failure, so it
        # does not flip the exit code; the reachable account is still processed.
        self.assertEqual(rc, 0)
        self.assertEqual(del_stacks.call_count, 1)

    def test_clean_run_returns_zero(self):
        accounts = [("111", "acct-a")]
        with patch.object(mod, "_session_for_account", return_value=object()), \
                patch.object(mod, "delete_stacks_in_all_regions"):
            rc = mod._run_cf_mode(accounts, None, "999", ["us-east-1"], True, False, None)
        self.assertEqual(rc, 0)


class TestAccountFilterValidation(unittest.TestCase):
    def _patches(self):
        # Org has one ACTIVE account, 111; describe_organization/get_all_accounts mocked.
        org = mock_org = __import__("unittest").mock.MagicMock()
        org.describe_organization.return_value = {"Organization": {"MasterAccountId": "111"}}
        return org

    def test_all_unknown_accounts_exits_nonzero_without_running_a_mode(self):
        org = self._patches()
        with patch.object(mod.boto3, "client", return_value=org), \
                patch.object(mod, "get_all_accounts",
                             return_value=[{"Id": "111", "Name": "a", "Status": "ACTIVE"}]), \
                patch.object(mod, "_run_lambda_mode") as run_lambda, \
                patch.object(mod, "_run_cf_mode") as run_cf:
            rc = mod.main(accounts="999999999999", aws_profile_name=None,
                          regions="us-east-1", just_print=True,
                          lambda_name_contains="streamsec")
        self.assertEqual(rc, 1)                 # no valid target -> non-zero
        run_lambda.assert_not_called()          # and neither mode is entered
        run_cf.assert_not_called()


if __name__ == "__main__":
    unittest.main()

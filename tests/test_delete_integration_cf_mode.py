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


if __name__ == "__main__":
    unittest.main()

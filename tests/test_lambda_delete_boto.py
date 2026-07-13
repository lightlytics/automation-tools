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

        to_delete, skipped, scan_errors = scan_lambdas_in_region(session, "us-east-1", "streamsec")

        self.assertEqual([d["function"] for d in to_delete], ["StreamSec_A"])
        self.assertEqual(len(skipped), 1)
        self.assertEqual(skipped[0]["function"], "StreamSec_B")
        self.assertEqual(skipped[0]["stack"], "LightlyticsStack-x")
        self.assertEqual(scan_errors, [])
        # list_tags must be called only for name-matched functions (A and B), not C
        self.assertEqual(client.list_tags.call_count, 2)

    def test_tag_failure_excludes_function_and_records_error(self):
        client = MagicMock()
        paginator = MagicMock()
        paginator.paginate.return_value = [{
            "Functions": [
                {"FunctionName": "StreamSec_ok", "FunctionArn": "arn:ok"},
                {"FunctionName": "StreamSec_bad", "FunctionArn": "arn:bad"},
            ]
        }]
        client.get_paginator.return_value = paginator

        def _tags(Resource):
            if Resource == "arn:bad":
                raise Exception("AccessDenied on ListTags")
            return {"Tags": {}}
        client.list_tags.side_effect = _tags
        session = _session_with_lambda(client)

        to_delete, skipped, scan_errors = scan_lambdas_in_region(session, "us-east-1", "streamsec")

        # A tag failure must NOT abort the region: the good function is still found,
        # the bad one is left out of to_delete and recorded as a scan error.
        self.assertEqual([d["function"] for d in to_delete], ["StreamSec_ok"])
        self.assertEqual(len(scan_errors), 1)
        self.assertEqual(scan_errors[0]["function"], "StreamSec_bad")
        self.assertIn("could not read tags", scan_errors[0]["reason"])


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

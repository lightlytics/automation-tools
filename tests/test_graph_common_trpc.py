"""
GraphCommon talks to the API's tRPC procedures. These pin the transport (URL, headers,
errors, retries, re-login) and the return shapes the utilities depend on.
"""
import json
import os
import sys
import unittest
import urllib.parse
from unittest.mock import MagicMock, patch

import requests

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from src.python.common import graph_common
from src.python.common.graph_common import GraphCommon, TRPCError


def response(status=200, data=None, error=None):
    res = MagicMock(status_code=status)
    payload = {"error": error} if error else {"result": {"data": data}}
    res.json.return_value = payload
    res.text = json.dumps(payload)
    return res


def client(email=None, pw=None):
    gc = GraphCommon.__new__(GraphCommon)   # skip login
    gc.url = "https://example.streamsec.io/graphql"
    gc.base_url = "https://example.streamsec.io"
    gc.email, gc.pw = email, pw
    gc.token = "Bearer token"
    gc.customer_id = "ws1"
    return gc


def sent_input(call):
    method, url = call.args
    if method == "GET":
        return json.loads(urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["input"][0])
    return call.kwargs["json"]


@patch.object(graph_common.time, "sleep", lambda _: None)
class TestTransport(unittest.TestCase):
    def test_query_is_a_get_with_the_input_in_the_url_and_both_headers(self):
        with patch.object(graph_common.requests, "request", return_value=response(data=[1])) as req:
            self.assertEqual(client().trpc_query("rules.list", {"a": 1}), [1])
        call = req.call_args
        self.assertEqual(call.args[0], "GET")
        self.assertTrue(call.args[1].startswith("https://example.streamsec.io/trpc/rules.list?input="))
        self.assertEqual(sent_input(call), {"a": 1})
        self.assertEqual(call.kwargs["headers"], {"Authorization": "Bearer token", "Customer": "ws1"})

    def test_a_name_that_is_not_a_procedure_is_refused_before_any_request(self):
        with patch.object(graph_common.requests, "request") as req:
            for name in ("../../admin", "rules.list?x=1", "%2e%2e/admin", "rules", "rules.list/x"):
                with self.subTest(name=name), self.assertRaises(ValueError):
                    client().trpc_query(name)
        req.assert_not_called()

    def test_trailing_graphql_in_the_environment_url_is_ignored(self):
        with patch.object(GraphCommon, "get_customer_id", return_value="ws1"):
            gc = GraphCommon("https://example.streamsec.io/graphql", token="t")
        self.assertEqual(gc.base_url, "https://example.streamsec.io")
        self.assertEqual(gc.token, "Bearer t")

    def test_error_envelope_raises_with_the_api_message(self):
        error = {"message": "Rule not found", "data": {"code": "NOT_FOUND", "httpStatus": 404}}
        with patch.object(graph_common.requests, "request", return_value=response(404, error=error)):
            with self.assertRaisesRegex(TRPCError, "rules.detail failed with HTTP 404: Rule not found"):
                client().trpc_query("rules.detail", {"id": "x"})

    def test_expired_token_logs_in_again_once(self):
        responses = [response(401, error={"message": "UNAUTHORIZED"}), response(data={"access_token": "new"}),
                     response(data=[])]
        with patch.object(graph_common.requests, "request", side_effect=responses) as req:
            self.assertEqual(client("me@example.com", "pw").trpc_query("rules.list"), [])
        self.assertEqual(req.call_args_list[1].args[1], "https://example.streamsec.io/trpc/auth.login")
        self.assertEqual(req.call_args_list[2].kwargs["headers"]["Authorization"], "Bearer new")

    def test_token_session_does_not_try_to_log_in(self):
        with patch.object(graph_common.requests, "request",
                          return_value=response(401, error={"message": "UNAUTHORIZED"})) as req:
            with self.assertRaises(TRPCError):
                client().trpc_query("rules.list")
        self.assertEqual(req.call_count, 1)

    def test_gateway_errors_are_retried_for_queries_but_a_create_is_sent_once(self):
        with patch.object(graph_common.requests, "request", side_effect=[response(502), response(data=[])]) as req:
            client().trpc_query("rules.list")
        self.assertEqual(req.call_count, 2)
        with patch.object(graph_common.requests, "request", return_value=response(502)) as req, \
                patch("builtins.print"):
            self.assertFalse(client().create_account("111111111111", ["us-east-1"]))
        self.assertEqual(req.call_count, 1)

    def test_connection_error_is_retried_for_queries(self):
        side_effect = [requests.exceptions.ConnectionError(), response(data=[])]
        with patch.object(graph_common.requests, "request", side_effect=side_effect) as req:
            self.assertEqual(client().trpc_query("rules.list"), [])
        self.assertEqual(req.call_count, 2)


class TestAuth(unittest.TestCase):
    def test_login_and_2fa(self):
        responses = [response(data={"access_token": "mid", "two_factor_state": "SECURED_TOTP"}),
                     response(data={"access_token": "full", "refresh_token": "r"})]
        gc = client()
        gc.token, gc.customer_id = None, None
        with patch.object(graph_common.requests, "request", side_effect=responses) as req:
            self.assertEqual(gc.get_token("me@example.com", "pw"), "Bearer mid")
            self.assertEqual(gc.get_token_otp("123456", "Bearer mid"), "Bearer full")
        login, two_factor = req.call_args_list
        self.assertEqual(login.kwargs["json"], {"email": "me@example.com", "password": "pw"})
        self.assertTrue(two_factor.args[1].endswith("/trpc/twoFactor.authenticate"))
        self.assertEqual(two_factor.kwargs["json"], {"method": "SECURED_TOTP", "user_code": "123456"})
        self.assertEqual(two_factor.kwargs["headers"], {"Authorization": "Bearer mid"})

    def test_workspaces_keep_the_old_keys_and_send_no_customer_header(self):
        rows = [{"id": "ws1", "name": "Production", "role": "ADMIN"}]
        with patch.object(graph_common.requests, "request", return_value=response(data=rows)) as req:
            gc = client()
            self.assertEqual(gc.get_all_customer_ids(), ["ws1"])
            self.assertEqual(gc.get_all_customer_ids(raw=True)[0]["display_name"], "Production")
        self.assertNotIn("Customer", req.call_args.kwargs["headers"])


class TestReturnShapes(unittest.TestCase):
    def call(self, method, data, *args, **kwargs):
        with patch.object(graph_common.requests, "request", return_value=response(data=data)) as req:
            result = getattr(client(), method)(*args, **kwargs)
        return result, req

    def test_accounts_keep_only_the_selected_fields(self):
        account = {"_id": "a1", "cloud_account_id": "111111111111", "account_auth_token": "secret",
                   "cost": {"status": "READY", "external_id": "x"}, "realtime_regions": [{"region_name": "us-east-1"}]}
        [result], _ = self.call("get_accounts", [account])
        self.assertNotIn("account_auth_token", result)
        self.assertEqual(result["cost"]["status"], "READY")
        self.assertNotIn("external_id", result["cost"])
        self.assertIsNone(result["display_name"])
        self.assertEqual(result["realtime_regions"][0]["template_version"], None)

    def test_resource_searches_ask_for_every_match_except_free_text(self):
        _, req = self.call("get_resources_by_type", {"results": []}, "instance")
        self.assertEqual((sent_input(req.call_args)["cursor"], sent_input(req.call_args)["limit"]), (0, 0))
        _, req = self.call("general_resource_search", {"results": []}, "prod")
        self.assertEqual(sent_input(req.call_args)["limit"], 100)

    def test_rule_metadata_has_the_singular_predicates_in_the_old_shape(self):
        rule = {"id": "r1", "resource_predicates": [{"resource_type": "instance", "is_expired": False}],
                "path_source_predicates": [], "path_destination_predicates": [{"resource_id": "i-1"}],
                "ports": [{"start": 22, "end": 22, "match": "any"}]}
        result, _ = self.call("get_rule_metadata", rule, "r1")
        self.assertEqual(result["resource_predicate"], {"resource_id": None, "resource_type": "instance",
                                                        "attributes": None, "tags": None, "locations": None,
                                                        "__typename": "ResourceCondition"})
        self.assertIsNone(result["path_source_predicate"])
        # The compliance report reads resource_type with [] and falls back to another predicate when it is None.
        self.assertIsNone(result["path_destination_predicate"]["resource_type"])
        self.assertEqual(result["ports"], [{"start": 22, "end": 22, "protocol": None, "__typename": "PortRange"}])

    def test_condition_attributes_keep_the_six_levels_the_old_query_selected(self):
        level = {"name": "a7"}
        for depth in range(6, 0, -1):
            level = {"name": f"a{depth}", "attributes_list": [level]}
        rule = {"id": "r1", "resource_predicates": [{"tags": {"operand": "AND", "attributes_list": [level]}}]}
        result, _ = self.call("get_rule_metadata", rule, "r1")
        attribute = result["resource_predicate"]["tags"]["attributes_list"][0]
        self.assertEqual(list(attribute), ["name", "value", "match_type", "operand", "__typename", "attributes_list"])
        for _ in range(5):
            attribute = attribute["attributes_list"][0]
        self.assertEqual(attribute["name"], "a6")
        self.assertNotIn("attributes_list", attribute)

    def test_enrichment_sessions_keep_their_keys_in_either_stored_shape(self):
        sessions = {"_id": "d1", "session_list": [{"ip_address": "203.0.113.1", "src_resource_type": "user"}]}
        summary = {"_id": "d2", "session_list": {"ip_addresses": [{"Ip": "203.0.113.1", "CountryCode": "US"}]}}
        [result], _ = self.call("get_detection_enrichment", {"results": [sessions]}, "d1")
        self.assertEqual(result["session_list"], [{"ip_address": "203.0.113.1", "access_key": None,
                                                   "user_agent": None, "country_code_iso": None, "mfa": None,
                                                   "__typename": "Session"}])
        self.assertIsNone(result["signals"])
        [result], _ = self.call("get_detection_enrichment", {"results": [summary]}, "d2")
        self.assertEqual(result["session_list"], {"ip_addresses": [{"Ip": "203.0.113.1", "CountryCode": "US",
                                                                    "__typename": "IpAddress"}],
                                                  "access_keys": None, "user_agents": None,
                                                  "src_resource_type": None, "__typename": "SessionList"})

    def test_enrichment_signals_keep_the_fields_the_old_query_selected(self):
        signals = [{"signal_type": "malicious_ip_signal", "__typename": "MaliciousIpSignal", "score": 9,
                    "malicious_ip_records": [{"ip_address": "203.0.113.1", "country": "US"}]},
                   {"signal_type": "anomalous_api_call_signal", "__typename": "AnomalousApiCallSignal",
                    "http_path": "/login"}]
        [result], _ = self.call("get_detection_enrichment", {"results": [{"_id": "d1", "signals": signals}]}, "d1")
        self.assertEqual(result["signals"], [
            {"signal_type": "malicious_ip_signal",
             "malicious_ip_records": [{"ip_address": "203.0.113.1", "severity": None, "hosts": None, "ports": None,
                                       "initiated_session": None, "vol_traffic": None, "__typename": "IpRecord"}],
             "__typename": "MaliciousIpSignal"},
            {"signal_type": "anomalous_api_call_signal", "__typename": "AnomalousApiCallSignal"}])

    def test_rule_violations_are_resource_ids(self):
        result, _ = self.call("get_rule_violations", {"results": [{"subject_id": "i-1"}], "total_count": 1}, "r1")
        self.assertEqual(result, ["i-1"])

    def test_cves_skip_false_flags_and_keep_numeric_severity(self):
        result, req = self.call("get_cves", {"results": [{"cve_id": "CVE-1", "severity": "HIGH",
                                                          "severity_numeric": 3}]})
        self.assertEqual(sent_input(req.call_args)["filters"], {})
        self.assertEqual(result[0]["severity"], 3)

    def test_cves_are_read_page_by_page_until_a_short_page(self):
        pages = [response(data={"results": [{"cve_id": "CVE-1"}]}), response(data={"results": []})]
        with patch.object(graph_common, "PAGE_SIZE", 1), \
                patch.object(graph_common.requests, "request", side_effect=pages) as req:
            self.assertEqual([c["cve_id"] for c in client().get_cves()], ["CVE-1"])
        self.assertEqual([(sent_input(c)["skip"], sent_input(c)["limit"]) for c in req.call_args_list],
                         [(0, 1), (1, 1)])

    def test_flow_log_rows_end_with_typename(self):
        # export_flow_logs drops each row's last key when it builds the CSV header.
        result, req = self.call("get_flow_logs", {"results": [{"dst_geo_iso": "US", "src_port": 1}]}, limit=5)
        self.assertEqual(list(result[0])[-2:], ["dst_geo_iso", "__typename"])
        self.assertEqual(req.call_args.args[0], "POST")

    def test_a_failed_csv_export_is_none_so_the_reports_skip_the_rule(self):
        with patch.object(graph_common.requests, "request",
                          return_value=response(500, error={"message": "An internal error occurred"})):
            self.assertIsNone(client().export_csv_rule("r1"))

    def test_kubernetes_cost_keeps_the_keys_the_export_deletes(self):
        result, _ = self.call("get_kubernetes_cost", {"total_count": 1, "results": [{"total_cost": 5}]},
                              "arn", "from", "to")
        self.assertIn("timestamp", result["results"][0])
        self.assertIn("__typename", result["results"][0])

    def test_detections_send_flat_paging_input(self):
        _, req = self.call("get_detections", {"results": []})
        sent = sent_input(req.call_args)
        self.assertEqual((sent["skip"], sent["limit"]), (0, 500))
        self.assertNotIn("filters", sent)


if __name__ == "__main__":
    unittest.main()

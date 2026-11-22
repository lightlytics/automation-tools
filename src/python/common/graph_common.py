import datetime
import json
import re
import time
import urllib.parse

import requests

# Report reads (rules, CSV exports, cost) can take minutes on a large workspace.
REQUEST_TIMEOUT_S = 300
PROCEDURE_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_]*(\.[A-Za-z][A-Za-z0-9_]*)+")
RETRY_STATUSES = (502, 503, 504)

ACCOUNT_KEYS = ('_id', 'account_type', 'cloud_account_id', 'cloud_regions', 'display_name', 'external_id', 'status',
                'template_url', 'collection_template_url', 'remediation_template_url', 'realtime_regions',
                'vpc_flow_logs', 'lightlytics_collection_token', 'stack_region', 'account_aliases', 'cost')
ACCOUNT_COST_KEYS = ('status', 'details', 'operation', 'template_version', 'role_arn', 'bucket_arn', 'cur_prefix',
                     'last_timestamp')
UPDATED_ACCOUNT_KEYS = ('_id', 'display_name', 'cloud_regions', 'template_url', 'collection_template_url')
KUBERNETES_KEYS = ('_id', 'type', 'display_name', 'creation_date', 'status', 'collection_token', 'eks_arn')
SEARCH_KEYS = ('id', 'type', 'display_name', 'addresses', 'is_public', 'state')
SEARCH_FIELDS = ['display_name', 'addresses', 'is_public', 'state', 'network_interfaces']
RULE_KEYS = ('id', 'name', 'creation_date', 'created_by', 'category', 'severity', 'description', 'labels',
             'compliance', 'status', 'state', 'rule_type', 'fail_simulation', 'exclusions_count')
RULE_PREDICATES = ('path_source', 'path_intermediate', 'path_destination', 'resource')
RULE_METADATA_KEYS = ('id', 'name', 'status', 'state', 'category', 'severity', 'description', 'remediation', 'labels',
                      'compliance', 'rule_type', 'subject', 'action', 'path_source_predicate_equals_match',
                      'path_intermediate_predicate_equals_match', 'path_destination_predicate_equals_match',
                      'path_source_predicate', 'path_intermediate_predicate', 'path_destination_predicate',
                      'resource_predicate', 'fail_simulation', 'ports', 'creation_date', 'created_by')
RULE_CSV_KEYS = ('rule_name', 'description', 'category', 'severity', 'labels', 'compliance', 'date', 'violation_count')
RULE_CSV_VIOLATION_KEYS = ('resource_id', 'resource_name', 'resource_type', 'account_display_name', 'account_id',
                           'region', 'vpc_id', 'tags', 'monthly_cost')
COST_REPORT_KEYS = ('day', 'month', 'year', 'account', 'region', 'resource_type', 'product_family', 'pricing_term',
                    'total_cost')
COST_KEYS = ('is_real_resource_id', 'timestamp', 'total_cost', 'total_direct_cost', 'total_indirect_cost',
             'preceding_total_cost', 'preceding_total_direct_cost', 'predicted_cost', 'trend_difference',
             'trend_percentage', 'trend_difference_direct', 'trend_percentage_direct', 'trend_difference_indirect',
             'trend_percentage_indirect', 'resource_type', 'account', 'region')
K8S_COST_KEYS = ('timestamp', 'total_cost', 'trend_difference', 'trend_percentage', 'cpu_cost', 'cpu_max_usage',
                 'cpu_average_usage', 'cpu_requested', 'ram_cost', 'ram_max_usage', 'ram_average_usage',
                 'ram_requested', 'volume_cost', 'traffic_cost', 'efficiency', 'predicted_cost', 'cpu_charge_average',
                 'memory_charge_average')
K8S_CLUSTER_COST_KEYS = ('total_cluster_cost', 'total_cluster_idle_cost', 'trend_percentage_cluster_cost',
                         'trend_percentage_cluster_idle_cost')
CVE_KEYS = ('attack_vector', 'cve_id', 'cve_sources', 'severity', 'cvss_score', 'packages', 'exploit_available',
            'internet_exposed', 'affected_resources_count', 'fix_available', 'fixed_in_version', 'epss_score',
            'cisa_kev', 'published_date', 'discovery_timestamp')
CVE_RESOURCE_KEYS = ('account_id', 'resource_id', 'resource_type', 'container_images', 'exposure_risk',
                     'exposure_risk_description', 'internet_exposed')
FLOW_LOG_KEYS = ('src_port', 'src_resource_id', 'src_resource_type', 'src_resource_display_name', 'src_ip', 'dst_port',
                 'dst_resource_id', 'dst_resource_type', 'dst_resource_display_name', 'dst_ip', 'start', 'end', 'bytes',
                 'action', 's3_action', 'protocol', 'application_name', 'application_desc', 'src_geo_iso',
                 'dst_geo_iso')
DETECTION_KEYS = ('_id', 'timestamp', 'activity_type', 'source', 'account_id', 'anomaly_severity', 'resource_id',
                  'resource_type', 'mitre_categories', 'acknowledged', 'acknowledgement_details', 'signal_types')
DETECTION_ENRICHMENT_KEYS = ('_id', 'timestamp', 'activity_type', 'source', 'account_id', 'anomaly_severity',
                             'cluster', 'namespace', 'resource_id', 'resource_type', 'resource_cluster',
                             'resource_namespace', 'resource_deployment', 'mitre_categories', 'acknowledged',
                             'signal_types', 'session_list', 'acknowledgement_details', 'external_id', 'external_url',
                             'json_data', 'signals')
PAGE_SIZE = 500


class TRPCError(Exception):
    """ The API answered a procedure call with an error. """


def _pick(row, keys, typename=None):
    """ The row's values for keys, in that order. The API leaves out null values, so a missing key is None. """
    if row is None:
        return None
    out = {key: row.get(key) for key in keys}
    if typename:
        out['__typename'] = typename
    return out


def _as_list(value):
    return value if isinstance(value, list) else [value]


class GraphCommon(object):
    def __init__(self, url, email=None, pw=None, customer_id=None, otp=None, token=None):
        """ Initialize GraphCommon class to graph functions.
            :param url (str)            - The url of the environment, e.g. https://<env>.streamsec.io
                                          (a trailing /graphql is accepted).
            :param email (str)          - The email for login.
            :param pw (str)             - The password for login.
            :param otp (str)            - 2FA token.
            :param customer_id (str)    - The customer ID for operations; Defaults to the Demo Customer ID.
            :param token (str)          - Pre-existing API token; if provided, skips email/pw login.
        """
        self.url = url
        self.base_url = url.rstrip('/')
        if self.base_url.endswith('/graphql'):
            self.base_url = self.base_url[:-len('/graphql')]
        self.email = email
        self.pw = pw
        self.customer_id = None
        self.token = None
        if token:
            if not isinstance(token, str):
                raise ValueError(f"token must be a string, got {type(token).__name__}")
            self.token = token if token.startswith('Bearer ') else f'Bearer {token}'
        else:
            self.token = self.get_token(email, pw)
            if otp:
                self.token = self.get_token_otp(otp, self.token)
        time.sleep(2)
        self.customer_id = customer_id or self.get_customer_id()

    def get_token(self, email, pw):
        """ Get token.
            :param email (str)  - The email for login.
            :param pw (str)     - The password for login.
            :returns (str)      - Token.
        """
        try:
            data = self._trpc_call("POST", "auth.login", {"email": email, "password": pw}, resend=False)
        except requests.exceptions.RequestException as e:
            raise Exception(f"URL doesn't exist --> {self.base_url}, error: {e}")
        self.token = 'Bearer ' + data['access_token']
        return self.token

    def get_token_otp(self, otp, token):
        """ Get token using 2FA.
            :param otp (str)    - The OTP code provided by the user.
            :param token (str)  - Token received after successful login.
            :returns (str)      - New Bearer Token.
        """
        data = self._trpc_call("POST", "twoFactor.authenticate", {"method": "SECURED_TOTP", "user_code": otp},
                               resend=False, token=token, with_customer=False)
        return 'Bearer ' + data['access_token']

    def get_customer_id(self, email=None, pw=None, token=None):
        """ Get customer id.
            :param email (str)  - The email for login.
            :param pw (str)     - The password for login.
            :param token (str)  - Token.
            :returns (str)      - The first customer id.
        """
        return self.get_all_customer_ids(email, pw, token)[0]

    def get_all_customer_ids(self, email=None, pw=None, raw=False):
        """ Get all customer ids.
            :param email (str)  - The email for login.
            :param pw (str)     - The password for login.
            :param raw (bool)   - Whether the return the entire result not just the IDs.
            :returns (str)      - Customer ids list.
        """
        if not self.token:
            self.token = self.get_token(email or self.email, pw or self.pw)
        try:
            data = self._trpc_call("GET", "workspaces.list", {}, resend=True, with_customer=False)
        except TRPCError as e:
            raise Exception(f"Could not get customer id, error: {e}")
        workspaces = [{"_id": w["id"], "display_name": w.get("name"), "role": w.get("role"),
                       "__typename": "Workspace"} for w in data]
        if raw:
            return workspaces
        return [w['_id'] for w in workspaces]

    def get_ws_id_by_name(self, ws_name):
        """ Get Workspace ID by name.
            :param ws_name (str)    - Workspace name.
            :returns (str)          - Workspace ID.
        """
        workspaces = self.get_all_customer_ids(raw=True)
        specific_ws = [ws for ws in workspaces if ws["display_name"] == ws_name]
        try:
            return specific_ws[0]["_id"]
        except IndexError:
            raise Exception("Can't find WS")

    # Account methods
    def get_accounts(self, raise_on_error=False):
        """ Get all accounts.
            :param raise_on_error (bool) - Raise on a null/invalid/errored response instead
                of returning []. Callers that treat "not found" as "create it" need this.
            :returns (list) - Integrations in the environment.
        """
        try:
            result = self.trpc_query("integrations.cloud_accounts_api.list", {})
        except TRPCError as e:
            result = str(e)
        # Treat an invalid/errored response as "no accounts" (warn once), but return a
        # genuinely empty list as-is so an environment with zero integrations isn't flagged.
        if not isinstance(result, list):
            if raise_on_error:
                raise Exception(f"Could not list accounts from {self.url}: {str(result)[:200]}")
            if not getattr(self, "_warned_empty_accounts", False):
                print(f"Warning: null/invalid accounts response from {self.url}; treating as no accounts.")
                self._warned_empty_accounts = True
            return []
        return [self._account(a) for a in result]

    @staticmethod
    def _account(account):
        out = _pick(account, ACCOUNT_KEYS, 'Account')
        realtime_regions = account.get('realtime_regions')
        out['realtime_regions'] = None if realtime_regions is None else [
            _pick(r, ('region_name', 'template_version'), 'RealtimeRegionDocument') for r in realtime_regions]
        out['vpc_flow_logs'] = _pick(account.get('vpc_flow_logs'), ('flow_logs_token', 'should_collect_flow_logs'),
                                     'VpcFlowLogs')
        out['cost'] = _pick(account.get('cost'), ACCOUNT_COST_KEYS, 'CostData')
        return out

    def get_account_response_config(self, cloud_account_id):
        """ Get an account's response (remediation) configuration.
            :returns (dict) - The account ID and its remediation details.
        """
        account = self.trpc_query("integrations.cloud_accounts_api.getByCloudId",
                                  {"cloud_account_id": cloud_account_id})
        return {"_id": account.get("_id"),
                "remediation": _pick(account.get("remediation"),
                                     ('status', 'template_version', 'external_id', 'role_arn', 'stack_id'))}

    def create_account(self, account_id, regions_list, display_name=None):
        """ Create account.
            :param account_id (str)     - Specific AWS account ID.
            :param regions_list (list)  - Regions which the user want to add.
            :param display_name (str)    - Display name for AWS Account; Defaults to None.
            :returns (dict)             - Account details.
        """
        account = {"account_type": "AWS",
                   "cloud_account_id": account_id,
                   "cloud_regions": regions_list,
                   "stack_region": regions_list[0]}
        if display_name:
            account["display_name"] = display_name
        try:
            self.trpc_mutation("integrations.cloud_accounts_api.create", account)
        except TRPCError as e:
            print("Something went wrong with creating an account / Account already exists")
            print(e)
            return False
        return True

    def get_specific_account(self, account_id):
        """ Get specific account.
            :param account_id (str) - Specific AWS account ID.
            :returns (dict)         - Account details.
        """
        account = [a for a in self.get_accounts() if a['cloud_account_id'] == account_id][0]
        try:
            return account
        except IndexError:
            raise Exception(f"Can't find the desired account: {account_id}")

    def get_account_status(self, account_id):
        """ Get account status.
            :param account_id (str) - Specific AWS account ID.
            :returns (str)          - Integration status.
        """
        accounts = self.get_accounts()
        if not accounts:
            raise Exception(
                f"Stream Security API returned no accounts while checking status for {account_id} "
                f"(likely a transient/null API response). The integration may have succeeded - "
                f"verify in the UI and re-run for this account if needed.")
        specific_account = next(
            (account for account in accounts if account["cloud_account_id"] == account_id), None)
        if specific_account is None:
            raise Exception(
                f"Account {account_id} was not found in Stream Security while polling its status.")
        return specific_account["status"]

    def wait_for_account_connection(self, account, timeout=600):
        """ Wait for account to be connected.
            :param timeout (int)    - Max waiting time; Defaults to 600.
            :param account (str)    - Account ID.
            :returns (str)          - Account's status.
        """

        dt_start = datetime.datetime.utcnow()
        dt_diff = 0
        account_status = ''
        while dt_diff < timeout:
            account_status = self.get_account_status(account)
            dt_finish = datetime.datetime.utcnow()
            dt_diff = (dt_finish - dt_start).total_seconds()
            if account_status != "READY":
                time.sleep(1)
            else:
                return account_status
        return account_status

    def edit_regions(self, account_id, regions_list):
        """ Edit regions list.
            :param account_id (str)     - Specific AWS account ID.
            :param regions_list (list)  - Region's list which the user wants to add.
            :returns (dict)             - Account details.
        """
        return self._update_account(account_id, {"cloud_regions": _as_list(regions_list)})

    def update_account_display_name(self, account_id, display_name):
        """ Update a specific account display name.
            :param account_id (str)     - Specific AWS account ID.
            :param display_name (list)  - Display name to change to.
            :returns (dict)             - Account details.
        """
        return self._update_account(account_id, {"display_name": display_name})

    def _update_account(self, account_id, changes):
        try:
            account = self.trpc_mutation("integrations.cloud_accounts_api.update",
                                         {"id": self.get_specific_account(account_id)["_id"], **changes}, resend=True)
        except TRPCError as e:
            raise Exception(f"Something else occurred, error: {e}")
        return _pick(account, UPDATED_ACCOUNT_KEYS, 'Account')

    # Resources methods
    def get_resources_by_account(self, account_id):
        """ Get resources details by account.
            :returns (dict/list)            - resources details.
        """
        return self.trpc_query("inventory.type", {"account_id": [account_id]})

    def get_resources_by_type(self, resource_type, get_only_ids=False):
        """ Get resources details by type.
            :param resource_type (str)      - Resource type.
            :param get_only_ids (boolean)   - Return only IDs.
            :returns (dict/list)            - resources details.
        """
        rows = self._search({"phrase": "", "filters": {"resource_type": [resource_type], "attributes": []}},
                            SEARCH_FIELDS)
        resources = [self._search_row(r, include_tags=False) for r in rows]
        if get_only_ids:
            return [r['id'] for r in resources]
        return resources

    def general_resource_search(self, search_query, get_only_ids=False):
        """ Get resources details by type.
            :param search_query (str)       - query to search by.
            :param get_only_ids (boolean)   - Return only IDs.
            :returns (dict/list)            - resources details.
        """
        # A free-text search returns its first 100 matches.
        rows = self._search({"phrase": search_query}, SEARCH_FIELDS, limit=100 if search_query else 0)
        resources = [self._search_row(r, include_tags=False) for r in rows]
        if get_only_ids:
            return [r['id'] for r in resources]
        return resources

    def get_resources_type_count_by_account(self, resource_type, account):
        """ Get resources count by account.
            :param account (str)        - Account ID.
            :param resource_type (str)  - Resource type.
            :returns (int)              - Resources count.
        """
        results = self.trpc_query("inventory.type", {"account_id": account})
        try:
            return [r["count"] for r in results if r["resource_type"] == resource_type][0]
        except IndexError:
            return 0

    def get_resource_configuration_by_id(self, resource_id, raw=False, get_from_latest_timestamp=False):
        """ Get configuration details by resource's ID.
            :param resource_id (str)                - Specific resource's ID.
            :param raw (bool)                       - Get Raw data instead of translated.
            :param get_from_latest_timestamp (bool) - Get from latest timestamp instead of current (Enriched).
            :returns (dict)                         - Configuration details.
        """
        variables = {"resource_id": resource_id}
        if get_from_latest_timestamp:
            variables["timestamp"] = self.get_resource_configuration_latest_version_by_id(resource_id)
        configuration = self.trpc_query("inventory.fullConfiguration", variables)
        if raw:
            return configuration['raw']
        return configuration['translated']

    def get_resource_configuration_latest_version_by_id(self, resource_id):
        """ Get configuration details by resource's ID.
            :param resource_id (str)                - Specific resource's ID.
            :returns (dict)                         - Configuration latest version timestamp.
        """
        res = self.trpc_query("inventory.configurationVersions", {"resource_id": resource_id, "cursor": 0, "limit": 1})
        try:
            return res['results'][0]['timestamp']
        except IndexError:
            raise Exception("Can't find latest version of the configuration, fatal error")

    def get_resource_parents_by_id(self, resource_id):
        """ Get parent by resource's ID.
            :param resource_id (str)    - Specific resource's ID.
            :returns (list)             - Resource parents.
        """
        return self.trpc_query("inventory.details", {"resource_id": resource_id}).get('parent')

    def get_resource_metadata(self, resource_id):
        """ Get resource metadata.
            :param resource_id (str)    - Specific resource's ID.
            :returns (str)              - Account ID.
        """
        resource = self.trpc_query("inventory.resource", {"resource_id": resource_id})
        return _pick(resource, ('id', 'type', 'display_name', 'end_timestamp', 'region', 'parent', 'account_id'),
                     'Resource')

    def get_resource_ancestors(self, resource_id):
        """ Get resource ancestors.
            :param resource_id (str)    - Specific resource's ID.
            :returns (dict)             - Ancestors information.
        """
        ancestors = self.trpc_query("inventory.ancestors", {"resource_id": resource_id})
        return [_pick(a, ('id', 'type', 'display_name', 'parent'), 'Resource') for a in ancestors]

    def get_resource_account_id(self, resource_id):
        """ Get resource account ID.
            :param resource_id (str)    - Specific resource's ID.
            :returns (str)              - Account ID.
        """
        resource = self.trpc_query("inventory.resource", {"resource_id": resource_id})
        return _pick(resource, ('account_id',))['account_id']

    def get_resource_associated_resources(self, resource_id):
        """ Get resource associated resources.
        """
        rows = self._search({"filters": {"associated_resource_id": resource_id}}, ['display_name'])
        return [_pick(r, ('id', 'type', 'display_name'), 'Resource') for r in rows]

    def resources_search(self, account, resource_type, tags=None):
        """ Search resources by account and types.
            :param account (str)        - Account to search in.
            :param resource_type (str)  - Resource type.
            :param tags (list)          - List of tags to filter by.
            :returns (list)             - List of resources.
        """
        filters = {"resource_type": [resource_type], "account_id": _as_list(account), "attributes": []}
        if tags:
            filters["tags"] = _as_list(tags)
        rows = self._search({"phrase": "", "filters": filters}, SEARCH_FIELDS + ['tags', 'cloud_tags'])
        return [self._search_row(r, include_tags=True) for r in rows]

    def _search(self, search_input, fields, limit=0):
        """ One inventory search page from the start; limit 0 returns every match. """
        return self.trpc_query("inventory.search",
                               {**search_input, "fields": fields, "cursor": 0, "limit": limit})["results"]

    @staticmethod
    def _search_row(row, include_tags):
        out = _pick(row, SEARCH_KEYS)
        interfaces = row.get('network_interfaces')
        out['network_interfaces'] = None if interfaces is None else [
            _pick(i, ('id', 'addresses'), 'NetworkInterface') for i in interfaces]
        if include_tags:
            for key in ('tags', 'cloud_tags'):
                tags = row.get(key)
                out[key] = None if tags is None else [_pick(t, ('Key', 'Value'), 'Tag') for t in tags]
        out['__typename'] = 'Resource'
        return out

    # Arch Standards methods
    def get_all_rules(self):
        """ Get all "standards" rules.
            :returns (list) - Rules.
        """
        return [_pick(r, RULE_KEYS, 'Rule') for r in self.trpc_query("rules.list", {})['results']]

    def get_rules_by_compliance(self, compliance):
        """ Get all "standards" rules by compliance.
            :returns (list) - Compliance rules.
        """
        return [r for r in self.get_all_rules() if compliance in r['compliance']]

    def get_rule_metadata(self, rule_id):
        """ Get rule metadata.
            :returns (dict) - Rule metadata.
        """
        rule = self.trpc_query("rules.detail", {"id": rule_id})
        for predicate in RULE_PREDICATES:
            rule[f"{predicate}_predicate"] = (rule.get(f"{predicate}_predicates") or [None])[0]
        return _pick(rule, RULE_METADATA_KEYS, 'Rule')

    def get_rule_violations(self, rule_id):
        """ Get all rule violations.
            :returns (list) - IDs of the violating resources.
        """
        data = self.trpc_query("rules.ruleViolations", {"rule_id": rule_id, "filter_inventory": {}})
        return [r['subject_id'] for r in data['results']]

    def export_csv_rule(self, rule_id):
        """ Get CSV formatted data regarding rule violations.
            :returns (csv) - Rule violations; None when the export fails.
        """
        try:
            data = self.trpc_mutation("rules.ruleCsv", {"rule_id": rule_id}, resend=True)
        except TRPCError:
            return None
        out = _pick(data, RULE_CSV_KEYS)
        out['violations'] = [_pick(v, RULE_CSV_VIOLATION_KEYS, 'RuleCsvViolation') for v in data.get('violations') or []]
        out['__typename'] = 'RuleCsvResponse'
        return out

    def get_violation_cost_predicted_savings(self, rule_id, resource_id):
        """ Get Predicted Savings for a specific rule violation.
            :returns (int) - Predicted Savings for the violation.
        """
        data = self.trpc_query("rules.violationCost", {"rule_id": rule_id, "resource_ids": [resource_id]})
        return data['results'][0].get('predicted_monthly_cost')

    def get_compliance_standards(self):
        """ Get all compliance standards.
            :returns (list) - Available compliance standards.
        """
        return self.trpc_query("rules.facets", {})['compliance']

    # Cost methods
    def check_cost_integration(self):
        """
        Check whether cost is integrated or not.
        :returns (bool) - True/False if cost integrated.
        """
        integration_status = (self.trpc_query("cost.dataStatus", {}) or {}).get("status")
        return True if integration_status == "data_exists" else False

    def get_cost_chart(self, from_timestamp, to_timestamp, group_by=None, ignore_discounts=None):
        """
        Get the cost information.
        :returns (list) - Cost data.
        """
        # ignore_discounts was never sent with the query, so the report has always used the default cost type.
        variables = {
            "filters": {
                "from_timestamp": from_timestamp,
                "to_timestamp": to_timestamp
            },
            "group_bys": [
                "resource_type", "region", "account", "product_family", "pricing_term"
            ]
        }
        if group_by:
            variables["period"] = group_by
        return [_pick(r, COST_REPORT_KEYS) for r in self.trpc_query("cost.reports", variables)["results"]]

    def get_cost_chart_main_pipeline(self, from_timestamp, to_timestamp, group_by=None):
        """
        Get the cost information.
        :returns (list) - Cost data.
        """
        variables = {
            "filters": {
                "from_timestamp": from_timestamp,
                "to_timestamp": to_timestamp
            },
            "sort": {
                "field": "total_direct_cost",
                "direction": "desc"
            },
            "group_bys": [
                "resource_type", "region", "account", group_by
            ],
            "cursor": 0,
            "limit": 99999
        }
        results = self.trpc_query("cost.cost", variables)['results']
        return [_pick(r, COST_KEYS + (group_by,), 'CostResult') for r in results]

    def get_cost_rules(self):
        """
        Get Cost-related rules.
        :returns (list) - Cost Rules.
        """
        return [r for r in self.get_all_rules() if r["category"] == "Cost" and r["status"] == "active"]

    def get_recommendations_history_by_date(self, req_date):
        """
        Get recommendations history by date.
        :param req_date (str)   - Date; format - YYYY/MM/YY.
        :returns (dict)         - Recommendations history.
        """
        return self.trpc_query("rules.costViolationsHistory", {"date": req_date})['data']

    def get_all_recommendations_history_dates(self):
        """
        Get recommendations history by date.
        :returns (list) - Recommendations history available dates.
        """
        return [d["date"] for d in self.trpc_query("rules.costViolationsHistoryDates", {})]

    def get_kubernetes_integrations(self, get_only_names=False):
        """
        Get Kubernetes integrations.
        :returns (list) - K8s integration list.
        """
        res = [_pick(k, KUBERNETES_KEYS, 'Kubernetes')
               for k in self.trpc_query("integrations.kubernetes_api.list", {})]
        if get_only_names:
            return [ki['display_name'] for ki in res]
        return res

    def create_kubernetes_integration(self, eks_arn, display_name):
        """
        Create Kubernetes integration.
        :returns (list) - K8s integration list.
        """
        try:
            integration = self.trpc_mutation("integrations.kubernetes_api.create",
                                             {"display_name": display_name, "eks_arn": eks_arn})
        except TRPCError as e:
            print(f"Failed to create integration - {e}")
            return False
        return _pick(integration, ('_id', 'collection_token'), 'Kubernetes')

    def get_kubernetes_cost(self, cluster_arn, from_ts, to_ts):
        """
        Get EKS cost.
        """
        variables = {
            "filters": {
                "cluster": cluster_arn,
                "from_timestamp": from_ts,
                "to_timestamp": to_ts
            },
            "group_bys": [],
            "trend_period": "month",
            "cursor": 0,
            "limit": 310
        }
        try:
            data = self.trpc_query("cost.costK8s", variables)
        except TRPCError as e:
            print(f"Failed to create integration - {e}")
            return False
        return {"total_count": data.get("total_count"),
                "results": [_pick(r, K8S_COST_KEYS, 'CostK8sResult') for r in data["results"]],
                "__typename": "CostK8sResponse"}

    def get_kubernetes_cluster_cost(self, cluster_arn, from_ts, to_ts):
        """
        Get EKS cluster cost.
        """
        variables = {
            "filters": {
                "cluster": cluster_arn,
                "from_timestamp": from_ts,
                "to_timestamp": to_ts
            },
            "trend_period": "month"
        }
        try:
            data = self.trpc_query("cost.k8sClusters", variables)
        except TRPCError as e:
            print(f"Failed to create integration - {e}")
            return False
        return _pick(data, K8S_CLUSTER_COST_KEYS, 'CostK8sClustersResponse')

    def delete_eks_integration(self, integration_id):
        """
        Delete EKS integration.
        """
        try:
            self.trpc_mutation("integrations.kubernetes_api.delete", {"id": integration_id})
        except TRPCError as e:
            print(f"Failed to create integration - {e}")
            return False
        return True

    # CVEs
    def get_cves(self, public_exposed=False, exploit_available=False, fix_available=False, cve_id=None, source=None,
                 packages=None, resource_id=None, resource_type=None, severity=None):
        """ Get CVEs.
            :returns (list) - CVEs information.
        """
        # A false flag means "don't filter"; the API reads fix_available=false as "only CVEs without a fix".
        filters = {}
        if public_exposed:
            filters["internet_exposed"] = True
        if exploit_available:
            filters["exploit_available"] = True
        if fix_available:
            filters["fix_available"] = True
        for key, value in (("cve_id", cve_id), ("source", source), ("packages", packages),
                           ("resource_id", resource_id), ("resource_type", resource_type), ("severity", severity)):
            if value:
                filters[key] = _as_list(value)
        rows = self._pages("cve.listCvesPost", {"filters": filters, "sort_by": "cvss_score", "sort_order": "desc"})
        return [self._cve(r) for r in rows]

    @staticmethod
    def _cve(row):
        out = _pick(row, CVE_KEYS, 'CVE')
        out['severity'] = row.get('severity_numeric')
        kev = row.get('cisa_kev')
        if kev:
            out['cisa_kev'] = _pick(kev, ('action', 'date_added', 'due_date'), 'CisaKevField')
        return out

    def get_affected_resources(self, cve_id):
        rows = self._pages("cve.listCveResourcesPost", {"filters": {"cve_ids": [cve_id]}})
        return [_pick(r, CVE_RESOURCE_KEYS, 'VulnerableResource') for r in rows]

    def _pages(self, procedure, query_input):
        """ Every row of a skip/limit procedure, PAGE_SIZE at a time. """
        rows = []
        while True:
            page = self.trpc_query(procedure, {**query_input, "skip": len(rows), "limit": PAGE_SIZE})['results']
            rows.extend(page)
            if len(page) < PAGE_SIZE:
                return rows

    # Flow logs methods
    def get_flow_logs(self, skip=0, limit=999, action=None, dst_resource_id=None, start_time=None, end_time=None,
                      src_public=False, protocols=None):
        filters = {}
        if action:
            filters['action'] = [action]
        if dst_resource_id:
            filters['dst_resource_id'] = dst_resource_id
        start = {key: value for key, value in (('gte', start_time), ('lte', end_time)) if value}
        if start:
            filters['start'] = start
        if src_public:
            filters['src_ip_filter'] = {'is_internet': True}
        if protocols:
            filters['protocol'] = protocols.split(",")
        data = self.trpc_mutation("logQuery.uiTrafficLogs", {"filters": filters, "skip": skip, "limit": limit},
                                  resend=True)
        return [_pick(r, FLOW_LOG_KEYS, 'Connection') for r in data['results']]

    def get_detections(self, page_size=500):
        # 500 per page balances fewer round-trips against request payload size;
        # the server's default implicit limit was dropping results beyond ~100.
        all_results = []
        skip = 0
        while True:
            data = self.trpc_query("detections.list",
                                   {"skip": skip, "limit": page_size, "fields": list(DETECTION_KEYS)})
            batch = [self._detection(r, DETECTION_KEYS) for r in data['results']]
            all_results.extend(batch)
            if len(batch) < page_size:
                break
            skip += page_size
        return all_results

    def get_detection_enrichment(self, detection_id):
        data = self.trpc_query("detections.detail", {"filters": {"_id": [detection_id]}})
        return [self._detection(r, DETECTION_ENRICHMENT_KEYS) for r in data['results']]

    @staticmethod
    def _detection(row, keys):
        out = _pick(row, keys, 'Detection')
        out['acknowledgement_details'] = _pick(out['acknowledgement_details'], ('timestamp', 'user', 'reason'),
                                               'AcknowledgementDetails')
        return out

    # General methods
    def trpc_query(self, procedure, input_data=None):
        """ Call a query procedure.
            :param procedure (str)      - Router and procedure, e.g. "rules.list".
            :param input_data (dict)    - The procedure's input.
            :returns                    - The procedure's result.
        """
        return self._trpc_call("GET", procedure, input_data, resend=True)

    def trpc_mutation(self, procedure, input_data=None, resend=False):
        """ Call a mutation procedure.
            :param procedure (str)      - Router and procedure, e.g. "integrations.cloud_accounts_api.create".
            :param input_data (dict)    - The procedure's input.
            :param resend (bool)        - Send again after a gateway error; only for a call that is safe to repeat.
            :returns                    - The procedure's result.
        """
        return self._trpc_call("POST", procedure, input_data, resend=resend)

    def _trpc_call(self, method, procedure, input_data, resend, token=None, with_customer=True):
        # A router.procedure name only, so a name can't reach another path on the host.
        if not PROCEDURE_NAME.fullmatch(procedure):
            raise ValueError(f"Not a procedure name: {procedure!r}")
        url = f"{self.base_url}/trpc/{procedure}"
        body = None
        if method == "GET":
            url += "?input=" + urllib.parse.quote(json.dumps(input_data if input_data is not None else {}))
        else:
            body = input_data if input_data is not None else {}
        res = self._send(method, url, body, resend, token, with_customer)
        if res.status_code == 401 and token is None and self.email and self.pw and procedure != "auth.login":
            self.token = self.get_token(self.email, self.pw)
            res = self._send(method, url, body, resend, token, with_customer)
        try:
            payload = res.json()
        except ValueError:
            payload = None
        error = payload.get('error') if isinstance(payload, dict) else None
        if res.status_code >= 400 or error or not isinstance(payload, dict):
            message = error.get('message') if isinstance(error, dict) else res.text[:300]
            raise TRPCError(f"{procedure} failed with HTTP {res.status_code}: {message}")
        return (payload.get('result') or {}).get('data')

    def _send(self, method, url, body, resend, token, with_customer):
        headers = {}
        if token or self.token:
            headers["Authorization"] = token or self.token
        if with_customer and self.customer_id:
            headers["Customer"] = self.customer_id
        attempts = 3 if resend else 1
        for attempt in range(attempts):
            try:
                res = requests.request(method, url, json=body, headers=headers, timeout=REQUEST_TIMEOUT_S)
            except requests.exceptions.ConnectionError:
                if attempt == attempts - 1:
                    raise
            else:
                if res.status_code not in RETRY_STATUSES or attempt == attempts - 1:
                    return res
            time.sleep(2 ** attempt)

    def change_client_ws(self, ws):
        self.customer_id = ws

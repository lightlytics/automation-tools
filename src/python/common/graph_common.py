import datetime
import json
import requests
import time


class GraphCommon(object):
    def __init__(self, url, email, pw, customer_id=None, otp=None):
        """ Initialize GraphCommon class to graph functions.
            :param url (str)            - The url of the environment.
            :param email (str)          - The email for login.
            :param pw (str)             - The password for login.
            :param otp (str)            - 2FA token.
            :param customer_id (str)    - The customer ID for operations; Defaults to the Demo Customer ID.
        """
        self.url = url
        self.email = email
        self.pw = pw
        self.token = self.get_token(email, pw)
        if otp:
            self.token = self.get_token_otp(otp, self.token)
        time.sleep(2)
        self.customer_id = customer_id or self.get_customer_id()

    def get_token(self, email, pw):
        """ Get token from graph.
            :param email (str)  - The email for login.
            :param pw (str)     - The password for login.
            :returns (str)      - Token.
        """
        payload_operation = "Login"
        payload_vars = {"credentials": {"email": email, "password": pw}}
        query = "mutation Login($credentials: Credentials){login(credentials: $credentials){access_token }}"
        payload = self.create_graph_payload(payload_operation, payload_vars, query)
        try:
            res = requests.post(self.url, json=payload)
        except Exception as e:
            raise Exception(f"URL doesn't exist --> {self.url}, error: {e}")
        if 'errors' not in res.text:
            eval_res = json.loads(res.text)
            self.token = 'Bearer ' + eval_res['data']['login']['access_token']
            return self.token
        else:
            err = res.text
            raise Exception(json.loads(str(err))['errors'][0]['message'])

    def get_token_otp(self, otp, token):
        """ Get token using 2FA.
            :param otp (str)    - The OTP code provided by the user.
            :param token (str)  - Token received after successful login.
            :returns (str)      - New Bearer Token.
        """
        payload_operation = "authenticateTwoFactor"
        query = "mutation authenticateTwoFactor($method: TwoFactorState, $user_code: String){" \
                "authenticateTwoFactor(method: $method, user_code: $user_code){access_token refresh_token __typename}}"
        payload_vars = {"method": "SECURED_TOTP", "user_code": otp}
        payload = self.create_graph_payload(payload_operation, payload_vars, query)
        res = requests.post(self.url, json=payload, headers={"Authorization": token})
        if 'errors' not in res.text:
            eval_res = json.loads(res.text)
            return 'Bearer ' + eval_res['data']['authenticateTwoFactor']['access_token']
        else:
            err = res.text
            raise Exception(json.loads(str(err))['errors'][0]['message'])

    def get_customer_id(self, email=None, pw=None, token=None):
        """ Get customer id from graph.
            :param email (str)  - The email for login.
            :param pw (str)     - The password for login.
            :param token (str)  - Token.
            :returns (str)      - The first customer id.
        """
        return self.get_all_customer_ids(email, pw, token)[0]

    def get_all_customer_ids(self, email=None, pw=None, raw=False):
        """ Get all customer ids from graph.
            :param email (str)  - The email for login.
            :param pw (str)     - The password for login.
            :param raw (bool)   - Whether the return the entire result not just the IDs.
            :returns (str)      - Customer ids list.
        """
        email = email or self.email
        pw = pw or self.pw
        token = self.token or self.get_token(email, pw)
        payload_vars = {"credentials": {"email": email, "password": pw}}
        query = "{workspaces { _id: customer_id display_name: customer_name role __typename}}"
        payload = self.create_graph_payload(None, payload_vars, query)
        try:
            res = requests.post(self.url, json=payload, headers={"Authorization": token})
        except Exception as e:
            raise Exception(f"URL doesn't exist --> {self.url}, error: {e}")
        if 'errors' not in res.text:
            eval_res = json.loads(res.text)
            if raw:
                return eval_res['data']['workspaces']
            else:
                return [w['_id'] for w in eval_res['data']['workspaces']]
        else:
            raise Exception(f"Could not get customer id, error: {res.text}")

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
    def get_accounts(self):
        """ Get all accounts.
            :returns (list) - Integrations in the environment.
        """
        operation = 'Accounts'
        query = "query Accounts{accounts{_id account_type cloud_account_id cloud_regions display_name " \
                "external_id status template_url collection_template_url remediation_template_url realtime_regions{region_name " \
                "template_version __typename}vpc_flow_logs{flow_logs_token should_collect_flow_logs __typename} " \
                "lightlytics_collection_token stack_region account_aliases cost{status details operation " \
                "template_version role_arn bucket_arn cur_prefix last_timestamp __typename}__typename}}"
        return self.graph_query(operation, {}, query)['data']['accounts']

    def get_account_response_config(self, cloud_account_id):
        """ Get all accounts.
            :returns (list) - Integrations in the environment.
        """
        operation = 'AccountAutoRemediationConfig'
        payload_vars = {"cloud_account_id": cloud_account_id}
        query = "query AccountAutoRemediationConfig($cloud_account_id: ID) {account(id: $cloud_account_id) {_id remediation { status template_version external_id role_arn stack_id }}}"
        return self.graph_query(operation, payload_vars, query)['data']['account']

    def create_account(self, account_id, regions_list, display_name=None):
        """ Create account.
            :param account_id (str)     - Specific AWS account ID.
            :param regions_list (list)  - Regions which the user want to add.
            :param display_name (str)    - Display name for AWS Account; Defaults to None.
            :returns (dict)             - Account details.
        """
        payload_operation = "CreateAccount"
        payload_vars = {"account": {"account_type": "AWS",
                                    "cloud_account_id": account_id,
                                    "cloud_regions": regions_list,
                                    "stack_region": regions_list[0]}}
        if display_name:
            payload_vars['account']["display_name"] = display_name
        query = "mutation CreateAccount($account: AccountInput){createAccount(account: $account){_id __typename}}"
        res = self.graph_query(payload_operation, payload_vars, query)
        if "errors" in res:
            print("Something went wrong with creating an account / Account already exists")
            print(res)
            return False
        else:
            return True

    def create_response_template(self, cloud_account_id):
        """ Create response template.
            :param account_id (str)     - Specific AWS account ID.
            :returns (dict)             - Account details.
        """
        payload_operation = "GenerateAutoRemediationTemplate"
        payload_vars = {"cloud_account_id": cloud_account_id}
        query = "mutation GenerateAutoRemediationTemplate($cloud_account_id: ID!) {" \
                    "remediation_generate_template(cloud_account_id: $cloud_account_id)}"
        res = self.graph_query(payload_operation, payload_vars, query)
        if "errors" in res:
            print("Something went wrong with creating an account / Account already exists")
            print(res)
            return False
        else:
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
        specific_account = next(account for account in accounts if account["cloud_account_id"] == account_id)
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
        payload_operation = "updateAccount"
        payload_vars = {"id": self.get_specific_account(account_id)["_id"],
                        "account": {"cloud_regions": regions_list}}
        query = "mutation updateAccount($id: ID!, $account: AccountUpdateInput) {updateAccount(id: $id, account:" \
                " $account) {_id display_name cloud_regions template_url collection_template_url __typename }}"
        res = self.graph_query(payload_operation, payload_vars, query)
        if "errors" in res:
            raise Exception(f"Something else occurred, error: {res.text}")
        return res["data"]["updateAccount"]

    def update_account_display_name(self, account_id, display_name):
        """ Update a specific account display name.
            :param account_id (str)     - Specific AWS account ID.
            :param display_name (list)  - Display name to change to.
            :returns (dict)             - Account details.
        """
        payload_operation = "updateAccount"
        query = "mutation updateAccount($id: ID!, $account: AccountUpdateInput)" \
                "{updateAccount(id: $id, account: $account)" \
                "{_id display_name cloud_regions template_url collection_template_url __typename}}"
        payload_vars = {"id": self.get_specific_account(account_id)["_id"],
                        "account": {"display_name": display_name}}
        res = self.graph_query(payload_operation, payload_vars, query)
        if "errors" in res:
            raise Exception(f"Something else occurred, error: {res.text}")
        return res["data"]["updateAccount"]

    # Resources methods
    def get_resources(self, parent_data=False):
        """ Get resources details.
            :param parent_data (boolean)    - Expend/not details; Defaults to False.
            :returns (dict/list)            - resources details.
        """
        operation = "ResourcesQuery"
        query = "query ResourcesQuery{resources{id type display_name is_public state parent __typename}}"
        resources = self.graph_query(operation, {}, query)['data']['resources']
        if not parent_data:
            try:
                return [r['id'] for r in resources]
            except TypeError:
                raise Exception("Couldn't fetch resources")
        else:
            return resources

    def get_resources_by_account(self, account_id):
        """ Get resources details by account.
            :returns (dict/list)            - resources details.
        """
        operation = "InventorySummaryQuery"
        query = ("query InventorySummaryQuery($account_id: [ID]){inventorySummary(account_id: $account_id){"
                 "resource_type count}}")
        return self.graph_query(operation, {"account_id": [account_id]}, query)['data']['inventorySummary']

    def get_resources_by_type(self, resource_type, get_only_ids=False):
        """ Get resources details by type.
            :param resource_type (str)      - Resource type.
            :param get_only_ids (boolean)   - Return only IDs.
            :returns (dict/list)            - resources details.
        """
        operation = "ResourceSearch"
        query = "query ResourceSearch($includeTags: Boolean!, $phrase: String, $filters: SearchFilters, $skip: Int, " \
                "$limit: Int){search(phrase: $phrase, filters: $filters, skip: $skip, limit: $limit){totalCount " \
                "results{id type display_name addresses is_public state network_interfaces{id addresses __typename} " \
                "tags @include(if: $includeTags){Key Value __typename}cloud_tags @include(if: $includeTags){Key " \
                "Value __typename}__typename}__typename}}"
        variables = {"includeTags": False, "phrase": "",
                     "filters": {"resource_type": [resource_type], "attributes": []}, "skip": 0}
        resources = self.graph_query(operation, variables, query)['data']['search']['results']
        if get_only_ids:
            return [r['id'] for r in resources]
        return resources

    def general_resource_search(self, search_query, get_only_ids=False):
        """ Get resources details by type.
            :param search_query (str)       - query to search by.
            :param get_only_ids (boolean)   - Return only IDs.
            :returns (dict/list)            - resources details.
        """
        operation = "ResourceSearch"
        query = "query ResourceSearch($includeTags: Boolean!, $phrase: String, $filters: SearchFilters, $skip: Int, " \
                "$limit: Int){search(phrase: $phrase, filters: $filters, skip: $skip, limit: $limit){totalCount " \
                "results{id type display_name addresses is_public state network_interfaces{id addresses __typename} " \
                "tags @include(if: $includeTags){Key Value __typename}cloud_tags @include(if: $includeTags){Key " \
                "Value __typename}__typename}__typename}}"
        variables = {"includeTags": False, "phrase": search_query, "skip": 0}
        resources = self.graph_query(operation, variables, query)['data']['search']['results']
        if get_only_ids:
            return [r['id'] for r in resources]
        return resources

    def get_resources_type_count_by_account(self, resource_type, account):
        """ Get resources count by account.
            :param account (str)        - Account ID.
            :param resource_type (str)  - Resource type.
            :returns (int)              - Resources count.
        """
        operation = "InventorySummaryQuery"
        query = "query InventorySummaryQuery($account_id: String){inventorySummary(account_id: $account_id){" \
                "resource_type count __typename}}"
        results = self.graph_query(operation, {"account_id": account}, query)['data']['inventorySummary']
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
        operation = 'ResourceConfiguration'
        query = "query ResourceConfiguration($id: ID, $timestamp: Timestamp){" \
                "configuration(resource_id: $id, timestamp: $timestamp){raw translated impact_paths __typename}}"
        variables = {"id": resource_id}

        if get_from_latest_timestamp:
            latest_timestamp = self.get_resource_configuration_latest_version_by_id(resource_id)
            query = "query ResourceConfiguration($id: ID, $timestamp: Timestamp){" \
                    "configuration(resource_id: $id, timestamp: $timestamp){raw translated impact_paths __typename}}"
            variables["timestamp"] = latest_timestamp

        res = self.graph_query(operation, variables, query)
        if 'errors' in res:
            raise Exception(f'Something went wrong, result: {res}')
        if raw:
            return res['data']['configuration']['raw']
        return res['data']['configuration']['translated']

    def get_resource_configuration_latest_version_by_id(self, resource_id):
        """ Get configuration details by resource's ID.
            :param resource_id (str)                - Specific resource's ID.
            :returns (dict)                         - Configuration latest version timestamp.
        """
        operation = 'ResourceConfigurationVersions'
        query = "query ResourceConfigurationVersions($id: ID, $skip: Int, $limit: Int)" \
                "{configuration_versions(resource_id: $id, skip: $skip, limit: $limit){timestamp provider __typename}}"
        res = self.graph_query(operation, {"id": resource_id, "skip": 0, "limit": 1}, query)
        if 'errors' in res:
            raise Exception(f'Something went wrong, result: {res}')
        try:
            return res['data']['configuration_versions'][0]['timestamp']
        except IndexError:
            raise Exception("Can't find latest version of the configuration, fatal error")

    def get_resource_parents_by_id(self, resource_id):
        """ Get parent by resource's ID.
            :param resource_id (str)    - Specific resource's ID.
            :returns (list)             - Resource parents.
        """
        operation = 'ResourceQuery'
        query = "query ResourceQuery($resource_id: ID, $simulation_timestamp: Timestamp){" \
                "resource(resource_id: $resource_id simulation_timestamp: $simulation_timestamp return_deleted: true)" \
                "{parents}}"
        return self.graph_query(operation, {"resource_id": resource_id}, query)['data']['resource']['parents']

    def get_resource_metadata(self, resource_id):
        """ Get resource metadata.
            :param resource_id (str)    - Specific resource's ID.
            :returns (str)              - Account ID.
        """
        operation = 'ResourceQuery'
        query = "query ResourceQuery($resource_id: ID, $simulation_timestamp: Timestamp){resource(resource_id: " \
                "$resource_id simulation_timestamp: $simulation_timestamp return_deleted: true){id type display_name " \
                "end_timestamp region parent account_id __typename}}"
        return self.graph_query(operation, {"resource_id": resource_id}, query)['data']['resource']

    def get_resource_ancestors(self, resource_id):
        """ Get resource ancestors.
            :param resource_id (str)    - Specific resource's ID.
            :returns (dict)             - Ancestors information.
        """
        operation = 'ResourceAncestors'
        query = "query ResourceAncestors($resourceId: ID!){resourceAncestors(resource_id: $resourceId){id type " \
                "display_name parent __typename}}"
        return self.graph_query(operation, {"resourceId": resource_id}, query)['data']['resourceAncestors']

    def get_resource_account_id(self, resource_id):
        """ Get resource account ID.
            :param resource_id (str)    - Specific resource's ID.
            :returns (str)              - Account ID.
        """
        operation = 'ResourceQuery'
        query = "query ResourceQuery($resource_id: ID, $simulation_timestamp: Timestamp){" \
                "resource(resource_id: $resource_id simulation_timestamp: $simulation_timestamp return_deleted: true)" \
                "{account_id}}"
        return self.graph_query(operation, {"resource_id": resource_id}, query)['data']['resource']['account_id']

    def get_resource_associated_resources(self, resource_id):
        """ Get resource associated resources.
        """
        operation = 'SearchAssociatedResources'
        query = "query SearchAssociatedResources($filters: SearchFilters, $simulation_timestamp: Timestamp, " \
                "$skip: Int, $limit: Int){search(filters: $filters simulation_timestamp: $simulation_timestamp " \
                "skip: $skip limit: $limit){results{id type display_name __typename}__typename}}"
        variables = {"filters": {"associated_resource_id": resource_id}}
        return self.graph_query(operation, variables, query)['data']['search']['results']

    def resources_search(self, account, resource_type, tags=None):
        """ Search resources by account and types.
            :param account (str)        - Account to search in.
            :param resource_type (str)  - Resource type.
            :param tags (list)          - List of tags to filter by.
            :returns (list)             - List of resources.
        """
        operation = 'ResourceSearch'
        query = "query ResourceSearch($includeTags: Boolean!, $phrase: String, $filters: SearchFilters, $skip: " \
                "Int, $limit: Int){search(phrase: $phrase, filters: $filters, skip: $skip, limit: $limit)" \
                "{totalCount results{id type display_name addresses is_public state network_interfaces{id " \
                "addresses __typename}tags @include(if: $includeTags){Key Value __typename}cloud_tags @include" \
                "(if: $includeTags){Key Value __typename}__typename}__typename}}"
        variables = {
            "includeTags": True,
            "phrase": "",
            "filters": {
                "resource_type": [resource_type],
                "account_id": account,
                "attributes": []
            },
            "skip": 0, "limit": 0
        }
        if tags:
            variables["filters"]["tags"] = tags
        return self.graph_query(operation, variables, query)['data']['search']['results']

    # Arch Standards methods
    def get_all_rules(self):
        """ Get all "standards" rules.
            :returns (list) - Rules.
        """
        operation = 'RulesQuery'
        query = "query RulesQuery($filters: RuleFilters, $eventId: String, $resourceId: String, " \
                "$isRemediation: Boolean, $simulation: Boolean){rules(filters: $filters event_id: $eventId " \
                "resource_id: $resourceId is_remediation: $isRemediation is_simulation: $simulation){" \
                "total_count results{id name creation_date created_by category severity description labels " \
                "compliance status state rule_type fail_simulation exclusions_count __typename}__typename}}"
        return self.graph_query(operation, {}, query)['data']['rules']['results']

    def get_rules_by_compliance(self, compliance):
        """ Get all "standards" rules by compliance.
            :returns (list) - Compliance rules.
        """
        return [r for r in self.get_all_rules() if compliance in r['compliance']]

    def get_rule_metadata(self, rule_id):
        """ Get rule metadata.
            :returns (dict) - Rule metadata.
        """
        operation = 'RuleQuery'
        query = "query RuleQuery($id: ID){rule(id: $id){...RuleFields __typename}}fragment RuleFields on Rule" \
                "{id name status state category severity description remediation labels compliance rule_type subject " \
                "action path_source_predicate_equals_match path_intermediate_predicate_equals_match " \
                "path_destination_predicate_equals_match path_source_predicate{...ConditionFields __typename}" \
                "path_intermediate_predicate{...ConditionFields __typename}path_destination_predicate{" \
                "...ConditionFields __typename}resource_predicate{...ConditionFields __typename}fail_simulation ports" \
                "{start end protocol __typename}creation_date created_by __typename}" \
                "fragment ConditionFields on ResourceCondition{resource_id resource_type attributes{operand " \
                "attributes_list{...AttributeFields attributes_list{...AttributeFields attributes_list{" \
                "...AttributeFields attributes_list{...AttributeFields attributes_list{...AttributeFields " \
                "attributes_list{...AttributeFields __typename}__typename}__typename}__typename}__typename}" \
                "__typename}__typename}tags{operand attributes_list{...AttributeFields attributes_list{" \
                "...AttributeFields attributes_list{...AttributeFields attributes_list{...AttributeFields " \
                "attributes_list{...AttributeFields attributes_list{...AttributeFields __typename}__typename}" \
                "__typename}__typename}__typename}__typename}__typename}locations{location_type location_value " \
                "__typename}__typename}fragment AttributeFields on ConditionAttribute{name value match_type operand " \
                "__typename}"
        return self.graph_query(operation, {"id": rule_id}, query)["data"]["rule"]

    def get_rule_violations(self, rule_id):
        """ Get all rule violations.
            :returns (list) - Rule violations.
        """
        operation = 'RuleViolations'
        query = "query RuleViolations($rule_id: ID!, $filter_inventory: RuleViolationFilterInventory, $skip: " \
                "Int, $limit: Int){ruleViolations(rule_id: $rule_id filter_inventory: $filter_inventory skip: " \
                "$skip limit: $limit){total_count results __typename}}"
        variables = {"rule_id": rule_id, "filter_inventory": {}, "skip": 0, "limit": 0}
        violations = self.graph_query(operation, variables, query)['data']['ruleViolations']['results']
        return violations

    def export_csv_rule(self, rule_id):
        """ Get CSV formatted data regarding rule violations.
            :returns (csv) - Rule violations.
        """
        operation = "RuleViolationsCsv"
        query = "query RuleViolationsCsv($rule_id: ID!){ruleCsv(rule_id: $rule_id){rule_name description category " \
                "severity labels compliance date violation_count violations{resource_id resource_name resource_type " \
                "account_display_name account_id region vpc_id tags monthly_cost __typename}__typename}}"
        return self.graph_query(operation, {"rule_id": rule_id}, query)['data']['ruleCsv']

    def get_violation_cost_predicted_savings(self, rule_id, resource_id):
        """ Get Predicted Savings for a specific rule violation.
            :returns (int) - Predicted Savings for the violation.
        """
        operation = "RuleViolationCost"
        query = "query RuleViolationCost($rule_id: String, $resource_ids: [String]){resourcePredictedMontlyCost" \
                "(rule_id: $rule_id, resource_ids: $resource_ids){results{predicted_monthly_cost id __typename}" \
                "__typename}}"
        variables = {"rule_id": rule_id, "resource_ids": [resource_id], "skip": False}
        return self.graph_query(
            operation, variables, query)['data']['resourcePredictedMontlyCost']['results'][0]['predicted_monthly_cost']

    def get_compliance_standards(self):
        """ Get all compliance standards.
            :returns (list) - Available compliance standards.
        """
        operation = 'Compliances'
        query = "query Compliances{compliance{results{compliance __typename}__typename}}"
        return [c['compliance'] for c in self.graph_query(operation, {}, query)['data']['compliance']['results']]

    # Cost methods
    def check_cost_integration(self):
        """
        Check whether cost is integrated or not.
        :returns (bool) - True/False if cost integrated.
        """
        operation = "CostDataStatusQuery"
        query = "query CostDataStatusQuery{cost_data_status{status __typename}}"
        integration_status = self.graph_query(operation, {}, query)["data"]["cost_data_status"]["status"]
        return True if integration_status == "data_exists" else False

    def get_cost_chart(self, from_timestamp, to_timestamp, group_by=None, ignore_discounts=None):
        """
        Get the cost information.
        :returns (list) - Cost data.
        """
        operation = "cost_reports"
        query = "query cost_reports($filters: CostReportsFilters, $group_bys: [CostReportsGroupBy], " \
                "$period: CostReportsPeriod) {cost_reports(filters: $filters, group_bys: $group_bys, period: $period)" \
                "{results{day month year account region resource_type product_family pricing_term total_cost}," \
                "total_count}}"
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
        if ignore_discounts:
            variables["total_cost_type"] = ignore_discounts
        return self.graph_query(operation, variables, query)["data"]["cost_reports"]["results"]

    def get_cost_chart_main_pipeline(self, from_timestamp, to_timestamp, group_by=None):
        """
        Get the cost information.
        :returns (list) - Cost data.
        """
        operation = "CostChartIndexQuery"
        query = "query CostChartIndexQuery($skip: Int, $limit: Int, $filters: CostFilters, $anti_filters: " \
                "CostAntiFilters, $sort: CostSort, $groupBy: [CostGroupBy], $groupByTagKey: String, " \
                "$trend_period: CostTrendPeriod, $trend_range: TrendRange){cost(filters: $filters anti_filters: " \
                "$anti_filters group_bys: $groupBy trend_period: $trend_period trend_range: $trend_range sort: $sort " \
                "skip: $skip limit: $limit group_by_tag_key: $groupByTagKey){total_count results{is_real_resource_id " \
                "timestamp total_cost total_direct_cost total_indirect_cost preceding_total_cost " \
                "preceding_total_direct_cost predicted_cost trend_difference trend_percentage " \
                "trend_difference_direct trend_percentage_direct trend_difference_indirect trend_percentage_indirect " \
                f"resource_type account region {group_by} " \
                "__typename}__typename}}"
        variables = {
            "filters": {
                "from_timestamp": from_timestamp,
                "to_timestamp": to_timestamp
            },
            "sort": {
                "field": "total_direct_cost",
                "direction": "desc"
            },
            "groupBy": [
                "resource_type", "region", "account", group_by
            ],
            "skip": 0,
            "limit": 99999
        }
        return self.graph_query(operation, variables, query)['data']['cost']['results']

    def get_cost_rules(self):
        """
        Get Cost-related rules.
        :returns (list) - Cost Rules.
        """
        operation = "RulesQuery"
        query = "query RulesQuery($filters: RuleFilters, $eventId: String, $resourceId: String, $isRemediation: " \
                "Boolean, $simulation: Boolean){rules(filters: $filters event_id: $eventId resource_id: $resourceId " \
                "is_remediation: $isRemediation is_simulation: $simulation){total_count results{id name " \
                "creation_date created_by category severity description labels compliance status state rule_type " \
                "fail_simulation exclusions_count __typename}__typename}}"
        all_rules = self.graph_query(operation, {}, query)["data"]["rules"]["results"]
        return [r for r in all_rules if r["category"] == "Cost" and r["status"] == "active"]

    def get_recommendations_history_by_date(self, req_date):
        """
        Get recommendations history by date.
        :param req_date (str)   - Date; format - YYYY/MM/YY.
        :returns (dict)         - Recommendations history.
        """
        query = "query ($date: String){costViolationsHistory(date:$date)}"
        return self.graph_query(None, {"date": req_date}, query)['data']['costViolationsHistory']['data']

    def get_all_recommendations_history_dates(self):
        """
        Get recommendations history by date.
        :returns (list) - Recommendations history available dates.
        """
        res = self.graph_query(None, {}, "query {costViolationsHistoryDates}")['data']['costViolationsHistoryDates']
        return [d["date"] for d in res]

    def get_kubernetes_integrations(self, get_only_names=False):
        """
        Get Kubernetes integrations.
        :returns (list) - K8s integration list.
        """
        operation = "Kubernetes"
        query = ("query Kubernetes{kubernetes{"
                 "_id type display_name creation_date status collection_token eks_arn __typename}}")
        res = self.graph_query(operation, {}, query)['data']['kubernetes']
        if get_only_names:
            return [ki['display_name'] for ki in res]
        return res

    def create_kubernetes_integration(self, eks_arn, display_name):
        """
        Create Kubernetes integration.
        :returns (list) - K8s integration list.
        """
        operation = "CreateKubernetes"
        query = "mutation CreateKubernetes($kubernetes: CreateKubernetesInput){createKubernetes(kubernetes: " \
                "$kubernetes){_id collection_token __typename}}"
        variables = {"kubernetes": {"display_name": display_name, "eks_arn": eks_arn}}
        res = self.graph_query(operation, variables, query)
        if "errors" in res:
            print(f"Failed to create integration - {res['errors'][0]['message']}")
            return False
        else:
            return res['data']['createKubernetes']

    def get_kubernetes_cost(self, cluster_arn, from_ts, to_ts):
        """
        Get EKS cost.
        """
        operation = "CostCurrentTotalQuery"
        query = "query CostCurrentTotalQuery($skip: Int, $limit: Int, $filters: CostK8sFilters, $anti_filters: " \
                "CostK8sFilters, $sort: K8sCostSort, $groupBy: [K8sCostGroupBy], $groupByTagKey: String, " \
                "$trend_period: CostTrendPeriod, $trend_range: TrendRange){cost_k8s(filters: $filters anti_filters: " \
                "$anti_filters group_bys: $groupBy trend_period: $trend_period trend_range: $trend_range sort: " \
                "$sort skip: $skip limit: $limit group_by_tag_key: $groupByTagKey){total_count results{timestamp " \
                "total_cost trend_difference trend_percentage cpu_cost cpu_max_usage cpu_average_usage " \
                "cpu_requested ram_cost ram_max_usage ram_average_usage ram_requested volume_cost traffic_cost " \
                "efficiency predicted_cost cpu_charge_average memory_charge_average __typename}__typename}}"
        variables = {
            "filters": {
                "cluster": cluster_arn,
                "from_timestamp": from_ts,
                "to_timestamp": to_ts
            },
            "groupBy": [],
            "skip": 0,
            "trend_period": "month"
        }
        res = self.graph_query(operation, variables, query)
        if "errors" in res:
            print(f"Failed to create integration - {res['errors'][0]['message']}")
            return False
        else:
            return res['data']['cost_k8s']

    def get_kubernetes_cluster_cost(self, cluster_arn, from_ts, to_ts):
        """
        Get EKS cluster cost.
        """
        operation = "CostKubernetesClustersQuery"
        query = "query CostKubernetesClustersQuery($filters: CostK8sClusterFilters, $trend_period: CostTrendPeriod, " \
                "$trend_range: TrendRange){cost_k8s_clusters(filters: $filters trend_period: $trend_period " \
                "trend_range: $trend_range){total_cluster_cost total_cluster_idle_cost trend_percentage_cluster_cost " \
                "trend_percentage_cluster_idle_cost __typename}}"
        variables = {
            "filters": {
                "cluster": cluster_arn,
                "from_timestamp": from_ts,
                "to_timestamp": to_ts
            },
            "trend_period": "month"
        }
        res = self.graph_query(operation, variables, query)
        if "errors" in res:
            print(f"Failed to create integration - {res['errors'][0]['message']}")
            return False
        else:
            return res['data']['cost_k8s_clusters']

    def delete_eks_integration(self, integration_id):
        """
        Delete EKS integration.
        """
        operation = "DeleteKubernetes"
        query = "mutation DeleteKubernetes($id: ID!){deleteKubernetes(id: $id)}"
        variables = {"id": integration_id}
        res = self.graph_query(operation, variables, query)
        if "errors" in res:
            print(f"Failed to create integration - {res['errors'][0]['message']}")
            return False
        else:
            return True

    # CVEs
    def get_cves(self, public_exposed=False, exploit_available=False, fix_available=False, cve_id=None, source=None,
                 packages=None, resource_id=None, resource_type=None, severity=None):
        """ Get CVEs.
            :returns (list) - CVEs information.
        """
        operation = 'CVEsMainQuery'
        variables = {
            'filters': {
                "internet_exposed": public_exposed,
                "exploit_available": exploit_available,
                "fix_available": fix_available
            },
            'sort_by': 'cvss_score',
            'sort_order': -1
        }
        query = ("query CVEsMainQuery($filters: CVEFilters, $skip: Int, $limit: Int, $sort_by: CVESortField, "
                 "$sort_order: Int){cves(filters: $filters skip: $skip limit: $limit sort_by: $sort_by "
                 "sort_order: $sort_order){total_count results{attack_vector cve_id cve_sources severity cvss_score "
                 "packages exploit_available internet_exposed affected_resources_count fix_available fixed_in_version "
                 "epss_score cisa_kev{action date_added due_date __typename}published_date discovery_timestamp "
                 "__typename}__typename}}")
        if cve_id:
            variables['filters']['cve_id'] = cve_id
        if source:
            variables['filters']['source'] = source
        if packages:
            variables['filters']['packages'] = packages
        if resource_id:
            variables['filters']['resource_id'] = resource_id
        if resource_type:
            variables['filters']['resource_type'] = resource_type
        if severity:
            variables['filters']['severity'] = severity
        return self.graph_query(operation, variables, query)['data']['cves']['results']

    def get_affected_resources(self, cve_id):
        operation = 'CVEResources'
        variables = {"filters": {"cve_ids": [cve_id]}}
        query = ("query CVEResources($filters: VulnerableResourcesFilters, $skip: Int, $limit: Int){cve_resources("
                 "filters: $filters, skip: $skip, limit: $limit){total_count results{account_id resource_id "
                 "resource_type container_images exposure_risk exposure_risk_description internet_exposed __typename"
                 "}__typename}}")
        return self.graph_query(operation, variables, query)['data']['cve_resources']['results']

    # Flow logs methods
    def get_flow_logs(self, skip=0, limit=999, action=None, dst_resource_id=None, start_time=None, end_time=None,
                      src_public=False, protocols=None):
        operation = 'IPTraffic'
        query = ("query IPTraffic($filters: ConnectionsFilters, $limit: Int, $skip: Int){IPTraffic(filters: $filters, "
                 "limit: $limit, skip: $skip){results{src_port src_resource_id src_resource_type "
                 "src_resource_display_name src_ip dst_port dst_resource_id dst_resource_type "
                 "dst_resource_display_name dst_ip start end bytes action s3_action protocol application_name "
                 "application_desc src_geo_iso dst_geo_iso __typename}totalCount __typename}}")

        variables = {
            "skip": skip,
            "limit": limit,
            "filters": {}
        }
        if start_time or end_time:
            variables['filters']['start'] = dict()
        if src_public:
            variables['filters']['src_ip_filter'] = dict()

        if action:
            variables['filters']['action'] = [action]
        if dst_resource_id:
            variables['filters']['dst_resource_id'] = dst_resource_id
        if start_time:
            variables['filters']['start']['gte'] = start_time
        if end_time:
            variables['filters']['start']['lte'] = end_time
        if src_public:
            variables['filters']['src_ip_filter']['is_internet'] = True
        if protocols:
            variables['filters']['protocol'] = protocols.split(",")
        return self.graph_query(operation, variables, query)['data']['IPTraffic']['results']

    def get_detections(self):
        operation = 'Detections'
        variables = {"filters": {"acknowledged": True}}
        query = ("query Detections($filters: DetectionsFilters, $sort: DetectionsSort, $skip: Int, $limit: Int){"
                 "get_detections(filters: $filters, sort: $sort, skip: $skip, limit: $limit){total_count results{_id "
                 "timestamp activity_type source account_id anomaly_severity resource_id resource_type "
                 "mitre_categories acknowledged acknowledgement_details{timestamp user reason __typename}signal_types "
                 "__typename}__typename}}")
        return self.graph_query(operation, variables, query)['data']['get_detections']['results']

    def get_detection_enrichment(self, detection_id):
        operation = 'Detection'
        variables = {"filters": {"_id": [detection_id]}}
        query = """query Detection($filters: DetectionsFilters) {
                      get_detections(filters: $filters) {
                        total_count
                        results {
                          _id
                          timestamp
                          activity_type
                          source
                          account_id
                          anomaly_severity
                          cluster
                          namespace
                          resource_id
                          resource_type
                          resource_cluster
                          resource_namespace
                          resource_deployment
                          mitre_categories
                          acknowledged
                          signal_types
                          session_list {
                            ip_address
                            access_key
                            user_agent
                            country_code_iso
                            mfa
                            __typename
                          }
                          acknowledgement_details {
                            timestamp
                            user
                            reason
                            __typename
                          }
                          external_id
                          external_url
                          json_data
                          signals {
                            signal_type
                            ... on MaliciousIpSignal {
                              malicious_ip_records {
                                ...IpRecordFragment
                                __typename
                              }
                              __typename
                            }
                            ... on TorIpSignal {
                              tor_ip_records {
                                ...IpRecordFragment
                                __typename
                              }
                              __typename
                            }
                            ... on PentestToolSignal {
                              agents
                              __typename
                            }
                            ... on UnusualActivityTimeSignal {
                              activity_time
                              __typename
                            }
                            ... on UnusualActionTypeSignal {
                              resource_types_by_resources_actions {
                                resource_type
                                anomalous_actions {
                                  ...AnomalousActionFragment
                                  __typename
                                }
                                __typename
                              }
                              __typename
                            }
                            ... on AnomalousGeoLocationSignal {
                              locations
                              __typename
                            }
                            ... on ActivityInUnusualAwsRegionSignal {
                              unusual_activities_by_regions {
                                location
                                unusual_resource_types_actions {
                                  resource_type
                                  anomalous_actions {
                                    ...AnomalousActionFragment
                                    __typename
                                  }
                                  __typename
                                }
                                __typename
                              }
                              __typename
                            }
                            ... on AnomalousTrafficVolumeSignal {
                              volume_size
                              plot_coords {
                                ...CoordinatesFragment
                                __typename
                              }
                              top_destination_ips {
                                ...IpRecordFragment
                                __typename
                              }
                              __typename
                            }
                            ... on AnomalousOutboundConnectionSignal {
                              destination_ips {
                                ...IpRecordFragment
                                __typename
                              }
                              __typename
                            }
                            ... on PossiblePortScanSignal {
                              plot_coords {
                                ...CoordinatesFragment
                                __typename
                              }
                              __typename
                            }
                            ... on PossibleInternalIpScanSignal {
                              plot_coords {
                                ...CoordinatesFragment
                                __typename
                              }
                              __typename
                            }
                            ... on AnomalousCountOfRejectedFlowsSignal {
                              plot_coords {
                                ...CoordinatesFragment
                                __typename
                              }
                              __typename
                            }
                            ... on AnomalousDataStoreConnectivitySignal {
                              resource_ids
                              resource_types
                              __typename
                            }
                            ... on AnomalousCountOfGetObjectsSignal {
                              plot_coords {
                                ...CoordinatesFragment
                                __typename
                              }
                              __typename
                            }
                            ... on UnusualCostSpikeSignal {
                              service
                              plot_coords {
                                ...CoordinatesFragment
                                __typename
                              }
                              __typename
                            }
                            ... on UnusualActivityTimeSignal {
                              activity_time
                              __typename
                            }
                            ... on DetectionRuleActivitySignal {
                              rule_id
                              rule_name
                              description
                              type
                              window_start
                              window_end
                              plot_coords {
                                x_coords
                                y_coords
                                __typename
                              }
                              custom_config {
                                log_type
                                detection_field
                                __typename
                              }
                              identityml_config {
                                match_type
                                action
                                __typename
                              }
                              __typename
                            }
                            ... on GenericThirdPartyActivitySignal {
                              name
                              description
                              mitre_categories
                              __typename
                            }
                            __typename
                          }
                          __typename
                        }
                        __typename
                      }
                    }
                    fragment IpRecordFragment on IpRecord {
                      ip_address
                      severity
                      hosts
                      ports
                      initiated_session
                      vol_traffic
                      __typename
                    }
                    fragment AnomalousActionFragment on AnomalousAction {
                      action
                      mitre_category
                      resource_ids
                      sub_resource
                      regions
                      destinations
                      request_uri
                      __typename
                    }
                    fragment CoordinatesFragment on Coordinates {
                      x_coords
                      y_coords
                      __typename
                    }
"""
        return self.graph_query(operation, variables, query)['data']['get_detections']['results']

    # General methods
    @staticmethod
    def create_graph_payload(operation_name, variables, query):
        """ Create payload.
            :param operation_name (str) - The operation's name.
            :param variables (dict)     - The variables.
            :param query (str)          - The query.
            :returns (dict)             - Payload.
        """
        if operation_name:
            payload = {
                "operationName": operation_name,
                "variables": variables,
                "query": query}
        else:
            payload = {
                "variables": variables,
                "query": query}
        return payload

    def graph_query(self, operation_name, variables, query):
        """ Get graph query.
            :param operation_name (str) - The operation's name.
            :param variables (dict)     - The variables.
            :param query (str)          - The query.
            :returns (dict)             - Response from query.
        """
        customer_id = self.customer_id or self.get_customer_id()
        payload = self.create_graph_payload(operation_name, variables, query)
        res = requests.post(self.url, json=payload, headers={"Authorization": self.token, "customer": customer_id})
        if bool(res):
            if 'UNAUTHENTICATED' in str(json.loads(res.text)):
                self.token = self.get_token(self.email, self.pw)
                res = requests.post(self.url, json=payload, headers={"Authorization": self.token})
            return json.loads(res.text)
        else:
            print(f"res: {res}")
            return None

    def change_client_ws(self, ws):
        self.customer_id = ws

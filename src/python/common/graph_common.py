import datetime
import json
import requests
import time


class GraphCommon(object):
    def __init__(self, url, email, pw, customer_id=None):
        """ Initialize GraphCommon class to graph functions.
            :param url (str)            - The url of the environment.
            :param email (str)          - The email for login.
            :param pw (str)             - The password for login.
            :param customer_id (str)    - The customer ID for operations; Defaults to the Demo Customer ID.
        """
        self.url = url
        self.email = email
        self.pw = pw
        self.token = self.get_token(email, pw)
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
            raise Exception(f"Could not get token, error: {res.text}")

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
                "external_id status template_url collection_template_url realtime_regions{region_name " \
                "template_version __typename}vpc_flow_logs{flow_logs_token should_collect_flow_logs __typename} " \
                "lightlytics_collection_token stack_region account_aliases cost{status details operation " \
                "template_version role_arn bucket_arn cur_prefix last_timestamp __typename}__typename}}"
        return self.graph_query(operation, {}, query)['data']['accounts']

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
        return [r["count"] for r in results if r["resource_type"] == resource_type][0]

    def get_resource_configuration_by_id(self, resource_id):
        """ Get configuration details by resource's ID.
            :param resource_id (str)    - Specific resource's ID.
            :returns (dict)             - Configuration details.
        """
        operation = 'ResourceConfiguration'
        query = "query ResourceConfiguration($id: ID, $timestamp: Timestamp){" \
                "configuration(resource_id: $id, timestamp: $timestamp){raw translated impact_paths __typename}}"
        res = self.graph_query(operation, {"id": resource_id}, query)
        if 'errors' in res:
            raise Exception(f'Something went wrong, result: {res}')
        return res['data']['configuration']['translated']

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

    def resources_search(self, account, resource_type):
        """ Search resources by account and types.
            :param account (str)        - Account to search in.
            :param resource_type (str)  - Resource type.
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
            "filters": {"resource_type": [resource_type], "account_id": account, "attributes": []},
            "skip": 0, "limit": 0
        }
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
        query = "query RuleViolations($rule_id: String, $filter_inventory: RuleViolationFilterInventory, $skip: " \
                "Int, $limit: Int){ruleViolations(rule_id: $rule_id filter_inventory: $filter_inventory skip: " \
                "$skip limit: $limit){total_count results __typename}}"
        variables = {"rule_id": rule_id, "filter_inventory": {}, "skip": 0, "limit": 0}
        violations = self.graph_query(operation, variables, query)['data']['ruleViolations']['results']
        return violations

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

    def get_cost_chart(self, from_timestamp, to_timestamp):
        """
        Get the cost information.
        :returns (list) - Cost data.
        """
        operation = "CostChartIndexQuery"
        query = "query CostChartIndexQuery($skip: Int, $limit: Int, $filters: CostFilters, $anti_filters: " \
                "CostFilters, $sort: CostSort, $groupBy: [CostGroupBy], $trend_period: CostTrendPeriod, " \
                "$trend_range: TrendRange, $gbResourceId: Boolean!, $gbOriginalResourceId: Boolean!, " \
                "$gbLineItemType: Boolean!, $gbUsageType: Boolean!, $gbResourceType: Boolean!, $gbAccount: " \
                "Boolean!, $gbRegion: Boolean!, $gbVpc: Boolean!, $gbAvailabilityZone: Boolean!, $gbDay: " \
                "Boolean!, $gbMonth: Boolean!, $gbYear: Boolean!, $gbChargeType: Boolean!, $gbInstanceType: " \
                "Boolean!){cost(filters: $filters anti_filters: $anti_filters group_bys: $groupBy trend_period: " \
                "$trend_period trend_range: $trend_range sort: $sort skip: $skip limit: $limit){total_count " \
                "results{total_cost total_direct_cost total_indirect_cost resource_id @include(if: $gbResourceId) " \
                "original_resource_id @include(if: $gbOriginalResourceId) line_item_type " \
                "@include(if: $gbLineItemType) usage_type @include(if: $gbUsageType) resource_type " \
                "@include(if: $gbResourceType) account @include(if: $gbAccount) region @include(if: $gbRegion) " \
                "vpc @include(if: $gbVpc) availability_zone @include(if: $gbAvailabilityZone) day " \
                "@include(if: $gbDay) month @include(if: $gbMonth) year @include(if: $gbYear) charge_type " \
                "@include(if: $gbChargeType) instance_type @include(if: $gbInstanceType)}}}"
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
                "resource_type", "region", "account"
            ],
            "gbResourceId": False,
            "gbOriginalResourceId": False,
            "gbLineItemType": False,
            "gbUsageType": False,
            "gbResourceType": True,
            "gbAccount": True,
            "gbRegion": True,
            "gbVpc": False,
            "gbAvailabilityZone": False,
            "gbDay": False,
            "gbMonth": False,
            "gbYear": False,
            "gbChargeType": False,
            "gbInstanceType": False,
            "skip": 0,
            "limit": 99999
        }
        return self.graph_query(operation, variables, query)["data"]["cost"]["results"]

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

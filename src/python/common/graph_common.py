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

    def get_compliance_standards(self):
        """ Get all compliance standards.
            :returns (list) - Available compliance standards.
        """
        operation = 'Compliances'
        query = "query Compliances{compliance{results{compliance __typename}__typename}}"
        return [c['compliance'] for c in self.graph_query(operation, {}, query)['data']['compliance']['results']]

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

    def get_rule_violations(self, rule_id, filter_path_violations=False):
        """ Get all rule violations.
            :returns (list) - Rule violations.
        """
        operation = 'RuleViolations'
        query = "query RuleViolations($filters: RuleViolationFilters, $filter_inventory: " \
                "RuleViolationFilterInventory, $skip: Int, $limit: Int){ruleViolations(filters: $filters " \
                "filter_inventory: $filter_inventory skip: $skip limit: $limit){total_count results{id values{ " \
                "rule_id violation_type predicted_monthly_cost ... on RuleResourceViolation{resource_id __typename} " \
                "... on RulePathViolation{id violation_ids path_id path{id united_resources{id __typename} " \
                "__typename} destinations{id __typename}port_ranges{start end protocol __typename} actions " \
                "__typename}__typename}__typename}__typename}}"
        variables = {"filters": {"rule_id": rule_id}, "filter_inventory": {}, "skip": 0, "limit": 0}
        violations = self.graph_query(operation, variables, query)['data']['ruleViolations']['results']
        if filter_path_violations:
            return [v for v in violations if v["__typename"] != "RulePathViolation"]
        return violations

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

import json
import requests


def get_token(url, email, pw):
    """ Get token from graph.
        :param url (str)    - The Lightlytics URL.
        :param email (str)  - The email for login.
        :param pw (str)     - The password for login.
        :returns (str)      - Token.
    """
    payload_operation = "Login"
    payload_vars = {"credentials": {"email": email, "password": pw}}
    query = "mutation Login($credentials: Credentials){login(credentials: $credentials){access_token }}"
    payload = create_graph_payload(payload_operation, payload_vars, query)
    try:
        res = requests.post(url, json=payload)
    except Exception as e:
        raise Exception(f"URL doesn't exist --> {url}, error: {e}")
    if 'errors' not in res.text:
        eval_res = json.loads(res.text)
        return 'Bearer ' + eval_res['data']['login']['access_token']
    else:
        raise Exception(f"Could not get token, error: {res.text}")


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
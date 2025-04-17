"""
Interface to Stream Security GraphQL API providing tools for authentication,
resource management, and rule compliance monitoring.
"""
import os
import sys
from typing import List, Dict, Any, Optional
from fastmcp import FastMCP
from pydantic import BaseModel, Field
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Add parent directory to sys.path to find the src.python.common module
parent_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.append(parent_dir)

# Try to import GraphCommon from either location
try:
    from src.python.common.graph_common import GraphCommon
except ImportError:
    # If the import fails, provide instructions
    print("ERROR: Unable to import GraphCommon. "
          "Make sure the parent directory containing 'src/python/common/graph_common.py' "
          "is in your Python path.")
    print(f"Added {parent_dir} to sys.path, but still couldn't find the module.")
    print("You may need to adjust the import path in this file or set the PYTHONPATH "
          "environment variable.")
    GraphCommon = None

# Define models for input parameters
class LoginCredentials(BaseModel):
    """
    Represents login credentials for the Stream Security GraphQL API.
    """
    url: str = Field(..., description="Stream Security GraphQL API URL")
    email: str = Field(..., description="Email for login")
    password: str = Field(..., description="Password for login")

class AccountInfo(BaseModel):
    """
    Represents information about an account.
    """
    account_id: str = Field(..., description="Account ID")
    regions: List[str] = Field(..., description="List of regions")
    display_name: Optional[str] = Field(None, description="Display name for the account")

# Create the MCP server
mcp = FastMCP("Stream Security GraphQL MCP Server")

def connect(credentials: Optional[LoginCredentials] = None) -> Dict[str, Any]:
    """
    Connect to the Stream Security GraphQL API and authenticate.
    
    This establishes a connection to the Stream Security platform and
    authenticates using the provided credentials.
    
    If credentials are not provided, it will use environment variables:
    - STREAM_SECURITY_URL: Stream Security GraphQL API URL
    - STREAM_SECURITY_EMAIL: Email for login
    - STREAM_SECURITY_PASSWORD: Password for login
    """

    # If credentials not provided, use environment variables
    if credentials is None:
        url = os.getenv("STREAM_SECURITY_URL")
        email = os.getenv("STREAM_SECURITY_EMAIL")
        password = os.getenv("STREAM_SECURITY_PASSWORD")

        if not url or not email or not password:
            return {
                "status": "error",
                "message": "Missing required environment variables. "
                "Set STREAM_SECURITY_URL, STREAM_SECURITY_EMAIL, and STREAM_SECURITY_PASSWORD."
            }

        credentials = LoginCredentials(
            url=url,
            email=email,
            password=password
        )

    try:
        graph_client = GraphCommon(
            url=credentials.url,
            email=credentials.email,
            pw=credentials.password
        )

        # Get the workspace info to verify connection
        workspaces = graph_client.get_all_customer_ids(raw=True)

        return {
            "client": graph_client,
            "status": "connected",
            "token": graph_client.token,
            "customer_id": graph_client.customer_id,
            "workspaces": workspaces
        }
    except Exception as e:
        return {
            "status": "error",
            "message": str(e)
        }

@mcp.tool()
def switch_workspace(workspace_id: str) -> Dict[str, str]:
    """
    Switch to a different workspace/customer ID.
    
    Changes the active workspace to the specified workspace ID.
    """
    graph_client = connect().get("client", None)
    if not graph_client:
        return {"status": "error", "message": "Not connected. Use connect() first."}

    try:
        graph_client.change_client_ws(workspace_id)
        return {
            "status": "success", 
            "message": f"Switched to workspace {workspace_id}"
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}

@mcp.tool()
def get_accounts() -> List[Dict[str, Any]]:
    """
    Get all accounts integrated with Stream Security.
    
    Returns a list of all AWS accounts connected to the platform.
    """
    graph_client = connect().get("client", None)
    if not graph_client:
        return [{"status": "error", "message": "Not connected. Use connect() first."}]

    try:
        accounts = graph_client.get_accounts()
        return accounts
    except Exception as e:
        return [{"status": "error", "message": str(e)}]

@mcp.tool()
def create_account(account: AccountInfo) -> Dict[str, Any]:
    """
    Create a new AWS account integration.
    
    Adds a new AWS account to the Stream Security platform.
    """
    graph_client = connect().get("client", None)
    if not graph_client:
        return {"status": "error", "message": "Not connected. Use connect() first."}

    try:
        result = graph_client.create_account(
            account_id=account.account_id,
            regions_list=account.regions,
            display_name=account.display_name
        )

        if result:
            return {
                "status": "success",
                "message": f"Account {account.account_id} created successfully"
            }
        else:
            return {
                "status": "error",
                "message": "Failed to create account or account already exists"
            }
    except Exception as e:
        return {"status": "error", "message": str(e)}

@mcp.tool()
def get_resources_by_type(resource_type: str, get_only_ids: bool = False) -> Dict[str, Any]:
    """
    Get resources by type.
    
    Retrieves resources of a specific type from the platform.
    """
    graph_client = connect().get("client", None)
    if not graph_client:
        return {"status": "error", "message": "Not connected. Use connect() first."}

    try:
        resources = graph_client.get_resources_by_type(resource_type, get_only_ids)
        return {
            "status": "success",
            "count": len(resources),
            "resources": resources
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}

@mcp.tool()
def search_resources(query: str, get_only_ids: bool = False) -> Dict[str, Any]:
    """
    Search for resources using a query.
    The search does not support operators like AND, OR, NOT, etc.
    
    Performs a search for resources matching the specified query.
    """
    graph_client = connect().get("client", None)
    if not graph_client:
        return {"status": "error", "message": "Not connected. Use connect() first."}

    try:
        results = graph_client.general_resource_search(query, get_only_ids)
        return {
            "status": "success",
            "count": len(results),
            "results": results
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}

@mcp.tool()
def get_resource_configuration(resource_id: str, raw: bool = False) -> Dict[str, Any]:
    """
    Get resource configuration by ID.
    
    Retrieves the configuration details for a specific resource.
    """
    graph_client = connect().get("client", None)
    if not graph_client:
        return {"status": "error", "message": "Not connected. Use connect() first."}

    try:
        config = graph_client.get_resource_configuration_by_id(resource_id, raw)
        return {
            "status": "success",
            "resource_id": resource_id,
            "configuration": config
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}

@mcp.tool()
def get_rules() -> Dict[str, Any]:
    """
    Get all compliance rules.
    
    Retrieves all the compliance rules defined in the platform.
    """
    graph_client = connect().get("client", None)
    if not graph_client:
        return {"status": "error", "message": "Not connected. Use connect() first."}

    try:
        rules = graph_client.get_all_rules()
        return {
            "status": "success",
            "count": len(rules),
            "rules": [(rule['name'], rule['id']) for rule in rules]
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}

@mcp.tool()
def get_rule_violations(rule_id: str) -> Dict[str, Any]:
    """
    Get violations for a specific rule.
    
    Retrieves all resources that violate a specific compliance rule.
    """
    graph_client = connect().get("client", None)
    if not graph_client:
        return {"status": "error", "message": "Not connected. Use connect() first."}

    try:
        violations = graph_client.get_rule_violations(rule_id)
        return {
            "status": "success",
            "count": len(violations),
            "violations": violations
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}

@mcp.tool()
def run_custom_query(operation_name: Optional[str],
                     variables: Dict[str, Any], query: str) -> Dict[str, Any]:
    """
    Run a custom GraphQL query.
    
    Executes a custom GraphQL query against the Stream Security API.
    """
    graph_client = connect().get("client", None)
    if not graph_client:
        return {"status": "error", "message": "Not connected. Use connect() first."}

    try:
        result = graph_client.graph_query(operation_name, variables, query)
        return {
            "status": "success",
            "result": result
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}

@mcp.resource("stream-security://accounts/list")
def get_accounts_resource() -> List[Dict[str, Any]]:
    """
    Resource that returns all accounts.
    """
    graph_client = connect().get("client", None)
    if not graph_client:
        return [{"status": "error", "message": "Not connected. Use connect() first."}]

    try:
        return graph_client.get_accounts()
    except Exception as e:
        return [{"status": "error", "message": str(e)}]

@mcp.resource("stream-security://rules/list")
def get_rules_resource() -> List[Dict[str, Any]]:
    """
    Resource that returns all compliance rules.
    """
    graph_client = connect().get("client", None)
    if not graph_client:
        return [{"status": "error", "message": "Not connected. Use connect() first."}]

    try:
        return graph_client.get_all_rules()
    except Exception as e:
        return [{"status": "error", "message": str(e)}]

@mcp.resource("stream-security://resources/{resource_type}/list")
def get_resources_by_type_resource(resource_type: str) -> List[Dict[str, Any]]:
    """
    Resource that returns resources of a specific type.
    """
    graph_client = connect().get("client", None)
    if not graph_client:
        return [{"status": "error", "message": "Not connected. Use connect() first."}]

    try:
        return graph_client.get_resources_by_type(resource_type)
    except Exception as e:
        return [{"status": "error", "message": str(e)}]

@mcp.resource("stream-security://resources/{resource_id}/configuration")
def get_resource_config_resource(resource_id: str) -> Dict[str, Any]:
    """
    Resource that returns configuration for a specific resource.
    """
    graph_client = connect().get("client", None)
    if not graph_client:
        return {"status": "error", "message": "Not connected. Use connect() first."}

    try:
        return graph_client.get_resource_configuration_by_id(resource_id)
    except Exception as e:
        return {"status": "error", "message": str(e)}

if __name__ == "__main__":
    mcp.run()

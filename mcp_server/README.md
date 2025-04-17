# Stream Security MCP Server

The Stream Security MCP Server enables interaction with the Stream Security platform directly from Cursor AI through the Model Context Protocol (MCP).

## Features

- Connect to Stream Security GraphQL API
- Switch between workspaces
- Manage AWS accounts (list and create)
- Search and explore resources
- View resource configurations
- Check compliance rules and violations
- Run custom GraphQL queries

## Prerequisites

- Python 3.8+
- [Cursor AI](https://cursor.sh/) (with MCP support)
- Access to a Stream Security instance

## Installation

### 1. Clone the Repository

```bash
git clone https://github.com/lightlytics/automation-tools.git
cd automation-tools
```

### 2. Set Up a Virtual Environment (Required)

```bash
# Create a virtual environment
python -m venv venv

# Activate the virtual environment
# On Windows:
venv\Scripts\activate
# On macOS/Linux:
source venv/bin/activate
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

## Cursor AI Integration

### 1. Create MCP Configuration

Create a `.cursor/mcp.json` file in your project directory with the following content:

```json
{
  "mcpServers": {
    "stream-security": {
      "command": "PATH_TO_YOUR_VENV\\Scripts\\python.exe",
      "args": ["-m", "mcp_server.stream_security_mcp"],
      "env": {
        "PYTHONPATH": "PATH_TO_YOUR_PROJECT_ROOT",
        "STREAM_SECURITY_URL": "https://app.streamsec.io/graphql",
        "STREAM_SECURITY_EMAIL": "your-email@example.com",
        "STREAM_SECURITY_PASSWORD": "your-password"
      }
    }
  }
}
```

**Important Notes:**
- Replace `PATH_TO_YOUR_VENV` with the absolute path to your virtual environment
- Replace `PATH_TO_YOUR_PROJECT_ROOT` with the absolute path to your project root directory
- The `PYTHONPATH` environment variable is **crucial** for the MCP server to locate the `mcp_server` module

Example for Windows:
```json
{
  "mcpServers": {
    "stream-security": {
      "command": "D:\\GitHub\\lightlytics\\automation-tools\\venv\\Scripts\\python.exe",
      "args": ["-m", "mcp_server.stream_security_mcp"],
      "env": {
        "PYTHONPATH": "D:\\GitHub\\lightlytics\\automation-tools",
        "STREAM_SECURITY_URL": "https://app.streamsec.io/graphql",
        "STREAM_SECURITY_EMAIL": "your@email.com",
        "STREAM_SECURITY_PASSWORD": "your-password"
      }
    }
  }
}
```

### 2. Enable the MCP Server in Cursor

1. Open Cursor AI
2. Go to Settings > MCP
3. Your Stream Security MCP server should appear in the list
4. Click the toggle to enable it
5. If you make changes to the configuration, click the refresh button next to the server

## Usage

Once the MCP server is enabled in Cursor, you can use natural language to interact with Stream Security:

```
Connect to Stream Security
```

```
List all AWS accounts in Stream Security
```

```
Show me compliance rules that have violations
```

```
Search for S3 bucket resources
```

## Troubleshooting

### "Client Closed" Error

If you encounter a "Client Closed" error:

1. **Check Virtual Environment**: Ensure you're using the correct path to your virtual environment's Python executable
2. **Verify PYTHONPATH**: Make sure the PYTHONPATH environment variable is set correctly to your project root
3. **Check Dependencies**: Ensure all required packages are installed in your virtual environment
4. **Restart Cursor**: Sometimes a simple restart of Cursor resolves connection issues
5. **Check Logs**: Look at Cursor's developer console (Ctrl+Shift+I) for more detailed error messages

### Cannot Find Module

If you see "Cannot find module" errors:

1. Verify that `PYTHONPATH` is set correctly in your mcp.json
2. Ensure you've activated the virtual environment and installed all dependencies
3. Check that the module structure hasn't changed

## Running Manually (For Testing)

To test the MCP server outside of Cursor:

```bash
# Activate your virtual environment
venv\Scripts\activate

# Run the server
python -m mcp_server.stream_security_mcp
```

If this works but the Cursor integration doesn't, it likely indicates a configuration issue with the `.cursor/mcp.json` file.

## Advanced Configuration
For global configuration that works across all your Cursor projects:
1. Create the directory: `mkdir -p ~/.cursor`
2. Copy your configuration: `cp .cursor/mcp.json ~/.cursor/mcp.json`

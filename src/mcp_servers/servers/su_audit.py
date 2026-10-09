"""MCP server 4/12 (SUPER USER): who tried to access what (the MCP audit trail)."""
from mcp.server.fastmcp import FastMCP
from src.mcp_servers import data
from src.mcp_servers.auth import SUPER_USER, guarded

NAME = "su_audit"
mcp = FastMCP(NAME)


@mcp.tool()
@guarded(NAME, SUPER_USER)
def recent_access_log(limit: int = 50) -> dict:
    """Latest MCP tool calls (allowed and denied) with user id, role, server and tool."""
    return {"items": data.audit_rows(min(max(limit, 1), 200))}


@mcp.tool()
@guarded(NAME, SUPER_USER)
def denied_access_attempts(limit: int = 50) -> dict:
    """Only the DENIED calls: useful to spot users probing for data they should not see."""
    return {"items": data.audit_rows(min(max(limit, 1), 200), denied_only=True)}


if __name__ == "__main__":
    mcp.run()

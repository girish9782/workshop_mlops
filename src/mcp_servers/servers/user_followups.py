"""MCP server 7/12 (USER): the caller's own follow-up history only."""
from mcp.server.fastmcp import FastMCP
from src.mcp_servers import data
from src.mcp_servers.auth import PATIENT, SUPER_USER, get_identity, guarded

NAME = "user_followups"
mcp = FastMCP(NAME)


@mcp.tool()
@guarded(NAME, PATIENT, SUPER_USER)
def my_followups() -> dict:
    """How I said my earlier problems were going (better/same/worse) after past appointments."""
    return {"items": data.followups(user_id=get_identity().uid, limit=100)}


if __name__ == "__main__":
    mcp.run()

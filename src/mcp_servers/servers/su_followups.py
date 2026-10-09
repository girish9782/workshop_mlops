"""MCP server 3/12 (SUPER USER): follow-up / recovery reports of any patient."""
from mcp.server.fastmcp import FastMCP
from src.mcp_servers import data
from src.mcp_servers.auth import SUPER_USER, guarded

NAME = "su_followups"
mcp = FastMCP(NAME)


@mcp.tool()
@guarded(NAME, SUPER_USER)
def list_all_followups(limit: int = 50) -> dict:
    """Follow-up answers (better/same/worse) from every patient. Super user only."""
    return {"items": data.followups(limit=min(max(limit, 1), 200))}


@mcp.tool()
@guarded(NAME, SUPER_USER)
def followups_of_user(user_id: int) -> dict:
    """Follow-up history of one specific patient. Super user only."""
    return {"items": data.followups(user_id=user_id)}


if __name__ == "__main__":
    mcp.run()

"""MCP server 2/12 (SUPER USER): appointments of any patient."""
from mcp.server.fastmcp import FastMCP
from src.mcp_servers import data
from src.mcp_servers.auth import SUPER_USER, guarded

NAME = "su_appointments"
mcp = FastMCP(NAME)


@mcp.tool()
@guarded(NAME, SUPER_USER)
def list_all_appointments(limit: int = 50) -> dict:
    """All appointments across all patients, newest first. Super user only."""
    return {"items": data.appointments(limit=min(max(limit, 1), 200))}


@mcp.tool()
@guarded(NAME, SUPER_USER)
def appointments_of_user(user_id: int, limit: int = 50) -> dict:
    """All appointments of a specific patient (includes the problem they described). Super user only."""
    return {"items": data.appointments(user_id=user_id, limit=min(max(limit, 1), 200))}


if __name__ == "__main__":
    mcp.run()

"""MCP server 1/12 (SUPER USER): look up any user account."""
from mcp.server.fastmcp import FastMCP
from src.mcp_servers import data
from src.mcp_servers.auth import SUPER_USER, guarded

NAME = "su_users"
mcp = FastMCP(NAME)


@mcp.tool()
@guarded(NAME, SUPER_USER)
def list_all_users(limit: int = 50) -> dict:
    """List every registered user (id, name, email, role). Super user only."""
    return {"items": data.all_users(min(max(limit, 1), 200))}


@mcp.tool()
@guarded(NAME, SUPER_USER)
def get_user(user_id: int | None = None, email: str | None = None) -> dict:
    """Get one user's account by id or email. Super user only."""
    row = data.user_by_id(user_id) if user_id is not None else data.user_by_email(email or "")
    return row or {"error": "not found"}


if __name__ == "__main__":
    mcp.run()

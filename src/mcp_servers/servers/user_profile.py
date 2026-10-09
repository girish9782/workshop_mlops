"""MCP server 5/12 (USER): the caller's own profile. No user_id parameter exists on purpose."""
from mcp.server.fastmcp import FastMCP
from src.mcp_servers import data
from src.mcp_servers.auth import PATIENT, SUPER_USER, get_identity, guarded

NAME = "user_profile"
mcp = FastMCP(NAME)


@mcp.tool()
@guarded(NAME, PATIENT, SUPER_USER)
def get_my_profile() -> dict:
    """My own account details (name, email, role). Cannot return anyone else's."""
    return data.user_by_id(get_identity().uid) or {"error": "not found"}


if __name__ == "__main__":
    mcp.run()

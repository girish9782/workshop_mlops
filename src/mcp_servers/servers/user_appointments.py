"""MCP server 6/12 (USER): the caller's own appointments only."""
from mcp.server.fastmcp import FastMCP
from src.mcp_servers import data
from src.mcp_servers.auth import PATIENT, SUPER_USER, get_identity, guarded

NAME = "user_appointments"
mcp = FastMCP(NAME)


@mcp.tool()
@guarded(NAME, PATIENT, SUPER_USER)
def my_appointments() -> dict:
    """My booked appointments (doctor, specialty, date/time, the problem I described)."""
    return {"items": data.appointments(user_id=get_identity().uid, limit=100)}


if __name__ == "__main__":
    mcp.run()

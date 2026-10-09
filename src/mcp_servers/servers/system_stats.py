"""MCP server 10/12 (SYSTEM): aggregate numbers only (no personal data)."""
from mcp.server.fastmcp import FastMCP
from src.mcp_servers import data
from src.mcp_servers.auth import SUPER_USER, SYSTEM, guarded

NAME = "system_stats"
mcp = FastMCP(NAME)


@mcp.tool()
@guarded(NAME, SYSTEM, SUPER_USER)
def doctor_workload() -> dict:
    """Bookings and distinct patients per doctor, busiest first."""
    return {"items": data.doctor_load()}


@mcp.tool()
@guarded(NAME, SYSTEM, SUPER_USER)
def system_totals() -> dict:
    """Counts of users, doctors, appointments and follow-ups (and how many follow-ups said same/worse)."""
    return data.system_totals()


if __name__ == "__main__":
    mcp.run()

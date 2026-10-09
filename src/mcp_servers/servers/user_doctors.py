"""MCP server 8/12 (USER): public doctor directory. Read-only: booking stays a button in the UI
(an LLM should not be able to book on its own)."""
from mcp.server.fastmcp import FastMCP
from src.clinic import database as db
from src.mcp_servers import data
from src.mcp_servers.auth import PATIENT, SUPER_USER, guarded

NAME = "user_doctors"
mcp = FastMCP(NAME)


@mcp.tool()
@guarded(NAME, PATIENT, SUPER_USER)
def list_doctors(specialty: str | None = None) -> dict:
    """Doctors we have (name, specialty, experience, fee). Optional filter by specialty."""
    return {"items": data.doctors(specialty)}


@mcp.tool()
@guarded(NAME, PATIENT, SUPER_USER)
def doctor_free_slots(doctor_id: int, limit: int = 10) -> dict:
    """Next free 30-minute slots of a doctor."""
    if not db.get_doctor(doctor_id):
        return {"error": "doctor not found"}
    return {"items": db.get_available_slots(doctor_id)[:min(max(limit, 1), 30)]}


if __name__ == "__main__":
    mcp.run()

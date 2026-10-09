"""MCP server 9/12 (SYSTEM): which patient booked which doctor.
Returns patient id + name only (no emails, no symptom text): the minimum the system needs."""
from mcp.server.fastmcp import FastMCP
from src.mcp_servers import data
from src.mcp_servers.auth import SUPER_USER, SYSTEM, guarded

NAME = "system_booking_map"
mcp = FastMCP(NAME)


@mcp.tool()
@guarded(NAME, SYSTEM, SUPER_USER)
def doctor_to_patients() -> dict:
    """Every booking as (doctor, patient, slot), grouped by doctor."""
    grouped: dict = {}
    for r in data.booking_map():
        g = grouped.setdefault(r["doctor_name"], {"doctor_id": r["doctor_id"],
                                                  "specialty": r["specialty"], "patients": []})
        g["patients"].append({"patient_id": r["patient_id"], "patient_name": r["patient_name"],
                              "slot": r["slot_start"]})
    return {"doctors": grouped}


@mcp.tool()
@guarded(NAME, SYSTEM, SUPER_USER)
def patient_to_doctors() -> dict:
    """Every booking grouped by patient: which doctors each patient has booked."""
    grouped: dict = {}
    for r in data.booking_map():
        g = grouped.setdefault(r["patient_id"], {"patient_name": r["patient_name"], "bookings": []})
        g["bookings"].append({"doctor_name": r["doctor_name"], "specialty": r["specialty"],
                              "slot": r["slot_start"]})
    return {"patients": grouped}


if __name__ == "__main__":
    mcp.run()

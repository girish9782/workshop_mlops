"""The 12 MCP servers, who may use them, and which ones are exposed to the LLM as tools."""
from src.mcp_servers.auth import PATIENT, SUPER_USER, SYSTEM

_P = "src.mcp_servers.servers."
SERVERS = {
    # --- super user: can see every user's information
    "su_users":          {"module": _P + "su_users",          "group": "super_user", "roles": {SUPER_USER}},
    "su_appointments":   {"module": _P + "su_appointments",   "group": "super_user", "roles": {SUPER_USER}},
    "su_followups":      {"module": _P + "su_followups",      "group": "super_user", "roles": {SUPER_USER}},
    "su_audit":          {"module": _P + "su_audit",          "group": "super_user", "roles": {SUPER_USER}},
    # --- user: only their own data
    "user_profile":      {"module": _P + "user_profile",      "group": "user", "roles": {PATIENT, SUPER_USER}},
    "user_appointments": {"module": _P + "user_appointments", "group": "user", "roles": {PATIENT, SUPER_USER}},
    "user_followups":    {"module": _P + "user_followups",    "group": "user", "roles": {PATIENT, SUPER_USER}},
    "user_doctors":      {"module": _P + "user_doctors",      "group": "user", "roles": {PATIENT, SUPER_USER}},
    # --- system: which patient booked which doctor, aggregate stats
    "system_booking_map": {"module": _P + "system_booking_map", "group": "system", "roles": {SYSTEM, SUPER_USER}},
    "system_stats":      {"module": _P + "system_stats",      "group": "system", "roles": {SYSTEM, SUPER_USER}},
    # --- LLM security (run by the agent itself, not offered to the model as tools)
    "llm_input_guard":   {"module": _P + "llm_input_guard",   "group": "llm_security", "roles": {PATIENT, SUPER_USER, SYSTEM}},
    "llm_output_guard":  {"module": _P + "llm_output_guard",  "group": "llm_security", "roles": {PATIENT, SUPER_USER, SYSTEM}},
}


def tool_servers_for(role: str) -> dict:
    """Servers the LLM may be given for this role (guards excluded: they are not model-callable)."""
    return {n: s for n, s in SERVERS.items() if s["group"] != "llm_security" and role in s["roles"]}

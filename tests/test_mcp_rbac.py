import asyncio
import os
import sys

import pytest

from src.mcp_servers import auth, data
from src.mcp_servers.auth import issue_token
from src.mcp_servers.servers import (su_users, su_appointments, su_audit, user_appointments,
                                     user_profile, system_booking_map, system_stats, user_doctors)


def as_(uid, role, ttl=300):
    os.environ["MCP_AUTH_TOKEN"] = issue_token(uid, role, ttl)


# ---------------- patient: own data only ----------------
def test_patient_sees_only_own_appointments(world):
    as_(world["alice"], "patient")
    items = user_appointments.my_appointments()["items"]
    assert items and all(i["user_id"] == world["alice"] for i in items)
    assert "bob secret problem" not in str(items)


def test_patient_profile_is_own_and_has_no_hash(world):
    as_(world["bob"], "patient")
    p = user_profile.get_my_profile()
    assert p["email"] == "bob@x.com" and "password_hash" not in p


def test_patient_cannot_use_super_user_or_system_tools(world):
    as_(world["alice"], "patient")
    assert su_users.list_all_users()["error"] == "forbidden"
    assert su_appointments.appointments_of_user(world["bob"])["error"] == "forbidden"
    assert su_audit.recent_access_log()["error"] == "forbidden"
    assert system_booking_map.doctor_to_patients()["error"] == "forbidden"
    assert system_stats.system_totals()["error"] == "forbidden"


def test_patient_tools_have_no_user_id_parameter():
    import inspect
    for fn in (user_appointments.my_appointments, user_profile.get_my_profile):
        assert "user_id" not in inspect.signature(fn).parameters


# ---------------- super user ----------------
def test_super_user_sees_everyone(world):
    as_(world["carol"], "super_user")
    emails = {u["email"] for u in su_users.list_all_users()["items"]}
    assert {"alice@x.com", "bob@x.com", "carol@x.com"} <= emails
    assert all("password_hash" not in u for u in su_users.list_all_users()["items"])
    assert len(su_appointments.list_all_appointments()["items"]) >= 2
    assert su_appointments.appointments_of_user(world["bob"])["items"][0]["problem"] == "bob secret problem"


# ---------------- system ----------------
def test_system_sees_who_booked_which_doctor_without_emails(world):
    as_(auth.SYSTEM_UID, "system")
    out = system_booking_map.doctor_to_patients()
    names = {p["patient_name"] for d in out["doctors"].values() for p in d["patients"]}
    assert {"Alice", "Bob"} <= names
    assert "@" not in str(out) and "secret problem" not in str(out)
    assert system_stats.system_totals()["appointments"] >= 2
    assert su_users.list_all_users()["error"] == "forbidden"      # system is not a super user


# ---------------- token security ----------------
def test_missing_forged_expired_and_role_mismatch(world):
    os.environ.pop("MCP_AUTH_TOKEN", None)
    assert su_users.list_all_users()["error"] == "unauthorized"
    os.environ["MCP_AUTH_TOKEN"] = "garbage"
    assert su_users.list_all_users()["error"] == "unauthorized"
    as_(world["alice"], "super_user")                      # alice is a patient in the DB
    assert su_users.list_all_users()["reason"] == "role mismatch"
    as_(world["alice"], "patient", ttl=-1)
    assert user_profile.get_my_profile()["reason"] == "token expired"
    with pytest.raises(ValueError):
        issue_token(world["alice"], "root")


def test_user_cannot_hold_system_role(world):
    as_(world["alice"], "system")
    assert system_stats.system_totals()["error"] == "unauthorized"


def test_denials_are_audited(world):
    as_(world["carol"], "super_user")
    denied = su_audit.denied_access_attempts()["items"]
    assert denied and any(d["role"] == "patient" and d["server"] == "su_users" for d in denied)


# ---------------- real MCP protocol over stdio ----------------
def test_real_stdio_server_enforces_role(world):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    root = os.path.dirname(os.path.dirname(__file__))

    async def call(token, module, tool, args=None):
        env = {**os.environ, "MCP_AUTH_TOKEN": token}
        params = StdioServerParameters(command=sys.executable, args=["-m", module], env=env, cwd=root)
        async with stdio_client(params) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                res = await s.call_tool(tool, args or {})
                return "".join(getattr(b, "text", "") for b in res.content)

    mod = "src.mcp_servers.servers.su_users"
    assert "forbidden" in asyncio.run(call(issue_token(world["alice"], "patient"), mod, "list_all_users"))
    assert "alice@x.com" in asyncio.run(call(issue_token(world["carol"], "super_user"), mod, "list_all_users"))

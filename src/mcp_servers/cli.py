"""Admin helper.
  python -m src.mcp_servers.cli set-role you@example.com super_user
  python -m src.mcp_servers.cli token --role system            # service token (uid 0)
  python -m src.mcp_servers.cli token --role patient --user-id 3
Use the printed token as MCP_AUTH_TOKEN when running a server by hand or from another MCP client."""
import argparse

from src.clinic import database as db
from src.mcp_servers.auth import ROLES, SYSTEM, SYSTEM_UID, issue_token


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("set-role"); s.add_argument("email"); s.add_argument("role", choices=["patient", "super_user"])
    t = sub.add_parser("token"); t.add_argument("--role", choices=ROLES, required=True)
    t.add_argument("--user-id", type=int); t.add_argument("--ttl", type=int, default=3600)
    a = ap.parse_args()
    db.init_db()
    if a.cmd == "set-role":
        print("updated" if db.set_user_role(a.email, a.role) else "no such user")
    else:
        uid = SYSTEM_UID if a.role == SYSTEM else a.user_id
        if uid is None:
            ap.error("--user-id is required for patient / super_user tokens")
        print(issue_token(uid, a.role, ttl=a.ttl))


if __name__ == "__main__":
    main()

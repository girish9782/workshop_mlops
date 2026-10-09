"""Identity + role enforcement shared by every MCP server.

How identity works
------------------
The web app (or the CLI) issues a short-lived SIGNED token {uid, role}. The agent starts each
MCP server process with that token in MCP_AUTH_TOKEN. Servers:
  * verify the signature + expiry (forged tokens are rejected),
  * re-read the role from the database (a demoted user loses access immediately),
  * decide access from the TOKEN, never from tool arguments. Patient tools therefore have no
    `user_id` parameter at all: the model cannot ask for someone else's data.
Every call (allowed or denied) is written to the mcp_audit table.
"""
import contextvars
import functools
import os
import secrets
from dataclasses import dataclass

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from src.clinic import database as db

PATIENT, SUPER_USER, SYSTEM = "patient", "super_user", "system"
ROLES = (PATIENT, SUPER_USER, SYSTEM)
_SALT = "mcp-identity-v1"
SYSTEM_UID = 0  # service account: not a row in `users`, only a signed token can claim it


class AuthError(Exception):
    pass


@dataclass(frozen=True)
class Identity:
    uid: int
    role: str


_current: contextvars.ContextVar = contextvars.ContextVar("mcp_identity", default=None)


def _secret() -> str:
    s = os.getenv("MCP_SECRET") or os.getenv("SESSION_SECRET")
    if not s:
        # Dev fallback: random per process tree. Child servers inherit it through os.environ.
        s = os.environ["MCP_SECRET"] = secrets.token_urlsafe(32)
    return s


def issue_token(uid: int, role: str, ttl: int = 300) -> str:
    """ttl is enforced at verification time (see verify_token)."""
    if role not in ROLES:
        raise ValueError(f"unknown role {role!r}")
    return URLSafeTimedSerializer(_secret(), salt=_SALT).dumps({"uid": uid, "role": role, "ttl": ttl})


def verify_token(token: str) -> Identity:
    if not token:
        raise AuthError("missing MCP_AUTH_TOKEN")
    ser = URLSafeTimedSerializer(_secret(), salt=_SALT)
    try:
        data = ser.loads(token, max_age=3600)  # hard ceiling; per-token ttl checked below
        # per-token ttl
        ser.loads(token, max_age=int(data.get("ttl", 300)))
    except SignatureExpired:
        raise AuthError("token expired")
    except BadSignature:
        raise AuthError("invalid token")
    uid, role = int(data["uid"]), data["role"]
    if role not in ROLES:
        raise AuthError("unknown role")
    if uid == SYSTEM_UID:
        if role != SYSTEM:
            raise AuthError("uid 0 is reserved for the system role")
    else:
        row = db.get_user(uid)
        if not row:
            raise AuthError("user no longer exists")
        if row["role"] != role:  # role changed in DB since the token was issued
            raise AuthError("role mismatch")
        if role == SYSTEM:
            raise AuthError("system role cannot belong to a user account")
    return Identity(uid, role)


def get_identity() -> Identity:
    ident = _current.get()
    if ident is None:
        raise AuthError("no identity in context")
    return ident


def audit(ident, server: str, tool: str, allowed: bool, detail: str = ""):
    try:
        with db.get_conn() as conn:
            conn.execute(
                "INSERT INTO mcp_audit (user_id, role, server, tool, allowed, detail)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (getattr(ident, "uid", None), getattr(ident, "role", None), server, tool,
                 1 if allowed else 0, detail[:300]),
            )
    except Exception:  # auditing must never take the tool down, but never fail silently either
        import sys
        print("audit write failed", file=sys.stderr)


def guarded(server: str, *roles: str):
    """Decorator: only `roles` may call the tool. The tool body reads identity with get_identity()."""
    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            try:
                ident = verify_token(os.getenv("MCP_AUTH_TOKEN", ""))
            except AuthError as e:
                audit(None, server, fn.__name__, False, f"auth: {e}")
                return {"error": "unauthorized", "reason": str(e)}
            if ident.role not in roles:
                audit(ident, server, fn.__name__, False, "role not allowed")
                return {"error": "forbidden",
                        "reason": f"role '{ident.role}' cannot use {server}.{fn.__name__}"}
            token = _current.set(ident)
            try:
                result = fn(*args, **kwargs)
                audit(ident, server, fn.__name__, True)
                return result
            finally:
                _current.reset(token)
        return wrapper
    return deco

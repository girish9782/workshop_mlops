"""Read-only queries used by the MCP tools. Columns are listed explicitly so that
password hashes (or any future secret column) can never be returned by accident."""
from src.clinic import database as db

_APPT = (
    "SELECT a.id AS appointment_id, a.slot_start, a.problem, a.user_id,"
    " u.name AS patient_name, d.id AS doctor_id, d.name AS doctor_name, d.specialty"
    " FROM appointments a JOIN users u ON u.id = a.user_id JOIN doctors d ON d.id = a.doctor_id"
)


def _rows(sql, params=()):
    with db.get_conn() as conn:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


def all_users(limit=100):
    return _rows(
        "SELECT u.id, u.name, u.email, u.role, u.created_at, u.last_login_at, u.last_logout_at,"
        " u.login_count, (SELECT COUNT(*) FROM appointments a WHERE a.user_id = u.id) AS appointments"
        " FROM users u ORDER BY u.id LIMIT ?", (limit,))


_USER_COLS = "id, name, email, role, created_at, last_login_at, last_logout_at, login_count"


def user_by_id(uid):
    r = _rows(f"SELECT {_USER_COLS} FROM users WHERE id = ?", (uid,))
    return r[0] if r else None


def user_by_email(email):
    r = _rows(f"SELECT {_USER_COLS} FROM users WHERE email = ?", (email.lower(),))
    return r[0] if r else None


def appointments(user_id=None, doctor_id=None, limit=100):
    sql, cond, params = _APPT, [], []
    if user_id is not None:
        cond.append("a.user_id = ?"); params.append(user_id)
    if doctor_id is not None:
        cond.append("a.doctor_id = ?"); params.append(doctor_id)
    if cond:
        sql += " WHERE " + " AND ".join(cond)
    return _rows(sql + " ORDER BY a.slot_start DESC LIMIT ?", (*params, limit))


def followups(user_id=None, limit=100):
    sql = ("SELECT f.id, f.user_id, u.name AS patient_name, f.appointment_id, f.status, f.note,"
           " f.created_at, d.name AS doctor_name FROM followups f"
           " JOIN users u ON u.id = f.user_id JOIN appointments a ON a.id = f.appointment_id"
           " JOIN doctors d ON d.id = a.doctor_id")
    params = []
    if user_id is not None:
        sql += " WHERE f.user_id = ?"; params.append(user_id)
    return _rows(sql + " ORDER BY f.created_at DESC LIMIT ?", (*params, limit))


def doctors(specialty=None):
    sql, params = "SELECT id, name, specialty, experience_years, fee FROM doctors", []
    if specialty:
        sql += " WHERE specialty = ?"; params.append(specialty)
    return _rows(sql + " ORDER BY specialty, experience_years DESC", params)


def booking_map():
    """doctor -> patients. Patient id + name only (no email, no problem text): minimum needed."""
    return _rows(
        "SELECT d.id AS doctor_id, d.name AS doctor_name, d.specialty, a.slot_start,"
        " u.id AS patient_id, u.name AS patient_name"
        " FROM appointments a JOIN doctors d ON d.id = a.doctor_id JOIN users u ON u.id = a.user_id"
        " ORDER BY d.name, a.slot_start")


def doctor_load():
    return _rows(
        "SELECT d.id AS doctor_id, d.name AS doctor_name, d.specialty,"
        " COUNT(a.id) AS total_bookings, COUNT(DISTINCT a.user_id) AS distinct_patients"
        " FROM doctors d LEFT JOIN appointments a ON a.doctor_id = d.id"
        " GROUP BY d.id ORDER BY total_bookings DESC")


def system_totals():
    t = {}
    with db.get_conn() as conn:
        for key, sql in {
            "users": "SELECT COUNT(*) FROM users", "doctors": "SELECT COUNT(*) FROM doctors",
            "appointments": "SELECT COUNT(*) FROM appointments",
            "followups": "SELECT COUNT(*) FROM followups",
            "followups_worse_or_same": "SELECT COUNT(*) FROM followups WHERE status IN ('worse','same')",
        }.items():
            t[key] = conn.execute(sql).fetchone()[0]
    return t


def audit_rows(limit=50, denied_only=False):
    sql = "SELECT id, ts, user_id, role, server, tool, allowed, detail FROM mcp_audit"
    if denied_only:
        sql += " WHERE allowed = 0"
    return _rows(sql + " ORDER BY id DESC LIMIT ?", (limit,))

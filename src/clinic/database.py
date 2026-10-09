"""SQLite storage for users, doctors and appointments (stdlib only)."""
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, time, timedelta

DB_PATH = os.getenv("CLINIC_DB_PATH", os.path.join("data", "clinic.db"))
SLOT_MINUTES = 30
BOOKING_DAYS = 3
SLOT_FMT = "%Y-%m-%d %H:%M"

# name, specialty, experience_years, start_hour, end_hour, fee
SEED_DOCTORS = [
    ("Dr. Anil Verma", "General Physician", 12, 9, 15, 400),
    ("Dr. Meera Joshi", "General Physician", 8, 12, 18, 350),
    ("Dr. Rohit Mehta", "Neurologist", 15, 10, 16, 900),
    ("Dr. Kavita Rao", "Neurologist", 9, 14, 19, 800),
    ("Dr. Suresh Gupta", "Gastroenterologist", 14, 10, 16, 800),
    ("Dr. Neha Kapoor", "Gastroenterologist", 7, 15, 20, 700),
    ("Dr. Vikram Singh", "Cardiologist", 18, 9, 14, 1000),
    ("Dr. Anjali Nair", "Dermatologist", 10, 11, 17, 600),
    ("Dr. Imran Khan", "Orthopedic", 16, 10, 16, 800),
    ("Dr. Pooja Desai", "ENT Specialist", 11, 10, 16, 600),
    ("Dr. Sanjay Iyer", "Pulmonologist", 13, 11, 17, 800),
    ("Dr. Ritu Malhotra", "Gynecologist", 14, 10, 16, 800),
    ("Dr. Arjun Bansal", "Pediatrician", 9, 9, 15, 500),
    ("Dr. Farah Ali", "Psychiatrist", 12, 12, 18, 900),
    ("Dr. Manish Tiwari", "Ophthalmologist", 10, 10, 16, 600),
]


@contextmanager
def get_conn():
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    with get_conn() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'patient',
                last_login_at TEXT,
                last_logout_at TEXT,
                login_count INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS doctors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                specialty TEXT NOT NULL,
                experience_years INTEGER NOT NULL,
                start_hour INTEGER NOT NULL,
                end_hour INTEGER NOT NULL,
                fee INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS appointments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id),
                doctor_id INTEGER NOT NULL REFERENCES doctors(id),
                slot_start TEXT NOT NULL,
                problem TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE (doctor_id, slot_start),
                UNIQUE (user_id, slot_start)
            );
            CREATE TABLE IF NOT EXISTS followups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id),
                appointment_id INTEGER NOT NULL UNIQUE REFERENCES appointments(id),
                status TEXT NOT NULL,
                note TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS mcp_audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                user_id INTEGER,
                role TEXT,
                server TEXT NOT NULL,
                tool TEXT NOT NULL,
                allowed INTEGER NOT NULL,
                detail TEXT
            );
            """
        )
        # migration for databases created before roles existed
        cols = {r[1] for r in conn.execute("PRAGMA table_info(users)")}
        if "role" not in cols:
            conn.execute("ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'patient'")
        if "last_login_at" not in cols:
            conn.execute("ALTER TABLE users ADD COLUMN last_login_at TEXT")
            conn.execute("ALTER TABLE users ADD COLUMN last_logout_at TEXT")
            conn.execute("ALTER TABLE users ADD COLUMN login_count INTEGER NOT NULL DEFAULT 0")
        if conn.execute("SELECT COUNT(*) FROM doctors").fetchone()[0] == 0:
            conn.executemany(
                "INSERT INTO doctors (name, specialty, experience_years, start_hour, end_hour, fee)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                SEED_DOCTORS,
            )


# ---------- users ----------
def create_user(name: str, email: str, password_hash: str, role: str = "patient"):
    """Returns the new user id, or None if the email is already registered."""
    try:
        with get_conn() as conn:
            cur = conn.execute(
                "INSERT INTO users (name, email, password_hash, role) VALUES (?, ?, ?, ?)",
                (name, email, password_hash, role),
            )
            return cur.lastrowid
    except sqlite3.IntegrityError:
        return None


def get_user_by_email(email: str):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        return dict(row) if row else None


def get_user(user_id: int):
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id, name, email, role FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        return dict(row) if row else None


# ---------- doctors & slots ----------
def get_doctors_by_specialty(specialty: str):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM doctors WHERE specialty = ? ORDER BY experience_years DESC",
            (specialty,),
        ).fetchall()
        return [dict(r) for r in rows]


def get_doctor(doctor_id: int):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM doctors WHERE id = ?", (doctor_id,)).fetchone()
        return dict(row) if row else None


def get_available_slots(doctor_id: int, now: datetime | None = None):
    """Free 30-minute slots for the next few days, as 'YYYY-MM-DD HH:MM' strings."""
    doctor = get_doctor(doctor_id)
    if not doctor:
        return []
    now = now or datetime.now()
    with get_conn() as conn:
        booked = {
            r[0]
            for r in conn.execute(
                "SELECT slot_start FROM appointments WHERE doctor_id = ?", (doctor_id,)
            )
        }
    slots = []
    for offset in range(BOOKING_DAYS):
        day = (now + timedelta(days=offset)).date()
        cur = datetime.combine(day, time(doctor["start_hour"]))
        end = datetime.combine(day, time(doctor["end_hour"]))
        while cur < end:
            value = cur.strftime(SLOT_FMT)
            if cur > now + timedelta(minutes=30) and value not in booked:
                slots.append(value)
            cur += timedelta(minutes=SLOT_MINUTES)
    return slots


# ---------- appointments ----------
def book_appointment(user_id: int, doctor_id: int, slot: str, problem: str):
    """Returns the appointment id, or None if the slot is invalid / already taken."""
    if slot not in get_available_slots(doctor_id):  # never trust the client's slot value
        return None
    try:
        with get_conn() as conn:
            cur = conn.execute(
                "INSERT INTO appointments (user_id, doctor_id, slot_start, problem)"
                " VALUES (?, ?, ?, ?)",
                (user_id, doctor_id, slot, problem),
            )
            return cur.lastrowid
    except sqlite3.IntegrityError:
        return None


def get_user_appointments(user_id: int):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT a.id, a.slot_start, a.problem, d.name AS doctor_name, d.specialty, d.fee"
            " FROM appointments a JOIN doctors d ON d.id = a.doctor_id"
            " WHERE a.user_id = ? ORDER BY a.slot_start",
            (user_id,),
        ).fetchall()
        return [dict(r) for r in rows]


# ---------- follow-up ("how is your earlier problem now?") ----------
_APPT_SELECT = (
    "SELECT a.id, a.slot_start, a.problem, d.id AS doctor_id, d.name AS doctor_name,"
    " d.specialty, d.experience_years, d.fee"
    " FROM appointments a JOIN doctors d ON d.id = a.doctor_id WHERE a.user_id = ? "
)


def get_followup_context(user_id: int, now: datetime | None = None):
    """pending  = the user's most recent PAST appointment, if we haven't asked about it yet.
    upcoming = their next future appointment (for a friendly reminder)."""
    now_s = (now or datetime.now()).strftime(SLOT_FMT)
    with get_conn() as conn:
        last = conn.execute(
            _APPT_SELECT + "AND a.slot_start < ? ORDER BY a.slot_start DESC LIMIT 1",
            (user_id, now_s),
        ).fetchone()
        pending = None
        if last and not conn.execute(
            "SELECT 1 FROM followups WHERE appointment_id = ?", (last["id"],)
        ).fetchone():
            pending = dict(last)
        nxt = conn.execute(
            _APPT_SELECT + "AND a.slot_start >= ? ORDER BY a.slot_start ASC LIMIT 1",
            (user_id, now_s),
        ).fetchone()
        return {"pending": pending, "upcoming": dict(nxt) if nxt else None}


def record_followup(user_id: int, appointment_id: int, status: str, note: str = "",
                    now: datetime | None = None):
    """Saves the answer. Returns the appointment row, or None if it isn't this user's past
    appointment or was already answered."""
    now_s = (now or datetime.now()).strftime(SLOT_FMT)
    with get_conn() as conn:
        row = conn.execute(
            _APPT_SELECT + "AND a.id = ? AND a.slot_start < ?", (user_id, appointment_id, now_s)
        ).fetchone()
        if not row:
            return None
        try:
            conn.execute(
                "INSERT INTO followups (user_id, appointment_id, status, note) VALUES (?, ?, ?, ?)",
                (user_id, appointment_id, status, note[:500]),
            )
        except sqlite3.IntegrityError:
            return None
        return dict(row)


def set_user_role(email: str, role: str) -> bool:
    """Admin helper (used by the CLI). Roles: patient | super_user."""
    with get_conn() as conn:
        cur = conn.execute("UPDATE users SET role = ? WHERE email = ?", (role, email.lower()))
        return cur.rowcount > 0


# ---------- login / logout tracking ----------
TS_FMT = "%Y-%m-%d %H:%M:%S"  # server local time, same clock as appointment slots


def record_login(user_id: int, now: datetime | None = None):
    with get_conn() as conn:
        conn.execute(
            "UPDATE users SET last_login_at = ?, login_count = login_count + 1 WHERE id = ?",
            ((now or datetime.now()).strftime(TS_FMT), user_id),
        )


def record_logout(user_id: int, now: datetime | None = None):
    with get_conn() as conn:
        conn.execute(
            "UPDATE users SET last_logout_at = ? WHERE id = ?",
            ((now or datetime.now()).strftime(TS_FMT), user_id),
        )

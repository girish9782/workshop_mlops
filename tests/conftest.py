import os
import sys
import tempfile
from pathlib import Path

# Must be set BEFORE src.clinic.database is imported (DB_PATH is read at import time).
_tmp = tempfile.mkdtemp()
os.environ["CLINIC_DB_PATH"] = os.path.join(_tmp, "test.db")
os.environ["MCP_SECRET"] = "test-secret"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402
from datetime import datetime, timedelta  # noqa: E402
from src.clinic import database as db  # noqa: E402


@pytest.fixture(scope="session")
def world():
    """alice + bob (patients), carol (super_user), 2 bookings each for alice/bob."""
    db.init_db()
    a = db.create_user("Alice", "alice@x.com", "h")
    b = db.create_user("Bob", "bob@x.com", "h")
    c = db.create_user("Carol", "carol@x.com", "h", role="super_user")
    doc = db.get_doctors_by_specialty("Neurologist")[0]
    slots = db.get_available_slots(doc["id"])
    assert db.book_appointment(a, doc["id"], slots[0], "alice migraine")
    assert db.book_appointment(b, doc["id"], slots[1], "bob secret problem")
    return {"alice": a, "bob": b, "carol": c, "doctor": doc}

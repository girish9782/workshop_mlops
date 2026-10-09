"""Auth pages, chatbot API and appointment booking."""
import hmac
import os
import re
from datetime import datetime, timedelta

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from src.clinic import database as db
from src.clinic import triage
from src.clinic.imaging import MAX_IMAGE_BYTES, sniff_image, to_data_url
from src.clinic.security import DUMMY_HASH, hash_password, verify_password
from src.logger import get_logger
from src.mcp_servers.llm_agent import run_assistant
from src.mcp_servers.mcp_client import call_tool

logger = get_logger(__name__)
templates = Jinja2Templates(directory="templates")
router = APIRouter()

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _is_env_super_user(password: str) -> bool:
    """True only if the password equals SUPERUSER_PASSWORD from .env (constant-time compare).
    The email can be anything. If SUPERUSER_PASSWORD is empty, super user is disabled."""
    want_pw = os.getenv("SUPERUSER_PASSWORD", "")
    if not want_pw:
        return False
    return hmac.compare_digest(password.encode(), want_pw.encode())


def current_user(request: Request):
    uid = request.session.get("user_id")
    return db.get_user(uid) if uid else None


def render(request: Request, name: str, status_code: int = 200, **ctx):
    ctx.setdefault("user", current_user(request))
    return templates.TemplateResponse(request, name, ctx, status_code=status_code)


def _login(request: Request, user_id: int):
    request.session.clear()
    request.session["user_id"] = user_id


# ---------------- pages: signup / login / logout ----------------
@router.get("/signup")
def signup_form(request: Request):
    if current_user(request):
        return RedirectResponse("/chat", status_code=303)
    return render(request, "signup.html", error=None, form={})


@router.post("/signup")
def signup(request: Request, name: str = Form(...), email: str = Form(...),
           password: str = Form(...), confirm: str = Form(...)):
    name, email = name.strip(), email.strip().lower()
    error = None
    if not 2 <= len(name) <= 80:
        error = "Please enter your name (2-80 characters)."
    elif not EMAIL_RE.match(email) or len(email) > 254:
        error = "Please enter a valid email address."
    elif len(password) < 8:
        error = "Password must be at least 8 characters."
    elif password != confirm:
        error = "Passwords do not match."
    if not error:
        # Signing up with the SUPERUSER_PASSWORD from .env (any email) makes a super user;
        # everyone else is a patient.
        role = "super_user" if _is_env_super_user(password) else "patient"
        user_id = db.create_user(name, email, hash_password(password), role)
        if user_id is None:
            error = "An account with this email already exists. Try logging in."
    if error:
        return render(request, "signup.html", status_code=400, error=error,
                      form={"name": name, "email": email})
    _login(request, user_id)
    db.record_login(user_id)
    logger.info("New user registered (id=%s, role=%s)", user_id, role)
    return RedirectResponse("/chat", status_code=303)


@router.get("/login")
def login_form(request: Request):
    if current_user(request):
        return RedirectResponse("/chat", status_code=303)
    return render(request, "login.html", error=None, form={})


@router.post("/login")
def login(request: Request, email: str = Form(...), password: str = Form(...)):
    email = email.strip().lower()
    user = db.get_user_by_email(email)
    ok = verify_password(password, user["password_hash"] if user else DUMMY_HASH)
    if not (user and ok):
        return render(request, "login.html", status_code=401,
                      error="Incorrect email or password.", form={"email": email})
    if user["role"] != "super_user" and _is_env_super_user(password):
        db.set_user_role(email, "super_user")  # account existed before the .env credentials were set
        logger.info("User %s promoted to super_user via .env password", user["id"])
    _login(request, user["id"])
    db.record_login(user["id"])
    return RedirectResponse("/chat", status_code=303)


@router.post("/logout")
def logout(request: Request):
    uid = request.session.get("user_id")
    if uid:
        db.record_logout(uid)
    request.session.clear()
    return RedirectResponse("/", status_code=303)


# ---------------- admin: all users ----------------
SESSION_DAYS = 7  # must match max_age in main.py's SessionMiddleware


def _login_status(u: dict, now: datetime) -> str:
    """Best guess from the timestamps. Sessions are cookies, so 'Logged in' means: logged in more
    recently than the last logout and the 7-day session cookie has not run out."""
    login, logout_ = u.get("last_login_at"), u.get("last_logout_at")
    if not login:
        return "Never logged in"
    if logout_ and logout_ >= login:
        return "Logged out"
    age = now - datetime.strptime(login, db.TS_FMT)
    return "Logged in" if age < timedelta(days=SESSION_DAYS) else "Session expired"


async def _load_users(user: dict):
    """Ask the su_users MCP server for everyone, add status + stats. Returns (rows, stats) or None."""
    result = await call_tool(user["role"], user["id"], "su_users", "list_all_users", {"limit": 200})
    if "items" not in result:  # MCP server refused or failed
        logger.error("admin users: MCP call failed: %s", result.get("error"))
        return None
    now = datetime.now()
    rows = result["items"]
    for u in rows:
        u["status"] = _login_status(u, now)
        u["is_you"] = u["id"] == user["id"]
    stats = {"total": len(rows),
             "super_users": sum(u["role"] == "super_user" for u in rows),
             "patients": sum(u["role"] == "patient" for u in rows),
             "logged_in": sum(u["status"] == "Logged in" for u in rows)}
    return rows, stats, now


@router.get("/admin/users", response_class=HTMLResponse)
async def admin_users(request: Request):
    user = current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    if user["role"] != "super_user":
        return render(request, "admin_users.html", status_code=403, user=user, users=None,
                      stats=None, error="Only a super user can see this page.")
    loaded = await _load_users(user)
    if loaded is None:
        return render(request, "admin_users.html", status_code=502, user=user, users=None,
                      stats=None, error="Could not load users from the MCP server.")
    rows, stats, now = loaded
    return render(request, "admin_users.html", user=user, users=rows, stats=stats, error=None,
                  now=now.strftime("%d %b %Y, %I:%M %p"))


@router.get("/api/admin/users")
async def api_admin_users(request: Request):
    """JSON for the side panel (super user only)."""
    user = current_user(request)
    if not user:
        return _unauth()
    if user["role"] != "super_user":
        return JSONResponse({"error": "Only a super user can see this."}, status_code=403)
    loaded = await _load_users(user)
    if loaded is None:
        return JSONResponse({"error": "Could not load users."}, status_code=502)
    rows, stats, now = loaded
    keep = ("id", "name", "email", "role", "status", "is_you", "last_login_at",
            "last_logout_at", "login_count")
    return {"now": now.strftime("%d %b %Y, %I:%M %p"), "stats": stats,
            "users": [{k: u.get(k) for k in keep} for u in rows]}


# ---------------- chatbot ----------------
def _appt_view(row):
    if not row:
        return None
    dt = datetime.strptime(row["slot_start"], db.SLOT_FMT)
    return {
        "id": row["id"], "doctor_id": row["doctor_id"], "doctor_name": row["doctor_name"],
        "specialty": row["specialty"], "experience": row["experience_years"], "fee": row["fee"],
        "problem": (row["problem"] or "")[:200],
        "date": dt.strftime("%d %b %Y"), "time": dt.strftime("%I:%M %p").lstrip("0"),
    }


@router.get("/chat")
def chat_page(request: Request):
    user = current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    ctx = db.get_followup_context(user["id"])
    context = {"pending": _appt_view(ctx["pending"]), "upcoming": _appt_view(ctx["upcoming"])}
    return render(request, "chat.html", user=user, context=context)


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=1000)


class FollowupIn(BaseModel):
    appointment_id: int
    status: str | None = Field(default=None, max_length=10)  # better | same | worse | skipped
    text: str | None = Field(default=None, max_length=500)


class BookIn(BaseModel):
    doctor_id: int
    slot: str = Field(max_length=16)


def _unauth():
    return JSONResponse({"error": "Please log in again."}, status_code=401)

@router.post("/api/chat")
def api_chat(request: Request, body: ChatIn):
    user = current_user(request)
    if not user:
        return _unauth()
    problem = body.message.strip()
    result = triage.analyze(problem)
    skip = result.get("off_topic") or result.get("greeting")  # not a health problem
    if not skip:
        request.session["problem"] = problem[:500]  # remembered for the booking record
    doctors = [] if skip else db.get_doctors_by_specialty(result["specialty"])
    return {
        "reply": triage.build_reply(result),
        "emergency": result["emergency"],
        "off_topic": bool(result.get("off_topic")),
        "specialty": result["specialty"],
        "doctors": [
            {"id": d["id"], "name": d["name"], "specialty": d["specialty"],
             "experience": d["experience_years"], "fee": d["fee"]}
            for d in doctors
        ],
    }


def _doctor_cards(specialty):
    if not specialty:
        return []
    return [
        {"id": d["id"], "name": d["name"], "specialty": d["specialty"],
         "experience": d["experience_years"], "fee": d["fee"]}
        for d in db.get_doctors_by_specialty(specialty)
    ]


@router.post("/api/chat-image")
def api_chat_image(request: Request, file: UploadFile = File(...), note: str = Form("")):
    """Injury photo -> severity + specialty. The photo is analysed in memory and never stored."""
    user = current_user(request)
    if not user:
        return _unauth()
    data = file.file.read(MAX_IMAGE_BYTES + 1)
    if len(data) > MAX_IMAGE_BYTES:
        return JSONResponse({"error": "That photo is too large. Please send one under 3 MB."},
                            status_code=413)
    mime = sniff_image(data)
    if not mime:
        return JSONResponse({"error": "Please send a JPG, PNG or WebP photo."}, status_code=415)

    note = note.strip()[:500]
    raw = triage.analyze_injury_image(to_data_url(data, mime), note)
    result = triage.interpret_injury(raw, note)
    if result["status"] == "ok":
        label = result["body_part"] or "unspecified area"
        request.session["problem"] = f"Injury photo ({label}): {result['summary']}"[:500]
    logger.info("Injury photo analysed: status=%s severity=%s emergency=%s",
                result["status"], result["severity"], result["emergency"])
    return {
        "reply": triage.build_image_reply(result),
        "emergency": result["emergency"],
        "status": result["status"],
        "severity": result["severity"],
        "specialty": result["specialty"],
        "doctors": _doctor_cards(result["specialty"]),
    }


class AssistantIn(BaseModel):
    message: str = Field(min_length=1, max_length=2000)


@router.post("/api/assistant")
async def api_assistant(request: Request, body: AssistantIn):
    """LLM assistant wired to the MCP servers for the caller's role (see src/mcp_servers)."""
    user = current_user(request)
    if not user:
        return _unauth()
    return await run_assistant(user, body.message.strip())


@router.post("/api/followup")
def api_followup(request: Request, body: FollowupIn):
    """The user's answer to 'how is your earlier problem now?'"""
    user = current_user(request)
    if not user:
        return _unauth()
    text = (body.text or "").strip()
    status = body.status if body.status in ("better", "same", "worse", "skipped") else None
    if status is None:
        if not text:
            return JSONResponse({"error": "Please tell me how you are feeling."}, status_code=400)
        status, emergency = triage.classify_followup(text)
    else:
        emergency = bool(text) and triage.classify_followup(text)[1]

    appt = db.record_followup(user["id"], body.appointment_id, status, text)
    if not appt:  # not this user's appointment, not in the past, or already answered
        return JSONResponse({"error": "That follow-up was already recorded."}, status_code=404)

    doctor = None
    if status in ("same", "worse"):
        card = _appt_view(appt)
        doctor = {"id": card["doctor_id"], "name": card["doctor_name"],
                  "specialty": card["specialty"], "experience": card["experience"],
                  "fee": card["fee"]}
        request.session["problem"] = f"Follow-up ({status}): {appt['problem'] or ''}"[:500]
    logger.info("Follow-up recorded: status=%s emergency=%s", status, emergency)
    return {
        "status": status,
        "emergency": emergency,
        "reply": triage.followup_reply(status, appt["doctor_name"], emergency),
        "doctor": doctor,
    }


@router.get("/api/doctors/{doctor_id}/slots")
def api_slots(request: Request, doctor_id: int):
    if not current_user(request):
        return _unauth()
    if not db.get_doctor(doctor_id):
        return JSONResponse({"error": "Doctor not found."}, status_code=404)
    slots = []
    for value in db.get_available_slots(doctor_id):
        dt = datetime.strptime(value, db.SLOT_FMT)
        slots.append({"value": value, "day": dt.strftime("%a %d %b"),
                      "time": dt.strftime("%I:%M %p").lstrip("0")})
    return {"slots": slots}


@router.post("/api/book")
def api_book(request: Request, body: BookIn):
    user = current_user(request)
    if not user:
        return _unauth()
    doctor = db.get_doctor(body.doctor_id)
    if not doctor:
        return JSONResponse({"error": "Doctor not found."}, status_code=404)
    appt_id = db.book_appointment(user["id"], doctor["id"], body.slot,
                                  request.session.get("problem", ""))
    if appt_id is None:
        return JSONResponse(
            {"error": "Sorry, that slot was just taken (or you already have an appointment at "
                      "that time). Please pick another."}, status_code=409)
    dt = datetime.strptime(body.slot, db.SLOT_FMT)
    return {"ok": True, "appointment_id": appt_id, "doctor": doctor["name"],
            "when": dt.strftime("%A, %d %B at %I:%M %p")}


@router.get("/appointments")
def appointments_page(request: Request):
    user = current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    rows = db.get_user_appointments(user["id"])
    for r in rows:
        r["when"] = datetime.strptime(r["slot_start"], db.SLOT_FMT).strftime("%a %d %b, %I:%M %p")
    return render(request, "appointments.html", user=user, appointments=rows)

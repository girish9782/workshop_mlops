import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.middleware.sessions import SessionMiddleware

from src.clinic import database as db
from src.clinic.routes import router


@pytest.fixture()
def client(world, monkeypatch):
    monkeypatch.setenv("SUPERUSER_PASSWORD", "Sup3r-Secret-pw")
    app = FastAPI()
    app.add_middleware(SessionMiddleware, secret_key="k")
    app.include_router(router)
    return TestClient(app)


def signup(c, email, pw, name="Some One"):
    return c.post("/signup", data={"name": name, "email": email, "password": pw, "confirm": pw},
                  follow_redirects=False)


def role_of(email):
    return db.get_user_by_email(email)["role"]


def test_env_credentials_make_super_user_on_signup(client):
    assert signup(client, "boss@clinic.com", "Sup3r-Secret-pw", "The Boss").status_code == 303
    assert role_of("boss@clinic.com") == "super_user"


def test_wrong_password_stays_patient(client):
    signup(client, "boss2@clinic.com", "some-other-password")
    assert role_of("boss2@clinic.com") == "patient"


def test_any_email_with_right_password_is_super_user(client):
    signup(client, "random@x.com", "Sup3r-Secret-pw")
    assert role_of("random@x.com") == "super_user"


def test_no_env_means_nobody_is_promoted(monkeypatch):
    from src.clinic.routes import _is_env_super_user
    monkeypatch.delenv("SUPERUSER_PASSWORD", raising=False)
    assert _is_env_super_user("") is False                      # empty == empty must NOT match
    assert _is_env_super_user("Sup3r-Secret-pw") is False
    monkeypatch.setenv("SUPERUSER_PASSWORD", "")
    assert _is_env_super_user("") is False                      # empty password == disabled


def test_login_and_logout_times_are_recorded(client):
    signup(client, "tracked@x.com", "password123")
    u = db.get_user_by_email("tracked@x.com")
    assert u["last_login_at"] and u["login_count"] == 1 and u["last_logout_at"] is None
    client.post("/logout", follow_redirects=False)
    assert db.get_user_by_email("tracked@x.com")["last_logout_at"]
    client.post("/login", data={"email": "tracked@x.com", "password": "password123"}, follow_redirects=False)
    assert db.get_user_by_email("tracked@x.com")["login_count"] == 2


def test_admin_page_blocked_for_patient_and_anonymous(client):
    assert client.get("/admin/users", follow_redirects=False).status_code == 303   # -> /login
    signup(client, "pat@x.com", "password123")
    r = client.get("/admin/users")
    assert r.status_code == 403 and "Only a super user" in r.text and "alice@x.com" not in r.text


def test_admin_page_shows_everyone_with_roles_and_times(client):
    signup(client, "boss@clinic.com", "Sup3r-Secret-pw")      # may already exist: log in instead
    client.post("/login", data={"email": "boss@clinic.com", "password": "Sup3r-Secret-pw"}, follow_redirects=False)
    r = client.get("/admin/users")
    assert r.status_code == 200
    for needle in ("alice@x.com", "bob@x.com", "Super user", "Patient", "Last login", "Last logout", "Logged in"):
        assert needle in r.text, needle
    assert "password_hash" not in r.text and "pbkdf2" not in r.text


def test_existing_patient_with_env_credentials_is_promoted_on_login(client, monkeypatch):
    monkeypatch.delenv("SUPERUSER_PASSWORD")
    signup(client, "early@x.com", "Early-Bird-pw1"); client.post("/logout")
    assert role_of("early@x.com") == "patient"
    monkeypatch.setenv("SUPERUSER_PASSWORD", "Early-Bird-pw1")
    client.post("/login", data={"email": "early@x.com", "password": "Early-Bird-pw1"}, follow_redirects=False)
    assert role_of("early@x.com") == "super_user"


def test_nav_button_and_json_only_for_super_user(client):
    signup(client, "pat2@x.com", "password123")
    assert "su-open" in client.get("/appointments").text          # button is visible to everyone
    assert client.get("/api/admin/users").status_code == 403      # ...but the data is not
    client.post("/logout")
    signup(client, "anyone@x.com", "Sup3r-Secret-pw")
    assert "su-open" in client.get("/appointments").text
    r = client.get("/api/admin/users")
    assert r.status_code == 200
    d = r.json()
    assert {"stats", "users", "now"} <= set(d)
    assert any(u["email"] == "alice@x.com" for u in d["users"])
    assert "password_hash" not in r.text


def test_button_visible_when_logged_out_but_data_needs_login(client):
    assert "su-open" in client.get("/login").text
    assert client.get("/api/admin/users").status_code == 401

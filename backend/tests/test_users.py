from datetime import UTC, datetime

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.config import Settings
from app.main import create_app
from app.models import User
from app.seed import default_seed_path, seed_users
from tests.test_auth import SEED_USERS, _password
from tests.test_schema_migration import (
    BACKEND_ROOT,
    _database_url,
    _drop_database,
    _recreate_database,
)

USERS_DATABASE = "dataset_request_desk_users_migrate_test"
NEW_EMAIL = "new.user@example.com"
NEW_PASSWORD = "client123"


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch):
    _recreate_database(USERS_DATABASE)
    url = _database_url(USERS_DATABASE)
    monkeypatch.setenv("DATABASE_URL", url)
    command.upgrade(Config(str(BACKEND_ROOT / "alembic.ini")), "head")
    application = create_app(Settings(database_url=url, cookie_secure=False))
    db = application.state.session_factory()
    try:
        assert seed_users(db, default_seed_path()) == len(SEED_USERS)
    finally:
        db.close()
    with TestClient(application) as test_client:
        yield test_client
    application.state.engine.dispose()
    _drop_database(USERS_DATABASE)


def _login(client: TestClient, email: str, password: str | None = None) -> None:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": _password(email) if password is None else password},
    )
    assert response.status_code == 200, response.text


def _csrf(client: TestClient) -> dict[str, str]:
    return {"X-CSRF-Token": client.cookies["desk_csrf"]}


def _hold(client: TestClient, session: str, csrf: str) -> None:
    client.cookies.clear()
    client.cookies.set("desk_session", session, domain="testserver.local")
    client.cookies.set("desk_csrf", csrf, domain="testserver.local")


def _create_body(**overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "email": "New.User@Example.com",
        "name": "New User",
        "password": NEW_PASSWORD,
        "role": "client",
        "organisation": "New Org",
    }
    body.update(overrides)
    return body


def _user_id(client: TestClient, email: str) -> int:
    rows = client.get("/api/v1/users").json()
    return next(int(row["id"]) for row in rows if row["email"] == email)


def _count(client: TestClient, email: str) -> int:
    db = client.app.state.session_factory()
    try:
        counted = db.scalar(select(func.count()).select_from(User).where(User.email == email))
        return int(counted or 0)
    finally:
        db.close()


def test_admins_create_and_change_users(client: TestClient) -> None:
    assert client.get("/api/v1/users").status_code == 401

    _login(client, "ops1@example.com")
    assert client.get("/api/v1/users").status_code == 403
    client.post("/api/v1/auth/logout", headers=_csrf(client))
    _login(client, "client-a@example.com")
    assert client.get("/api/v1/users").status_code == 403

    client.post("/api/v1/auth/logout", headers=_csrf(client))
    _login(client, "admin@example.com")
    listed = client.get("/api/v1/users")
    assert listed.status_code == 200
    assert len(listed.json()) == len(SEED_USERS)
    assert "password_hash" not in listed.text
    assert all("password" not in row for row in listed.json())

    created = client.post("/api/v1/users", json=_create_body(), headers=_csrf(client))
    assert created.status_code == 201, created.text
    assert created.json()["email"] == NEW_EMAIL
    assert created.json()["role"] == "client"
    assert created.json()["is_active"] is True
    assert "password" not in created.json()

    client.post("/api/v1/auth/logout", headers=_csrf(client))
    _login(client, NEW_EMAIL, NEW_PASSWORD)
    assert client.get("/api/v1/users").status_code == 403
    member_session = client.cookies["desk_session"]
    member_csrf = client.cookies["desk_csrf"]

    _login(client, "admin@example.com")
    admin_session = client.cookies["desk_session"]
    admin_csrf = client.cookies["desk_csrf"]
    duplicate = client.post("/api/v1/users", json=_create_body(), headers=_csrf(client))
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"] == "A user with this email already exists"
    assert _count(client, NEW_EMAIL) == 1

    user_id = _user_id(client, NEW_EMAIL)
    deactivated = client.patch(
        f"/api/v1/users/{user_id}",
        json={"is_active": False, "password": "should-be-ignored"},
        headers=_csrf(client),
    )
    assert deactivated.status_code == 200
    assert deactivated.json()["is_active"] is False

    _hold(client, member_session, member_csrf)
    assert client.get("/api/v1/auth/me").status_code == 401
    refused = client.post(
        "/api/v1/auth/login",
        json={"email": NEW_EMAIL, "password": NEW_PASSWORD},
    )
    wrong = client.post(
        "/api/v1/auth/login",
        json={"email": "client-a@example.com", "password": "wrong-password"},
    )
    assert refused.status_code == wrong.status_code == 401
    assert refused.json() == wrong.json()
    assert refused.json()["detail"] == "Invalid email or password"

    _hold(client, admin_session, admin_csrf)
    restored = client.patch(
        f"/api/v1/users/{user_id}",
        json={"is_active": True},
        headers=_csrf(client),
    )
    assert restored.status_code == 200
    promoted = client.patch(
        f"/api/v1/users/{user_id}",
        json={"role": "operator"},
        headers=_csrf(client),
    )
    assert promoted.status_code == 200
    assert promoted.json()["role"] == "operator"

    client.post("/api/v1/auth/logout", headers=_csrf(client))
    _login(client, NEW_EMAIL, NEW_PASSWORD)
    assert client.get("/api/v1/episodes").status_code == 200
    request = client.post(
        "/api/v1/requests",
        json={
            "task_name": "pick cups",
            "episodes_requested": 1,
            "deadline": datetime.now(UTC).date().isoformat(),
        },
        headers=_csrf(client),
    )
    assert request.status_code == 403


def test_last_admin_cannot_step_down(client: TestClient) -> None:
    _login(client, "admin@example.com")
    admin_id = client.get("/api/v1/auth/me").json()["id"]

    demoted = client.patch(
        f"/api/v1/users/{admin_id}",
        json={"role": "operator"},
        headers=_csrf(client),
    )
    deactivated = client.patch(
        f"/api/v1/users/{admin_id}",
        json={"is_active": False},
        headers=_csrf(client),
    )
    assert demoted.status_code == deactivated.status_code == 409
    assert demoted.json()["detail"] == "The desk needs an active admin"

    me = client.get("/api/v1/auth/me").json()
    assert me["role"] == "admin"
    listed = next(row for row in client.get("/api/v1/users").json() if row["id"] == admin_id)
    assert listed["is_active"] is True

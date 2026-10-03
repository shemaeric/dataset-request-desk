import json
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from app.auth import require_roles
from app.config import Settings
from app.logging import access_logger
from app.main import create_app
from app.models import User, UserRole
from app.seed import default_seed_path, seed_users
from tests.test_schema_migration import _database_url, _drop_database, _recreate_database

AUTH_DATABASE = "dataset_request_desk_auth_migrate_test"
BACKEND_ROOT = Path(__file__).resolve().parents[1]
SEED_USERS = json.loads(default_seed_path().read_text())


def _password(email: str) -> str:
    return next(row["password"] for row in SEED_USERS if row["email"] == email)


def _mount_probes(app: FastAPI) -> None:
    operator_only = require_roles(UserRole.OPERATOR, UserRole.ADMIN)
    client_only = require_roles(UserRole.CLIENT)

    @app.get("/api/v1/probe/operator")
    def operator_probe(user: User = Depends(operator_only)) -> dict[str, str]:
        return {"role": user.role}

    @app.get("/api/v1/probe/client")
    def client_probe(user: User = Depends(client_only)) -> dict[str, str]:
        return {"role": user.role}


def _login(client: TestClient, email: str, password: str | None = None) -> object:
    return client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": _password(email) if password is None else password},
    )


def _csrf(client: TestClient) -> dict[str, str]:
    return {"X-CSRF-Token": client.cookies["desk_csrf"]}


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch):
    _recreate_database(AUTH_DATABASE)
    url = _database_url(AUTH_DATABASE)
    monkeypatch.setenv("DATABASE_URL", url)
    command.upgrade(Config(str(BACKEND_ROOT / "alembic.ini")), "head")
    application = create_app(Settings(database_url=url, cookie_secure=False))
    _mount_probes(application)
    db = application.state.session_factory()
    try:
        assert seed_users(db, default_seed_path()) == len(SEED_USERS)
        assert seed_users(db, default_seed_path()) == 0
    finally:
        db.close()
    with TestClient(application) as test_client:
        yield test_client
    application.state.engine.dispose()
    _drop_database(AUTH_DATABASE)


def test_login_me_and_logout(client: TestClient) -> None:
    denied = client.get("/api/v1/auth/me")
    assert denied.status_code == 401

    logged_in = _login(client, "client-a@example.com")
    assert logged_in.status_code == 200
    assert logged_in.json()["role"] == "client"
    assert "password" not in logged_in.json()

    session_cookie = next(
        header
        for header in logged_in.headers.get_list("set-cookie")
        if header.startswith("desk_session=")
    )
    csrf_cookie = next(
        header
        for header in logged_in.headers.get_list("set-cookie")
        if header.startswith("desk_csrf=")
    )
    assert "httponly" in session_cookie.lower()
    assert "samesite=lax" in session_cookie.lower()
    assert "httponly" not in csrf_cookie.lower()

    me = client.get("/api/v1/auth/me")
    assert me.status_code == 200
    assert me.json()["email"] == "client-a@example.com"

    missing_csrf = client.post("/api/v1/auth/logout")
    assert missing_csrf.status_code == 403
    assert client.get("/api/v1/auth/me").status_code == 200

    logged_out = client.post("/api/v1/auth/logout", headers=_csrf(client))
    assert logged_out.status_code == 204
    assert client.get("/api/v1/auth/me").status_code == 401


def test_login_errors_are_generic(client: TestClient) -> None:
    unknown = _login(client, "missing@example.com", "client123")
    wrong = _login(client, "client-a@example.com", "wrong-password")
    db = client.app.state.session_factory()
    try:
        db.execute(text("UPDATE users SET is_active = false WHERE email = 'ops2@example.com'"))
        db.commit()
        stored = db.scalar(select(User.password_hash).where(User.email == "client-a@example.com"))
    finally:
        db.close()
    inactive = _login(client, "ops2@example.com")

    assert unknown.status_code == wrong.status_code == inactive.status_code == 401
    assert unknown.json() == wrong.json() == inactive.json()
    assert unknown.json()["detail"] == "Invalid email or password"
    assert stored != _password("client-a@example.com")
    assert stored.startswith("$argon2")


def test_login_ignores_role_in_the_body(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/login",
        json={
            "email": "client-a@example.com",
            "password": _password("client-a@example.com"),
            "role": "admin",
        },
    )
    assert response.status_code == 200
    assert response.json()["role"] == "client"


def test_roles_are_enforced_on_the_server(client: TestClient) -> None:
    assert client.get("/api/v1/probe/operator").status_code == 401

    _login(client, "client-a@example.com")
    assert client.get("/api/v1/probe/operator").status_code == 403
    assert client.get("/api/v1/probe/client").status_code == 200

    client.post("/api/v1/auth/logout", headers=_csrf(client))
    _login(client, "ops1@example.com")
    assert client.get("/api/v1/probe/operator").status_code == 200
    assert client.get("/api/v1/probe/client").status_code == 403

    client.post("/api/v1/auth/logout", headers=_csrf(client))
    _login(client, "admin@example.com")
    assert client.get("/api/v1/probe/operator").status_code == 200


def test_expired_session_is_rejected(client: TestClient) -> None:
    assert _login(client, "client-a@example.com").status_code == 200
    db = client.app.state.session_factory()
    try:
        db.execute(text("UPDATE sessions SET expires_at = now() - interval '1 minute'"))
        db.commit()
    finally:
        db.close()
    assert client.get("/api/v1/auth/me").status_code == 401


def test_secure_cookie_flag(client: TestClient) -> None:
    application = create_app(
        Settings(database_url=client.app.state.settings.database_url, cookie_secure=True)
    )
    try:
        with TestClient(application) as secure_client:
            response = _login(secure_client, "admin@example.com")
        cookie = next(
            header
            for header in response.headers.get_list("set-cookie")
            if header.startswith("desk_session=")
        )
        assert "secure" in cookie.lower()
    finally:
        application.state.engine.dispose()


def test_logs_omit_password_and_session_token(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    password = _password("client-a@example.com")
    access_logger.addHandler(caplog.handler)
    try:
        response = _login(client, "client-a@example.com")
    finally:
        access_logger.removeHandler(caplog.handler)

    assert response.status_code == 200
    logged = "\n".join(record.message for record in caplog.records)
    token = client.cookies["desk_session"]
    assert password not in logged
    assert token not in logged
    assert client.cookies["desk_csrf"] not in logged

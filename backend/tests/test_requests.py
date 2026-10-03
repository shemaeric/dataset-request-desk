from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.models import Assignment, Episode
from app.seed import default_seed_path, seed_users
from tests.test_auth import SEED_USERS, _password
from tests.test_schema_migration import (
    BACKEND_ROOT,
    _database_url,
    _drop_database,
    _recreate_database,
)

REQUESTS_DATABASE = "dataset_request_desk_requests_migrate_test"


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch):
    _recreate_database(REQUESTS_DATABASE)
    url = _database_url(REQUESTS_DATABASE)
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
    _drop_database(REQUESTS_DATABASE)


def _login(client: TestClient, email: str) -> None:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": _password(email)},
    )
    assert response.status_code == 200


def _csrf(client: TestClient) -> dict[str, str]:
    return {"X-CSRF-Token": client.cookies["desk_csrf"]}


def _payload(**overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "task_name": "pick cups",
        "episodes_requested": 1,
        "deadline": datetime.now(UTC).date().isoformat(),
    }
    body.update(overrides)
    return body


def _create(client: TestClient, **overrides: object) -> dict[str, object]:
    response = client.post("/api/v1/requests", json=_payload(**overrides), headers=_csrf(client))
    assert response.status_code == 201, response.text
    return response.json()


def _move(client: TestClient, request_id: int, status: str):
    return client.post(
        f"/api/v1/requests/{request_id}/transitions",
        json={"status": status},
        headers=_csrf(client),
    )


def _user_id(client: TestClient) -> int:
    response = client.get("/api/v1/auth/me")
    assert response.status_code == 200
    return response.json()["id"]


def _assign(client: TestClient, request_id: int, actor_id: int) -> None:
    db = client.app.state.session_factory()
    try:
        episode = Episode(
            source_episode_id=f"EP-{uuid4().hex}",
            robot_id="arm-1",
            task_name="pick cups",
            recorded_at=datetime.now(UTC),
            duration_seconds=30,
            operator_name="ops",
            quality="good",
        )
        db.add(episode)
        db.flush()
        db.add(
            Assignment(
                episode_id=episode.id,
                request_id=request_id,
                assigned_by_user_id=actor_id,
            )
        )
        db.commit()
    finally:
        db.close()


def test_client_creates_their_own_request(client: TestClient) -> None:
    assert client.post("/api/v1/requests", json=_payload()).status_code == 401

    _login(client, "client-a@example.com")
    owner_id = _user_id(client)
    created = _create(client, client_id=999, status="delivered")
    assert created["client_id"] == owner_id
    assert created["client_name"] == "Acme Robotics"
    assert created["assigned_episode_count"] == 0
    assert created["assignments"] == []
    assert created["status"] == "submitted"
    assert created["status_history"][0]["from_status"] is None
    assert created["status_history"][0]["to_status"] == "submitted"
    assert created["status_history"][0]["actor_user_id"] == owner_id

    today = datetime.now(UTC).date()
    for payload in (
        _payload(task_name=" "),
        _payload(episodes_requested=0),
        _payload(deadline=(today - timedelta(days=1)).isoformat()),
    ):
        response = client.post("/api/v1/requests", json=payload, headers=_csrf(client))
        assert response.status_code == 422

    _login(client, "ops1@example.com")
    denied = client.post("/api/v1/requests", json=_payload(), headers=_csrf(client))
    assert denied.status_code == 403


def test_clients_see_only_their_requests(client: TestClient) -> None:
    _login(client, "client-a@example.com")
    owned_id = _create(client)["id"]
    _login(client, "client-b@example.com")
    other_id = _create(client)["id"]

    assert [row["id"] for row in client.get("/api/v1/requests").json()] == [other_id]
    hidden = client.get(f"/api/v1/requests/{owned_id}")
    missing = client.get("/api/v1/requests/999999")
    assert hidden.status_code == missing.status_code == 404
    assert hidden.json() == missing.json()

    _login(client, "ops1@example.com")
    assert {row["id"] for row in client.get("/api/v1/requests").json()} == {owned_id, other_id}
    assert client.get(f"/api/v1/requests/{owned_id}").status_code == 200


def test_status_changes_follow_the_workflow(client: TestClient) -> None:
    _login(client, "client-a@example.com")
    created = _create(client)
    request_id = int(created["id"])
    owner_id = int(created["client_id"])
    assert _move(client, request_id, "in_progress").status_code == 403

    _login(client, "ops1@example.com")
    operator_id = _user_id(client)
    skipped = _move(client, request_id, "delivered")
    assert skipped.status_code == 409
    assert skipped.json()["detail"] == "Invalid status transition"
    assert client.get(f"/api/v1/requests/{request_id}").json()["status"] == "submitted"

    assert _move(client, request_id, "in_progress").status_code == 200
    short = _move(client, request_id, "delivered")
    assert short.status_code == 409
    assert short.json()["detail"] == "Not enough episodes assigned"
    assert len(client.get(f"/api/v1/requests/{request_id}").json()["status_history"]) == 2

    _assign(client, request_id, operator_id)
    assert _move(client, request_id, "delivered").status_code == 200
    assert _move(client, request_id, "accepted").status_code == 403

    _login(client, "client-b@example.com")
    hidden = _move(client, request_id, "accepted")
    assert hidden.status_code == 404
    assert hidden.json()["detail"] == "Request not found"

    _login(client, "client-a@example.com")
    accepted = _move(client, request_id, "accepted")
    assert accepted.status_code == 200
    assert [
        (row["from_status"], row["to_status"], row["actor_user_id"])
        for row in accepted.json()["status_history"]
    ] == [
        (None, "submitted", owner_id),
        ("submitted", "in_progress", operator_id),
        ("in_progress", "delivered", operator_id),
        ("delivered", "accepted", owner_id),
    ]
    assert all(row["changed_at"] for row in accepted.json()["status_history"])


def test_client_can_reject_a_delivery(client: TestClient) -> None:
    _login(client, "client-a@example.com")
    request_id = int(_create(client)["id"])
    owner_id = _user_id(client)
    _login(client, "ops1@example.com")
    operator_id = _user_id(client)
    assert _move(client, request_id, "in_progress").status_code == 200
    _assign(client, request_id, operator_id)
    assert _move(client, request_id, "delivered").status_code == 200

    _login(client, "client-a@example.com")
    rejected = _move(client, request_id, "rejected")
    assert rejected.status_code == 200
    assert rejected.json()["status_history"][-1]["actor_user_id"] == owner_id

    _login(client, "ops1@example.com")
    reworked = _move(client, request_id, "in_progress")
    assert reworked.status_code == 200
    assert reworked.json()["status_history"][-1]["from_status"] == "rejected"
    assert reworked.json()["status_history"][-1]["actor_user_id"] == operator_id

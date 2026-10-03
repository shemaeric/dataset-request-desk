from datetime import UTC, datetime
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

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

ASSIGNMENTS_DATABASE = "dataset_request_desk_assignments_migrate_test"


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch):
    _recreate_database(ASSIGNMENTS_DATABASE)
    url = _database_url(ASSIGNMENTS_DATABASE)
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
    _drop_database(ASSIGNMENTS_DATABASE)


def _login(client: TestClient, email: str) -> None:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": _password(email)},
    )
    assert response.status_code == 200


def _csrf(client: TestClient) -> dict[str, str]:
    return {"X-CSRF-Token": client.cookies["desk_csrf"]}


def _create(client: TestClient) -> int:
    response = client.post(
        "/api/v1/requests",
        json={
            "task_name": "pick cups",
            "episodes_requested": 1,
            "deadline": datetime.now(UTC).date().isoformat(),
        },
        headers=_csrf(client),
    )
    assert response.status_code == 201, response.text
    return int(response.json()["id"])


def _move(client: TestClient, request_id: int, status: str):
    return client.post(
        f"/api/v1/requests/{request_id}/transitions",
        json={"status": status},
        headers=_csrf(client),
    )


def _assign(client: TestClient, request_id: int, episode_id: int):
    return client.post(
        f"/api/v1/requests/{request_id}/assignments",
        json={"episode_id": episode_id},
        headers=_csrf(client),
    )


def _remove(client: TestClient, request_id: int, episode_id: int):
    return client.delete(
        f"/api/v1/requests/{request_id}/assignments/{episode_id}",
        headers=_csrf(client),
    )


def _episode(client: TestClient, quality: str) -> int:
    db = client.app.state.session_factory()
    try:
        episode = Episode(
            source_episode_id=f"EP-{uuid4().hex}",
            robot_id="arm-01",
            task_name="pick cups",
            recorded_at=datetime.now(UTC),
            duration_seconds=30,
            operator_name="ops",
            quality=quality,
        )
        db.add(episode)
        db.commit()
        return episode.id
    finally:
        db.close()


def test_assignment_rules_and_delivery(client: TestClient) -> None:
    _login(client, "client-a@example.com")
    first_id = _create(client)
    second_id = _create(client)
    good = _episode(client, "good")
    usable = _episode(client, "usable")
    bad = _episode(client, "bad")
    assert _assign(client, first_id, good).status_code == 403
    assert _remove(client, first_id, good).status_code == 403

    _login(client, "ops1@example.com")
    operator_id = client.get("/api/v1/auth/me").json()["id"]
    assert _assign(client, first_id, good).status_code == 409
    assert _move(client, first_id, "in_progress").status_code == 200
    assert _move(client, second_id, "in_progress").status_code == 200

    assert _assign(client, first_id, bad).json()["detail"] == (
        "Episode quality must be good or usable"
    )
    assert _assign(client, first_id, 999999).status_code == 404
    assert _assign(client, first_id, usable).status_code == 201

    created = _assign(client, first_id, good)
    assert created.status_code == 201
    assert created.json()["assigned_by_user_id"] == operator_id
    assert _assign(client, first_id, good).json()["detail"] == (
        "Episode is already assigned to this request"
    )
    assert _assign(client, second_id, good).json()["detail"] == (
        "Episode is already assigned to another request"
    )

    db = client.app.state.session_factory()
    try:
        db.add(
            Assignment(
                episode_id=good,
                request_id=second_id,
                assigned_by_user_id=operator_id,
            )
        )
        with pytest.raises(IntegrityError):
            db.commit()
    finally:
        db.rollback()
        db.close()

    assert _move(client, second_id, "delivered").json()["detail"] == (
        "Not enough episodes assigned"
    )
    assert _remove(client, first_id, good).status_code == 204
    assert _assign(client, second_id, good).status_code == 201
    delivered = _move(client, second_id, "delivered")
    assert delivered.status_code == 200

    _login(client, "client-a@example.com")
    assert _move(client, second_id, "rejected").status_code == 200
    _login(client, "ops1@example.com")
    assert client.get(f"/api/v1/requests/{second_id}").json()["assigned_episode_count"] == 1
    assert _assign(client, first_id, good).status_code == 409
    assert _remove(client, second_id, good).status_code == 409
    assert _remove(client, first_id, good).status_code == 404

    fresh = _episode(client, "good")
    _login(client, "admin@example.com")
    assert _assign(client, first_id, fresh).status_code == 201

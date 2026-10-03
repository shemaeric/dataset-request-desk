from datetime import UTC, date, datetime, timedelta

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import Settings
from app.main import create_app
from app.models import DatasetRequest, Episode, RequestStatusHistory, User
from app.seed import default_seed_path, seed_users
from tests.test_auth import SEED_USERS, _password
from tests.test_schema_migration import (
    BACKEND_ROOT,
    _database_url,
    _drop_database,
    _recreate_database,
)

ANALYTICS_DATABASE = "dataset_request_desk_analytics_migrate_test"
START = date(2026, 8, 14)
END = date(2026, 8, 15)


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch):
    _recreate_database(ANALYTICS_DATABASE)
    url = _database_url(ANALYTICS_DATABASE)
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
    _drop_database(ANALYTICS_DATABASE)


def _login(client: TestClient, email: str) -> None:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": _password(email)},
    )
    assert response.status_code == 200


def _at(day: date, hour: int, minute: int = 0, second: int = 0) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, second, tzinfo=UTC)


def _episode(db, source: str, robot: str, task: str, when: datetime, quality: str) -> None:
    db.add(
        Episode(
            source_episode_id=source,
            robot_id=robot,
            task_name=task,
            recorded_at=when,
            duration_seconds=30,
            operator_name="ops",
            quality=quality,
        )
    )


def _request(
    db,
    client_id: int,
    status: str,
    submitted_at: datetime,
    events: list[tuple[str, str, datetime]],
    created_at: datetime | None = None,
) -> None:
    row = DatasetRequest(
        client_id=client_id,
        task_name="pick cups",
        episodes_requested=1,
        deadline=date(2026, 9, 1),
        status=status,
        created_at=created_at or submitted_at,
        updated_at=submitted_at,
    )
    db.add(row)
    db.flush()
    db.add(
        RequestStatusHistory(
            request_id=row.id,
            from_status=None,
            to_status="submitted",
            actor_user_id=client_id,
            changed_at=submitted_at,
        )
    )
    for previous, nxt, when in events:
        db.add(
            RequestStatusHistory(
                request_id=row.id,
                from_status=previous,
                to_status=nxt,
                actor_user_id=client_id,
                changed_at=when,
            )
        )


def test_analytics_uses_the_utc_window_and_first_delivery(client: TestClient) -> None:
    params = {"start_date": START.isoformat(), "end_date": END.isoformat()}
    assert client.get("/api/v1/analytics", params=params).status_code == 401
    _login(client, "client-a@example.com")
    assert client.get("/api/v1/analytics", params=params).status_code == 403

    _login(client, "ops1@example.com")
    assert (
        client.get(
            "/api/v1/analytics",
            params={"start_date": "2026-08-15", "end_date": "2026-08-14"},
        ).status_code
        == 422
    )
    assert (
        client.get(
            "/api/v1/analytics",
            params={"start_date": "2026-01-01", "end_date": "2027-01-03"},
        ).status_code
        == 422
    )

    db = client.app.state.session_factory()
    try:
        client_id = db.scalar(select(User.id).where(User.email == "client-a@example.com"))
        assert client_id is not None
        _episode(
            db,
            "before",
            "arm-01",
            "boundary",
            _at(START - timedelta(days=1), 23, 59, 59),
            "usable",
        )
        _episode(db, "start-a", "arm-01", "boundary", _at(START, 0), "usable")
        _episode(db, "start-b", "arm-02", "boundary", _at(START, 0), "usable")
        _episode(db, "start-c", "arm-01", "boundary", _at(START, 12), "usable")
        _episode(db, "end", "arm-01", "boundary", _at(END, 23, 59, 59), "usable")
        _episode(db, "after", "arm-01", "boundary", _at(END + timedelta(days=1), 0), "usable")

        noon = _at(START, 10)
        for name, count in (
            ("alpha", 3),
            ("beta", 3),
            ("gamma", 2),
            ("delta", 1),
            ("epsilon", 1),
            ("zeta", 1),
        ):
            for index in range(count):
                _episode(db, f"{name}-{index}", "arm-03", name, noon, "good")
        for index in range(4):
            _episode(db, f"alpha-bad-{index}", "arm-03", "alpha", noon, "bad")
        _episode(db, "alpha-old", "arm-03", "alpha", _at(START - timedelta(days=1), 10), "good")

        submitted = _at(START, 10)
        _request(
            db,
            client_id,
            "delivered",
            submitted,
            [("submitted", "delivered", submitted + timedelta(hours=4))],
            created_at=datetime(2020, 1, 1, tzinfo=UTC),
        )
        _request(
            db,
            client_id,
            "rejected",
            submitted + timedelta(hours=1),
            [
                ("submitted", "delivered", submitted + timedelta(hours=3)),
                ("delivered", "rejected", submitted + timedelta(hours=4)),
                ("in_progress", "delivered", submitted + timedelta(hours=9)),
            ],
        )
        _request(db, client_id, "submitted", submitted + timedelta(hours=2), [])
        _request(
            db,
            client_id,
            "delivered",
            _at(START - timedelta(days=1), 10),
            [("submitted", "delivered", submitted)],
        )
        _request(
            db,
            client_id,
            "delivered",
            _at(END, 23),
            [("submitted", "delivered", _at(END + timedelta(days=1), 0))],
        )
        db.commit()
    finally:
        db.close()

    body = client.get("/api/v1/analytics", params=params).json()
    assert body["episodes_per_day"] == [
        {"day": "2026-08-14", "robot_id": "arm-01", "count": 2},
        {"day": "2026-08-14", "robot_id": "arm-02", "count": 1},
        {"day": "2026-08-14", "robot_id": "arm-03", "count": 15},
        {"day": "2026-08-15", "robot_id": "arm-01", "count": 1},
    ]
    assert body["requests_by_status"] == [
        {"status": "submitted", "count": 1},
        {"status": "in_progress", "count": 0},
        {"status": "delivered", "count": 2},
        {"status": "accepted", "count": 0},
        {"status": "rejected", "count": 1},
    ]
    assert body["median_seconds_to_delivery"] == 7200
    assert body["top_tasks"] == [
        {"task_name": "alpha", "count": 3},
        {"task_name": "beta", "count": 3},
        {"task_name": "gamma", "count": 2},
        {"task_name": "delta", "count": 1},
        {"task_name": "epsilon", "count": 1},
    ]

    empty = client.get(
        "/api/v1/analytics",
        params={"start_date": "2026-01-01", "end_date": "2026-01-01"},
    ).json()
    assert empty["episodes_per_day"] == []
    assert empty["top_tasks"] == []
    assert empty["median_seconds_to_delivery"] is None
    assert [row["count"] for row in empty["requests_by_status"]] == [0, 0, 0, 0, 0]

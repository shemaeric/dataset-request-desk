from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import Settings
from app.episodes import MAX_UPLOAD_BYTES
from app.main import create_app
from app.models import Episode
from app.seed import default_seed_path, seed_users
from tests.test_auth import SEED_USERS, _password
from tests.test_schema_migration import (
    BACKEND_ROOT,
    _database_url,
    _drop_database,
    _recreate_database,
)

EPISODES_DATABASE = "dataset_request_desk_episodes_migrate_test"
SEED_CSV = Path(__file__).resolve().parents[2] / "seed" / "episodes.csv"
FIXTURE = """\
episode_id,robot_id,task_name,recorded_at,duration_seconds,operator_name,quality
EP-1,arm-01,pick cup,2026-08-14T09:12:00,30,Diane,good
EP-1,arm-01,pick cup,2026-08-14T09:12:00,30,Diane,good
EP-1,arm-01,pick cup,2026-08-14T09:12:00,31,Diane,good
ep-2, arm-01,  Pick Cup ,14/08/2026 09:15,33,Eric,Good
EP-2,arm-02,wipe table,2026-08-14 09:12:00,10,Eric,good
,arm-01,pick cup,2026-08-14T09:12:00,30,Diane,good
EP-3,arm-99,pick cup,2026-08-14T09:12:00,30,Diane,usable
EP-4,arm-01,pick cup,not a date,30,Diane,good
EP-5,arm-01,pick cup,2026-08-14T09:20:00Z,-5,Diane,USABLE
EP-6,arm-99,pick cup,2026-08-14T09:12:00,30,Diane,good
EP-6,arm-01,pick cup,2026-08-14T09:12:00,12,Diane,usable
"""


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch):
    _recreate_database(EPISODES_DATABASE)
    url = _database_url(EPISODES_DATABASE)
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
    _drop_database(EPISODES_DATABASE)


def _login(client: TestClient, email: str) -> None:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": _password(email)},
    )
    assert response.status_code == 200


def _csrf(client: TestClient) -> dict[str, str]:
    return {"X-CSRF-Token": client.cookies["desk_csrf"]}


def _upload(client: TestClient, content: bytes):
    return client.post(
        "/api/v1/episodes/import",
        files={"file": ("episodes.csv", content, "text/csv")},
        headers=_csrf(client),
    )


def _stored(client: TestClient, source_id: str) -> Episode | None:
    db = client.app.state.session_factory()
    try:
        return db.scalar(select(Episode).where(Episode.source_episode_id == source_id))
    finally:
        db.close()


def test_import_reports_rows_and_does_not_overwrite(client: TestClient) -> None:
    assert client.get("/api/v1/episodes").status_code == 401
    _login(client, "client-a@example.com")
    assert _upload(client, FIXTURE.encode()).status_code == 403
    assert client.get("/api/v1/episodes").status_code == 403

    _login(client, "ops1@example.com")
    bad_header = _upload(client, b"foo,bar\n1,2\n")
    assert bad_header.status_code == 400

    first = _upload(client, FIXTURE.encode())
    assert first.status_code == 200, first.text
    assert first.json()["created"] == 3
    assert first.json()["skipped"] == 1
    assert first.json()["conflicts"] == 2
    assert first.json()["invalid"] == 5
    assert {(item["row"], item["reason"]) for item in first.json()["errors"]} == {
        (4, "episode EP-1 already exists with different data"),
        (6, "episode EP-2 already exists with different data"),
        (7, "episode_id is required"),
        (8, "unknown robot"),
        (9, "recorded_at is not a valid timestamp"),
        (10, "duration must be a positive integer"),
        (11, "unknown robot"),
    }

    kept = _stored(client, "EP-1")
    normalized = _stored(client, "EP-2")
    later = _stored(client, "EP-6")
    assert kept is not None and kept.duration_seconds == 30 and kept.quality == "good"
    assert normalized is not None and normalized.robot_id == "arm-01"
    assert normalized.task_name == "pick cup" and normalized.quality == "good"
    assert later is not None and later.quality == "usable"
    assert _stored(client, "EP-3") is None

    second = _upload(client, FIXTURE.encode())
    assert second.status_code == 200
    assert second.json()["created"] == 0
    assert second.json()["skipped"] == 4
    assert second.json()["conflicts"] == 2
    assert second.json()["invalid"] == 5
    assert _stored(client, "EP-1") is not None
    assert _stored(client, "EP-1").duration_seconds == 30

    page = client.get(
        "/api/v1/episodes",
        params={"task_name": "Pick Cup", "quality": "good", "limit": 1, "offset": 0},
    )
    assert page.status_code == 200
    body = page.json()
    assert body["total"] == 2
    assert body["limit"] == 1
    assert body["items"][0]["source_episode_id"] == "EP-1"
    nxt = client.get(
        "/api/v1/episodes",
        params={"task_name": "pick cup", "quality": "good", "limit": 1, "offset": 1},
    )
    assert nxt.json()["items"][0]["source_episode_id"] == "EP-2"
    usable = client.get("/api/v1/episodes", params={"quality": "usable"})
    assert [row["source_episode_id"] for row in usable.json()["items"]] == ["EP-6"]

    _login(client, "admin@example.com")
    before = client.get("/api/v1/episodes", params={"limit": 1}).json()["total"]
    garbled = _upload(client, b"\xff\xfe")
    assert garbled.status_code == 400
    assert garbled.json()["detail"] == "CSV file must be UTF-8"
    huge = _upload(client, b"x" * (MAX_UPLOAD_BYTES + 1))
    assert huge.status_code == 400
    assert huge.json()["detail"] == "CSV file is too large"
    added = _upload(
        client,
        b"episode_id,robot_id,task_name,recorded_at,duration_seconds,operator_name,quality\n"
        b"\n"
        b"EP-90,arm-01,pick cup,2026-08-14T10:00:00,12,Diane,good\n"
        b",,,,,,\n",
    )
    assert added.status_code == 200, added.text
    assert added.json()["created"] == 1
    assert added.json()["invalid"] == 0
    assert added.json()["skipped"] == 0
    assert client.get("/api/v1/episodes", params={"limit": 1}).json()["total"] == before + 1
    assert _stored(client, "EP-1").duration_seconds == 30


def test_seed_file_imports_twice(client: TestClient) -> None:
    _login(client, "ops1@example.com")
    raw = SEED_CSV.read_bytes()
    first = _upload(client, raw)
    assert first.status_code == 200, first.text
    created = first.json()["created"]
    assert created > 0
    assert first.json()["invalid"] > 0
    assert first.json()["conflicts"] > 0

    second = _upload(client, raw)
    assert second.status_code == 200
    assert second.json()["created"] == 0
    assert second.json()["skipped"] == created + first.json()["skipped"]
    assert second.json()["conflicts"] == first.json()["conflicts"]
    assert second.json()["invalid"] == first.json()["invalid"]

    original = _stored(client, "EP-00011")
    folded = _stored(client, "EP-00003")
    spaced = _stored(client, "EP-00006")
    cased = _stored(client, "EP-00010")
    assert original is not None and original.quality == "bad"
    assert folded is not None and folded.task_name == "fold towel"
    assert spaced is not None and spaced.task_name == "pick cup"
    assert cased is not None and cased.quality == "usable"
    assert _stored(client, "EP-00024") is None
    assert _stored(client, "ep-00003") is None

    listed = client.get("/api/v1/episodes", params={"limit": 1, "offset": 0})
    assert listed.json()["total"] == created
    assert (
        listed.json()["items"][0]["source_episode_id"]
        < client.get("/api/v1/episodes", params={"limit": 1, "offset": 1}).json()["items"][0][
            "source_episode_id"
        ]
    )

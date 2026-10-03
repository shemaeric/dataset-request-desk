import json

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.db import database_config_from
from app.logging import access_logger
from app.main import create_app

client = TestClient(create_app())

LOG_FIELDS = {"method", "path", "status", "duration_ms", "user_id"}


def _log_payloads(caplog: pytest.LogCaptureFixture) -> list[dict[str, object]]:
    return [json.loads(record.message) for record in caplog.records]


def test_application_starts() -> None:
    application = create_app()
    with TestClient(application) as started:
        response = started.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert application.state.database.url.startswith("postgresql+psycopg://")


def test_health_returns_ok() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_does_not_report_database_status() -> None:
    body = client.get("/health").json()

    assert body == {"status": "ok"}
    assert "database" not in body


def test_access_log_records_request(caplog: pytest.LogCaptureFixture) -> None:
    access_logger.addHandler(caplog.handler)
    try:
        response = client.get("/health")
    finally:
        access_logger.removeHandler(caplog.handler)

    assert response.status_code == 200
    payloads = _log_payloads(caplog)
    assert payloads
    payload = payloads[-1]
    assert set(payload) == LOG_FIELDS
    assert payload["method"] == "GET"
    assert payload["path"] == "/health"
    assert payload["status"] == 200
    assert payload["user_id"] is None
    assert isinstance(payload["duration_ms"], float)


def test_access_log_ignores_client_supplied_user_id(caplog: pytest.LogCaptureFixture) -> None:
    access_logger.addHandler(caplog.handler)
    try:
        client.get("/health", headers={"X-User-Id": "999"})
    finally:
        access_logger.removeHandler(caplog.handler)

    payload = _log_payloads(caplog)[-1]
    assert payload["user_id"] is None
    assert "999" not in json.dumps(payload)


def test_access_log_omits_secrets(caplog: pytest.LogCaptureFixture) -> None:
    secret_values = (
        "super-secret-token",
        "session-id-value",
        "hunter2-password",
        "query-token-value",
    )
    access_logger.addHandler(caplog.handler)
    try:
        response = client.post(
            "/health?access_token=query-token-value",
            headers={
                "Authorization": "Bearer super-secret-token",
                "Cookie": "session=session-id-value",
            },
            json={"password": "hunter2-password"},
        )
    finally:
        access_logger.removeHandler(caplog.handler)

    assert response.status_code == 405
    logged = "\n".join(record.message for record in caplog.records)
    payload = _log_payloads(caplog)[-1]
    assert set(payload) == LOG_FIELDS
    assert payload["path"] == "/health"
    assert payload["user_id"] is None
    for secret in secret_values:
        assert secret not in logged


def test_settings_read_database_url_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+psycopg://desk:desk@db:5432/dataset_request_desk",
    )
    settings = Settings()
    config = database_config_from(settings)

    assert config.url == "postgresql+psycopg://desk:desk@db:5432/dataset_request_desk"


def test_empty_database_url_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "   ")

    with pytest.raises(ValueError, match="DATABASE_URL"):
        create_app()

import json

import pytest
from fastapi.testclient import TestClient

from app.logging import access_logger
from app.main import app

client = TestClient(app)


def test_health_returns_ok() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_access_log_records_request(caplog: pytest.LogCaptureFixture) -> None:
    access_logger.addHandler(caplog.handler)
    try:
        response = client.get("/health")
    finally:
        access_logger.removeHandler(caplog.handler)

    assert response.status_code == 200
    payloads = [json.loads(record.message) for record in caplog.records]
    assert payloads
    payload = payloads[-1]
    assert payload["method"] == "GET"
    assert payload["path"] == "/health"
    assert payload["status"] == 200
    assert payload["user_id"] is None
    assert isinstance(payload["duration_ms"], float)

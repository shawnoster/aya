"""Smoke tests for /health."""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_returns_ok() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["ok"] is True


def test_health_returns_version_string() -> None:
    body = client.get("/health").json()
    assert isinstance(body["version"], str)
    assert body["version"]  # non-empty

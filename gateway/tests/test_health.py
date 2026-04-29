"""Smoke tests for /health."""

from fastapi.testclient import TestClient
from pytest import MonkeyPatch

from app.main import app

client = TestClient(app)


def test_health_returns_ok() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["ok"] is True


def test_health_defaults_version_to_dev(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.delenv("GIT_SHA", raising=False)
    body = client.get("/health").json()
    assert body["version"] == "dev"


def test_health_uses_git_sha_when_set(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("GIT_SHA", "abc123")
    body = client.get("/health").json()
    assert body["version"] == "abc123"

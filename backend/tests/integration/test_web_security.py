"""Local web security layer: session, CSRF, Host/Origin allow-lists, headers, body limits."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def secure(monkeypatch):
    monkeypatch.setenv("SESSION_REQUIRED", "true")
    from app.config import get_settings

    get_settings.cache_clear()
    yield TestClient(app)
    get_settings.cache_clear()


def test_api_requires_a_session(secure) -> None:
    r = secure.get("/api/documents")
    assert r.status_code == 401 and r.json()["detail"] == "session_required"


def test_session_then_csrf(secure) -> None:
    token = secure.get("/api/session").json()["csrf_token"]
    assert secure.cookies.get("fable_session")
    assert secure.get("/api/documents").status_code == 200
    body = {"op": "mask", "scope": "occurrence", "target": {"span_id": "x"}}
    r = secure.post("/api/documents/unknown/decisions", json=body,
                    headers={"Origin": "http://localhost:5174"})
    assert r.status_code == 403 and r.json()["detail"] == "csrf_failed"
    r = secure.post("/api/documents/unknown/decisions", json=body,
                    headers={"X-CSRF-Token": token, "Origin": "http://localhost:5174"})
    assert r.status_code == 404  # passed the security layer, reached the handler


def test_health_and_session_are_public(secure) -> None:
    assert secure.get("/api/health").status_code == 200
    assert secure.get("/health").status_code == 200


def test_foreign_host_and_origin_are_refused(secure) -> None:
    assert secure.get("/api/health", headers={"Host": "evil.example"}).status_code == 403
    r = secure.get("/api/health", headers={"Origin": "http://evil.example"})
    assert r.status_code == 403 and r.json()["detail"] == "origin_not_allowed"


def test_security_headers(secure) -> None:
    r = secure.get("/api/health")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["referrer-policy"] == "no-referrer"
    assert "default-src 'none'" in r.headers["content-security-policy"]
    assert r.headers["cache-control"] == "no-store"


def test_oversized_json_body_is_refused(secure) -> None:
    token = secure.get("/api/session").json()["csrf_token"]
    big = {"always_mask": ["x" * 1000] * 400}
    r = secure.put("/api/settings", json=big, headers={"X-CSRF-Token": token})
    assert r.status_code == 413


def test_validation_errors_never_echo_input(secure) -> None:
    token = secure.get("/api/session").json()["csrf_token"]
    r = secure.put("/api/settings", json={"default_mode": "Ayşe Kaya 10000000146"},
                   headers={"X-CSRF-Token": token})
    assert r.status_code == 422
    assert "Ayşe" not in r.text and "10000000146" not in r.text

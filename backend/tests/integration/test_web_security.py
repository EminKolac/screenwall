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


def test_testserver_host_is_refused_unless_configured(monkeypatch) -> None:
    """TestClient sends Host "testserver". Production must not accept it: a DNS-rebinding page
    could otherwise name that host and read every original value."""
    monkeypatch.setenv("ALLOWED_HOSTS", "localhost,127.0.0.1")
    from app.config import get_settings

    get_settings.cache_clear()
    client = TestClient(app)
    r = client.get("/api/health")
    assert r.status_code == 403 and r.json()["detail"] == "host_not_allowed"
    assert client.get("/api/health", headers={"Host": "localhost:8000"}).status_code == 200


def test_non_ascii_csrf_token_is_refused_not_a_server_error(secure) -> None:
    client = TestClient(app, raise_server_exceptions=False)
    assert client.get("/api/session").status_code == 200
    r = client.put("/api/settings", json={}, headers={"X-CSRF-Token": "jeton-ş".encode()})
    assert r.status_code == 403 and r.json()["detail"] == "csrf_failed"


def test_origin_allowlist_is_only_the_configured_ui_origins(monkeypatch) -> None:
    from app.config import Settings

    monkeypatch.delenv("CORS_ALLOW_ORIGINS", raising=False)
    assert Settings().origin_allowlist() == {"http://localhost:5174", "http://127.0.0.1:5174"}
    only = Settings(cors_allow_origins="http://localhost:5174")
    assert only.origin_allowlist() == {"http://localhost:5174"}  # nothing added per host/port


@pytest.mark.parametrize("origin", ["http://localhost:5173", "http://127.0.0.1:5173",
                                    "http://localhost:8000", "http://127.0.0.1:5175"])
def test_other_local_ports_are_foreign_origins(secure, origin) -> None:
    """Another local dev server (any other Vite project on 5173) must not get credentialed API
    access, nor read the CSRF token through CORS."""
    r = secure.get("/api/session", headers={"Origin": origin})
    assert r.status_code == 403 and r.json()["detail"] == "origin_not_allowed"
    pre = secure.options("/api/session", headers={"Origin": origin,
                                                  "Access-Control-Request-Method": "GET"})
    assert "access-control-allow-origin" not in pre.headers


@pytest.mark.parametrize("origin", ["http://localhost:5174", "http://127.0.0.1:5174"])
def test_the_ui_origins_are_allowed(secure, origin) -> None:
    r = secure.get("/api/session", headers={"Origin": origin})
    assert r.status_code == 200 and r.headers["access-control-allow-origin"] == origin

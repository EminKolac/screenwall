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


# ------------------------------------------------------------------ launch token (packaged app)

LAUNCH = "synthetic-launch-token-for-tests"


@pytest.fixture
def launched(monkeypatch):
    """The packaged app: the launcher sets LAUNCH_TOKEN and opens the UI with it."""
    monkeypatch.setenv("SESSION_REQUIRED", "true")
    monkeypatch.setenv("LAUNCH_TOKEN", LAUNCH)
    from app.config import get_settings

    get_settings.cache_clear()
    yield TestClient(app)
    get_settings.cache_clear()


@pytest.mark.parametrize("sent", [None, "", "wrong", LAUNCH + "x", "jeton-ş".encode()])
def test_without_the_launch_token_no_session_is_issued(launched, sent) -> None:
    """Another account on the computer reaches 127.0.0.1 too, but cannot read the token."""
    headers = {} if sent is None else {"X-Launch-Token": sent}
    r = launched.get("/api/session", headers=headers)
    assert r.status_code == 401 and r.json()["detail"] == "launch_token_required"
    assert not launched.cookies.get("fable_session")
    assert launched.get("/api/documents").status_code == 401


def test_the_launch_token_opens_a_session_that_then_needs_no_token(launched) -> None:
    r = launched.get("/api/session", headers={"X-Launch-Token": LAUNCH})
    assert r.status_code == 200 and launched.cookies.get("fable_session")
    token = r.json()["csrf_token"]
    again = launched.get("/api/session")  # a reload: the live cookie is enough
    assert again.status_code == 200 and again.json()["csrf_token"] == token
    assert launched.get("/api/documents").status_code == 200


def test_a_stale_cookie_needs_the_launch_token_again(launched) -> None:
    launched.cookies.set("fable_session", "unknown-session", path="/api")
    r = launched.get("/api/session")
    assert r.status_code == 401 and r.json()["detail"] == "launch_token_required"


def test_without_launch_token_setting_the_session_is_open(secure, monkeypatch) -> None:
    """Development (start.sh, Vite) sets no LAUNCH_TOKEN: nothing changes there."""
    from app.config import get_settings

    monkeypatch.delenv("LAUNCH_TOKEN", raising=False)
    get_settings.cache_clear()
    assert get_settings().launch_token == ""
    assert secure.get("/api/session").status_code == 200


def test_the_launcher_hands_the_token_over_in_a_file(monkeypatch, tmp_path) -> None:
    """LAUNCH_TOKEN_FILE, not the environment: a process listing never shows the token."""
    from app.config import Settings

    monkeypatch.delenv("LAUNCH_TOKEN", raising=False)
    token_file = tmp_path / "launch-token"
    token_file.write_text(LAUNCH + "\n", encoding="ascii")
    assert Settings(launch_token_file=token_file).launch_token == LAUNCH
    assert Settings(launch_token_file="").launch_token == ""


@pytest.mark.parametrize("content", [None, "", "  \n", "kısa", "has space in it 0123456789"])
def test_an_unusable_token_file_stops_the_app(monkeypatch, tmp_path, content) -> None:
    """Fail closed: a launcher that meant to set a token never gets an open server instead."""
    from pydantic import ValidationError

    from app.config import Settings

    monkeypatch.delenv("LAUNCH_TOKEN", raising=False)
    token_file = tmp_path / "launch-token"
    if content is not None:
        token_file.write_text(content, encoding="utf-8")
    with pytest.raises(ValidationError):
        Settings(launch_token_file=token_file)

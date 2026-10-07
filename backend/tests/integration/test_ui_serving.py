"""The packaged single-server app: the API also serves the built UI (UI_DIST).

The launcher (packaging/) starts uvicorn on 127.0.0.1:8765 with UI_DIST=<app/frontend/dist> and
CORS_ALLOW_ORIGINS=http://127.0.0.1:8765,http://localhost:8765. These tests build that app with
a tiny dist (index.html + one hashed asset) next to a canary file that must never be served, and
keep the real security layer on (session, CSRF, Host/Origin allow-lists).
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import _ui_file, create_app
from tests import posix_only

ORIGIN = "http://127.0.0.1:8765"
LOCAL_ORIGIN = "http://localhost:8765"
CANARY = "SYNTHETIC-CANARY-outside-the-dist"
INDEX = (
    '<!doctype html><html lang="tr"><head><title>Screenwall</title>'
    '<script type="module" crossorigin src="/assets/index-abc123.js"></script>'
    '<link rel="stylesheet" crossorigin href="/assets/index-abc123.css"></head>'
    '<body><div id="root"></div></body></html>'
)
JS = "export const screenwall = 1;\n"
_DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


@pytest.fixture
def dist(tmp_path_factory):
    """pkg/dist holds the UI; pkg/secret.txt sits one level up, as a traversal target."""
    pkg = tmp_path_factory.mktemp("pkg")
    root = pkg / "dist"
    (root / "assets").mkdir(parents=True)
    (root / "index.html").write_text(INDEX, encoding="utf-8")
    (root / "assets" / "index-abc123.js").write_text(JS, encoding="utf-8")
    (root / "assets" / "index-abc123.css").write_text("body{margin:0}", encoding="utf-8")
    (root / "favicon.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'/>",
                                      encoding="utf-8")
    (pkg / "secret.txt").write_text(CANARY, encoding="utf-8")
    return root


def _packaged_app(monkeypatch, dist):
    monkeypatch.setenv("UI_DIST", str(dist))
    monkeypatch.setenv("CORS_ALLOW_ORIGINS", f"{ORIGIN},{LOCAL_ORIGIN}")
    monkeypatch.setenv("ALLOWED_HOSTS", "localhost,127.0.0.1")  # production: no "testserver"
    monkeypatch.setenv("SESSION_REQUIRED", "true")
    get_settings.cache_clear()
    return create_app()


@pytest.fixture
def ui(monkeypatch, dist) -> TestClient:
    return TestClient(_packaged_app(monkeypatch, dist), base_url=ORIGIN)


def _session(client: TestClient) -> str:
    r = client.get("/api/session")
    assert r.status_code == 200
    return r.json()["csrf_token"]


# ------------------------------------------------------------------ the UI itself


def test_root_is_index_html_with_a_csp_that_allows_the_bundle(ui):
    r = ui.get("/")
    assert r.status_code == 200 and r.text == INDEX
    assert r.headers["content-type"].startswith("text/html")
    assert r.headers["cache-control"] == "no-cache"
    csp = r.headers["content-security-policy"]
    # Vite's <script type="module" crossorigin src="/assets/..."> and its stylesheet: same origin.
    assert "script-src 'self'" in csp and "style-src 'self'" in csp
    assert "connect-src 'self'" in csp and "frame-ancestors 'none'" in csp
    assert "default-src 'none'" not in csp  # that is the API's policy
    assert r.headers["x-content-type-options"] == "nosniff"


@pytest.mark.parametrize("path", ["/d/abc", "/d/abc/chat", "/d/abc/"])
def test_client_routes_get_index_html(ui, path):
    r = ui.get(path)
    assert r.status_code == 200 and r.text == INDEX
    assert r.headers["content-type"].startswith("text/html")


def test_assets_are_served_with_their_content_types(ui):
    # A crossorigin module script request carries the page's own Origin: it must pass.
    r = ui.get("/assets/index-abc123.js", headers={"Origin": ORIGIN})
    assert r.status_code == 200 and r.text == JS
    assert r.headers["content-type"].startswith("text/javascript")
    r = ui.get("/assets/index-abc123.css")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/css")
    r = ui.get("/favicon.svg")
    assert r.status_code == 200 and r.headers["content-type"].startswith("image/svg+xml")
    head = ui.head("/")
    assert head.status_code == 200 and head.content == b""


def test_a_foreign_origin_cannot_load_the_bundle(ui):
    r = ui.get("/assets/index-abc123.js", headers={"Origin": "http://evil.example"})
    assert r.status_code == 403 and r.json() == {"detail": "origin_not_allowed"}


def test_a_missing_file_is_404_not_index_html(ui):
    for path in ("/assets/index-old999.js", "/robots.txt"):
        r = ui.get(path)
        assert r.status_code == 404 and r.json() == {"detail": "Not Found"}


@pytest.mark.parametrize(
    "path",
    [
        "/../secret.txt",
        "/assets/../../secret.txt",
        "/%2e%2e/secret.txt",
        "/assets/%2e%2e/%2e%2e/secret.txt",
        "/assets/..%2f..%2fsecret.txt",
        "/..%5csecret.txt",
        "/assets/%2e%2e%5c%2e%2e%5csecret.txt",
        "/C:/secret.txt",
        "/index.html%00.js",
    ],
)
def test_traversal_never_leaks_a_file(ui, path):
    r = ui.get(path)
    assert r.status_code == 404
    assert CANARY not in r.text and "<html" not in r.text


async def test_a_raw_dot_dot_path_is_refused(monkeypatch, dist):
    """Clients normalise "/../"; send the decoded path straight to the ASGI app instead."""
    app = _packaged_app(monkeypatch, dist)
    for path in ("/../secret.txt", "/assets/../../secret.txt", "/./index.html"):
        sent: list[dict] = []

        async def receive() -> dict:
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message: dict, sent=sent) -> None:
            sent.append(message)

        scope = {
            "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
            "method": "GET", "scheme": "http", "path": path, "raw_path": path.encode(),
            "root_path": "", "query_string": b"", "headers": [(b"host", b"127.0.0.1:8765")],
            "client": ("127.0.0.1", 50000), "server": ("127.0.0.1", 8765),
        }
        await app(scope, receive, send)
        body = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
        assert sent[0]["status"] == 404, path
        assert CANARY.encode() not in body


def test_the_file_lookup_itself_stays_inside_the_dist(dist):
    """Second layer behind the segment check: resolution never leaves the dist."""
    root = dist.resolve()
    assert _ui_file(root, ["", "assets", "index-abc123.js"]) == root / "assets/index-abc123.js"
    for segments in (["", "..", "secret.txt"], ["", "assets", "..", "..", "secret.txt"],
                     ["", "assets"], ["", "nope.js"], [""]):
        assert _ui_file(root, segments) is None, segments


@posix_only.FILE_MODES
def test_a_symlink_out_of_the_dist_is_not_followed(ui, dist):
    (dist / "assets" / "leak.txt").symlink_to(dist.parent / "secret.txt")
    r = ui.get("/assets/leak.txt")
    assert r.status_code == 404 and CANARY not in r.text


# ------------------------------------------------------------------ the API keeps precedence


def test_unknown_api_paths_stay_json_404(ui):
    _session(ui)
    for path in ("/api/nope", "/api/documents/x/nope", "/api", "/health/x"):
        r = ui.get(path)
        assert r.status_code == 404, path
        assert r.headers["content-type"].startswith("application/json")
        assert r.json() == {"detail": "Not Found"}


def test_api_routes_win_over_the_ui(ui):
    assert ui.get("/health").json() == {"status": "ok"}
    r = ui.get("/api/documents")  # no session yet: the API answers, not index.html
    assert r.status_code == 401 and r.json() == {"detail": "session_required"}
    _session(ui)
    r = ui.get("/api/documents")
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    assert "default-src 'none'" in r.headers["content-security-policy"]
    assert ui.get("/api/chat").status_code == 405  # POST-only route: still "wrong method"


def test_only_get_and_head_reach_the_ui(ui):
    r = ui.post("/d/abc", headers={"Origin": ORIGIN})
    assert r.status_code == 404 and r.json() == {"detail": "Not Found"}


# ------------------------------------------------------------------ security on the UI's origin


def test_upload_from_the_ui_origin_with_session_and_csrf(ui, docx_tr):
    token = _session(ui)
    files = {"file": ("synthetic.docx", docx_tr, _DOCX_MIME)}
    r = ui.post("/api/documents", files=files,
                headers={"Origin": ORIGIN, "X-CSRF-Token": token})
    assert r.status_code == 202, r.text
    assert r.headers["cache-control"] == "no-store"
    r = ui.post("/api/documents", files=files, headers={"Origin": ORIGIN})
    assert r.status_code == 403 and r.json() == {"detail": "csrf_failed"}


@pytest.mark.parametrize("origin", ["http://evil.example", "http://localhost:5174",
                                    "http://127.0.0.1:8000", "null"])
def test_a_foreign_origin_is_refused_even_with_session_and_csrf(ui, origin):
    token = _session(ui)
    r = ui.put("/api/settings", json={"default_mode": "destructive"},
               headers={"Origin": origin, "X-CSRF-Token": token})
    assert r.status_code == 403 and r.json() == {"detail": "origin_not_allowed"}


def test_settings_change_from_localhost_8765(monkeypatch, dist):
    client = TestClient(_packaged_app(monkeypatch, dist), base_url=LOCAL_ORIGIN)
    assert client.get("/").text == INDEX  # Host localhost:8765 is accepted
    token = _session(client)
    r = client.put("/api/settings", json={"default_mode": "destructive"},
                   headers={"Origin": LOCAL_ORIGIN, "X-CSRF-Token": token})
    assert r.status_code == 200 and r.json()["default_mode"] == "destructive"


def test_a_foreign_host_is_refused(ui):
    r = ui.get("/", headers={"Host": "evil.example:8765"})
    assert r.status_code == 403 and r.json() == {"detail": "host_not_allowed"}


# ------------------------------------------------------------------ UI_DIST unset or empty


def test_without_ui_dist_nothing_changes(monkeypatch):
    monkeypatch.delenv("UI_DIST", raising=False)
    get_settings.cache_clear()
    client = TestClient(create_app())
    assert get_settings().ui_dist is None
    for path in ("/", "/d/abc", "/assets/index-abc123.js"):
        r = client.get(path)
        assert r.status_code == 404 and r.json() == {"detail": "Not Found"}


@pytest.mark.parametrize("value", ["", "   "])
def test_a_blank_ui_dist_is_unset(monkeypatch, value):
    monkeypatch.setenv("UI_DIST", value)
    get_settings.cache_clear()
    assert get_settings().ui_dist is None
    assert TestClient(create_app()).get("/").status_code == 404


def test_a_ui_dist_without_index_html_is_not_served(monkeypatch, dist):
    (dist / "index.html").rename(dist / "index.bak")
    monkeypatch.setenv("UI_DIST", str(dist))
    get_settings.cache_clear()
    assert get_settings().ui_index() is None
    client = TestClient(create_app())
    assert client.get("/").status_code == 404
    assert client.get("/assets/index-abc123.js").status_code == 404

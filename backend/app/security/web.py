"""Local web security: Host/Origin allow-lists, session + CSRF, response headers, body limits.

The API only listens on 127.0.0.1, but a browser can still be tricked into talking to it: another
site via DNS rebinding, or a cross-site form post. Before v2 the API had no authentication, so
"unmask + preview" worked as a de-anonymization oracle for any local page. Now:

- the Host header must be an allowed local name and a present Origin must be allowed;
- every /api route except the session and health endpoints needs a session cookie issued by
  GET /api/session (HttpOnly, SameSite=Strict);
- every mutating request also needs the X-CSRF-Token header matching that session;
- request bodies are bounded BEFORE multipart parsing, and uploads stay in memory (never spooled
  to an unencrypted temporary file).

Pattern taken from Screenwall V2 (backend/app/studio/api.py).
"""
from __future__ import annotations

import secrets
import time

from starlette.formparsers import MultiPartParser
from starlette.requests import Request
from starlette.responses import JSONResponse

SESSION_COOKIE = "fable_session"
SESSION_TTL_S = 12 * 3600
_PUBLIC = {"/api/session", "/api/health", "/health"}
_MAX_SESSIONS = 1000

# Starlette spools multipart parts above 1 MiB to a temporary file on disk; keep uploads in memory.
MultiPartParser.spool_max_size = 64 * 1024 * 1024


def _upload_limit() -> int:
    from app.config import get_settings

    return get_settings().max_upload_mb * 1024 * 1024 + 1024 * 1024


class BodyLimitMiddleware:
    """Count request bytes as they arrive and stop at the limit, before any multipart parsing —
    a Content-Length check alone is bypassed by chunked requests."""

    def __init__(self, app, other_limit: int = 256 * 1024) -> None:
        self.app = app
        self.other_limit = other_limit

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] not in ("POST", "PUT", "PATCH"):
            return await self.app(scope, receive, send)
        limit = _upload_limit() if scope["path"] == "/api/documents" else self.other_limit
        chunks: list[bytes] = []
        size = 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body = message.get("body", b"")
            size += len(body)
            if size > limit:
                return await JSONResponse({"detail": "file_too_large"}, status_code=413)(
                    scope, receive, send)
            chunks.append(body)
            if not message.get("more_body", False):
                break
        buffered = b"".join(chunks)
        delivered = False

        async def replay():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": buffered, "more_body": False}
            return await receive()

        return await self.app(scope, replay, send)


class SessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, tuple[str, float]] = {}

    def issue(self, existing: str | None) -> tuple[str, str, bool]:
        """Return (session_id, csrf_token, is_new)."""
        now = time.monotonic()
        current = self._sessions.get(existing or "")
        if current and now - current[1] <= SESSION_TTL_S:
            return existing or "", current[0], False
        self._sessions = {k: v for k, v in self._sessions.items() if now - v[1] < SESSION_TTL_S}
        if len(self._sessions) >= _MAX_SESSIONS:
            self._sessions.pop(next(iter(self._sessions)))
        sid, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        self._sessions[sid] = (csrf, now)
        return sid, csrf, True

    def csrf_for(self, sid: str | None) -> str | None:
        entry = self._sessions.get(sid or "")
        if entry is None or time.monotonic() - entry[1] > SESSION_TTL_S:
            return None
        return entry[0]


def _host(request: Request) -> str:
    host = request.headers.get("host", "").lower()
    if host.startswith("["):  # [::1]:8000
        return host.split("]")[0] + "]"
    return host.rsplit(":", 1)[0] if ":" in host else host


def _csrf_matches(sent: str, expected: str) -> bool:
    """Constant-time comparison of bytes: `compare_digest` raises TypeError on a str with
    non-ASCII characters, and a header decoded as latin-1 can carry any byte."""
    try:
        return secrets.compare_digest(sent.encode("utf-8"), expected.encode("utf-8"))
    except (TypeError, UnicodeError):
        return False


def install(app, sessions: SessionStore) -> None:
    """Settings are read per request (they are cached), so tests can change them per test."""
    from app.config import get_settings

    app.add_middleware(BodyLimitMiddleware)

    @app.middleware("http")
    async def local_security(request: Request, call_next):
        settings = get_settings()
        hosts = settings.host_allowlist()  # tests add TestClient's "testserver" via settings
        origins = settings.origin_allowlist()
        if _host(request) not in hosts:
            return JSONResponse({"detail": "host_not_allowed"}, status_code=403)
        origin = request.headers.get("origin")
        if origin and origin not in origins:
            return JSONResponse({"detail": "origin_not_allowed"}, status_code=403)
        if request.headers.get("sec-fetch-site") == "cross-site":
            return JSONResponse({"detail": "cross_site_not_allowed"}, status_code=403)
        path = request.url.path
        if request.method in ("POST", "PUT", "PATCH"):
            limit = _upload_limit() if path == "/api/documents" else 256 * 1024
            length = request.headers.get("content-length")
            if length and length.isdigit() and int(length) > limit:
                return JSONResponse({"detail": "file_too_large"}, status_code=413)
        if settings.session_required and path.startswith("/api/") and path not in _PUBLIC \
                and request.method != "OPTIONS":
            csrf = sessions.csrf_for(request.cookies.get(SESSION_COOKIE))
            if csrf is None:
                return JSONResponse({"detail": "session_required"}, status_code=401)
            if request.method not in ("GET", "HEAD") and not _csrf_matches(
                    request.headers.get("x-csrf-token", ""), csrf):
                return JSONResponse({"detail": "csrf_failed"}, status_code=403)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        if path.startswith("/api/"):
            response.headers.setdefault("Cache-Control", "no-store")
            response.headers["Content-Security-Policy"] = (
                "default-src 'none'; frame-ancestors 'none'")
        else:
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; connect-src 'self'; img-src 'self' data: blob:; "
                "style-src 'self' 'unsafe-inline'; script-src 'self'; frame-ancestors 'none'")
        return response

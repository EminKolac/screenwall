"""FastAPI application entrypoint.

Wires the routers (documents + review, chat, session/health/settings), the local web security
layer (security/web.py) and the background worker. The API is meant to listen on 127.0.0.1 only
(start.sh). Validation errors never echo request input back (it may contain personal data).

With UI_DIST set (the packaged app, packaging/), the same server also serves the built UI; see
`install_ui`. Unset, nothing changes: in development Vite serves the UI.
"""
from __future__ import annotations

import logging
import mimetypes
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from starlette.types import Receive, Scope, Send

from app.api import chat, documents, system
from app.config import get_settings
from app.security import web
from app.security.logging import configure_pii_safe_logging
from app.security.permissions import lock_down_store
from app.services.deps import get_worker

logger = logging.getLogger(__name__)

_LAYERS = ("1_original", "2_extracted", "3_anonymized", "4_validation", "5_chat_context")

# Paths that belong to the API: an unknown one stays a JSON 404, never the UI's index.html.
_BACKEND_PREFIXES = ("/api", "/health")
# Content types of the built UI, set explicitly: `mimetypes` reads the Windows registry, where
# ".js" can be text/plain, and the browser refuses a module script with that type (nosniff).
_UI_TYPES = {
    ".html": "text/html", ".js": "text/javascript", ".mjs": "text/javascript",
    ".css": "text/css", ".svg": "image/svg+xml", ".json": "application/json",
    ".map": "application/json", ".png": "image/png", ".ico": "image/x-icon",
    ".webp": "image/webp", ".woff": "font/woff", ".woff2": "font/woff2", ".txt": "text/plain",
}
_NO_CACHE = {"Cache-Control": "no-cache"}  # index.html and unhashed files: revalidate


def _is_backend_path(path: str) -> bool:
    return any(path == p or path.startswith(p + "/") for p in _BACKEND_PREFIXES)


def _ui_file(root: Path, segments: list[str]) -> Path | None:
    """The regular file these path segments name inside `root` (symlinks resolved), or None.
    Nothing outside `root` is ever returned."""
    parts = [s for s in segments if s]
    if not parts:
        return None
    try:
        resolved = root.joinpath(*parts).resolve(strict=True)
    except (OSError, RuntimeError, ValueError):
        return None
    if not resolved.is_relative_to(root) or not resolved.is_file():
        return None
    return resolved


def install_ui(app: FastAPI, ui_dist: Path) -> None:
    """Serve the built UI from `ui_dist` behind every API route.

    The handler is the router's fallback (`router.default`), so it only sees requests that no
    route matched, not even by path: API routes keep precedence and a wrong method on an API
    path stays 405. It answers GET/HEAD outside /api and /health with the file of that name
    inside `ui_dist`, or, for a client-side route such as /d/abc, with index.html. A path with
    "..", a backslash, a colon or NUL in a segment, or a missing file-like path (a stale
    /assets/x.js), is a 404. The security middleware (security/web.py) still runs first: Host and
    Origin allow-lists, the HTML Content-Security-Policy, nosniff.
    """
    root = ui_dist.resolve()
    index = root / "index.html"
    not_found = app.router.default

    async def serve_ui(scope: Scope, receive: Receive, send: Send) -> None:
        path = scope.get("path", "")
        if scope["type"] != "http" or scope["method"] not in ("GET", "HEAD") \
                or _is_backend_path(path):
            return await not_found(scope, receive, send)
        segments = path.split("/")
        if any(s in (".", "..") or any(c in s for c in "\\:\x00") for s in segments):
            return await not_found(scope, receive, send)
        target = _ui_file(root, segments)
        if target is not None:
            kind = _UI_TYPES.get(target.suffix.lower()) or mimetypes.guess_type(target.name)[0]
            hashed = segments[1] == "assets"  # Vite's content-hashed bundle files
            response = FileResponse(target, media_type=kind or "application/octet-stream",
                                    headers=None if hashed else _NO_CACHE)
        elif "." in segments[-1] or not index.is_file():  # a file that is not there
            return await not_found(scope, receive, send)
        else:
            response = FileResponse(index, media_type="text/html", headers=_NO_CACHE)
        await response(scope, receive, send)

    app.router.default = serve_ui


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_pii_safe_logging()  # redact PII from all logs (uvicorn's too) before anything runs
    settings = get_settings()
    settings.storage_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    for layer_dir in _LAYERS:
        settings.layer_path(layer_dir).mkdir(parents=True, exist_ok=True, mode=0o700)
    # mkdir never tightens what exists; a store from an older version is 0755/0644.
    counts = lock_down_store(settings.storage_root, _LAYERS)
    if counts["dirs"] or counts["files"] or counts["errors"]:
        logger.info("storage permissions: %d directories, %d files made private "
                    "(%d symlinks skipped, %d errors)", counts["dirs"], counts["files"],
                    counts["symlinks"], counts["errors"])
    worker = None
    if not settings.process_inline:
        worker = get_worker()
        worker.start()
        worker.recover()
    app.state.worker = worker
    try:
        yield
    finally:
        if worker is not None:
            worker.stop()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="Fable", version="2.0.0", lifespan=lifespan)
    app.state.sessions = web.SessionStore()
    app.state.worker = None
    web.install(app, app.state.sessions)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=sorted(settings.origin_allowlist()),
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["Content-Type", "X-CSRF-Token"],
    )

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request, exc: RequestValidationError):
        return JSONResponse(
            {"detail": [{"loc": list(e["loc"]), "type": e["type"]} for e in exc.errors()]},
            status_code=422)

    @app.get("/health")
    def root_health() -> dict:
        return {"status": "ok"}

    app.include_router(system.router)
    app.include_router(documents.router)
    app.include_router(chat.router)
    index = settings.ui_index()
    if index is not None:
        install_ui(app, index.parent)
    elif settings.ui_dist is not None:
        logger.warning("UI_DIST is set but holds no index.html; the UI is not served")
    return app


app = create_app()

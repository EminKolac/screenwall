"""FastAPI application entrypoint.

Wires the routers (documents + review, chat, session/health/settings), the local web security
layer (security/web.py) and the background worker. The API is meant to listen on 127.0.0.1 only
(start.sh). Validation errors never echo request input back (it may contain personal data).
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import chat, documents, system
from app.config import get_settings
from app.security import web
from app.security.logging import configure_pii_safe_logging
from app.services.deps import get_worker

_LAYERS = ("1_original", "2_extracted", "3_anonymized", "4_validation", "5_chat_context")


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_pii_safe_logging()  # redact PII from all logs before anything runs
    settings = get_settings()
    settings.storage_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    for layer_dir in _LAYERS:
        settings.layer_path(layer_dir).mkdir(parents=True, exist_ok=True, mode=0o700)
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
    return app


app = create_app()

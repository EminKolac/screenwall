"""FastAPI application entrypoint.

Phase 1 exposes health + the status state machine so the scaffold is runnable and reviewable.
Feature routers (documents, review, chat) are wired in their respective phases.
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import chat, documents, review
from app.config import get_settings
from app.models.document import DocumentStatus
from app.security.logging import configure_pii_safe_logging


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_pii_safe_logging()  # redact PII from all logs before anything runs
    settings = get_settings()
    # Ensure storage layer directories exist (local backend).
    for layer_dir in ("1_original", "2_extracted", "3_anonymized", "4_validation", "5_chat_context"):
        settings.layer_path(layer_dir).mkdir(parents=True, exist_ok=True)
    yield


app = FastAPI(title="Document Anonymization Platform", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in get_settings().cors_allow_origins.split(",") if o.strip()],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict:
    s = get_settings()
    return {
        "status": "ok",
        "env": s.app_env,
        "auditor": {"provider": s.auditor_provider, "model": s.auditor_model},
        "max_iterations": s.max_iterations,
    }


@app.get("/api/statuses")
def statuses() -> dict:
    """The processing state machine, for the dashboard (machine value + display label)."""
    return {"statuses": [{"value": s.value, "label": s.display} for s in DocumentStatus]}


app.include_router(documents.router)
app.include_router(review.router)
app.include_router(chat.router)

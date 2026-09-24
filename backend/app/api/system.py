"""Session, health and user settings (frontend/src/api/contract.ts)."""
from __future__ import annotations

import shutil
from typing import Literal

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel

from app.config import get_settings
from app.security.web import SESSION_COOKIE, SESSION_TTL_S
from app.services.user_settings import UserSettings, load_user_settings, save_user_settings

router = APIRouter(prefix="/api", tags=["system"])


@router.get("/session")
def session(request: Request, response: Response) -> dict:
    """Issue (or reuse) the local session. The cookie is HttpOnly and SameSite=Strict; the CSRF
    token in the body must accompany every mutating request."""
    sessions = request.app.state.sessions
    sid, csrf, is_new = sessions.issue(request.cookies.get(SESSION_COOKIE))
    if is_new:
        response.set_cookie(SESSION_COOKIE, sid, httponly=True, samesite="strict",
                            max_age=SESSION_TTL_S, path="/api")
    return {"csrf_token": csrf}


@router.get("/health")
def health(request: Request) -> dict:
    s = get_settings()
    reachable = False
    if s.auditor_provider == "ollama":
        from app.audit.ollama_provider import OllamaProvider

        try:
            reachable = OllamaProvider(s.ollama_base_url, s.auditor_model).is_available()
        except Exception:  # noqa: BLE001 — health must not fail because a probe failed
            reachable = False
    worker = getattr(request.app.state, "worker", None)
    return {
        "status": "ok",
        "auditor": {"provider": s.auditor_provider, "model": s.auditor_model,
                    "reachable": reachable},
        "ocr": {"available": shutil.which("tesseract") is not None},
        "worker": {"alive": bool(worker and worker.alive)},
    }


class SettingsBody(BaseModel):
    default_mode: Literal["mapping", "destructive"] | None = None
    chat_default_provider: Literal["ollama", "claude_cli", "codex_cli"] | None = None
    always_mask: list[str] | None = None
    never_mask: list[str] | None = None


@router.get("/settings")
def get_user_settings() -> dict:
    return load_user_settings(get_settings()).model_dump()


@router.put("/settings")
def put_user_settings(body: SettingsBody) -> dict:
    settings = get_settings()
    current = load_user_settings(settings).model_dump()
    current.update({k: v for k, v in body.model_dump().items() if v is not None})
    return save_user_settings(settings, UserSettings.model_validate(current)).model_dump()

"""Session, health and user settings (frontend/src/api/contract.ts)."""
from __future__ import annotations

import shutil
from typing import Literal

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

from app.config import get_settings
from app.security.web import SESSION_COOKIE, SESSION_TTL_S, token_matches
from app.services.user_settings import (
    UserSettings,
    UserSettingsUnreadable,
    load_user_settings,
    update_user_settings,
)

router = APIRouter(prefix="/api", tags=["system"])


@router.get("/session")
def session(request: Request, response: Response) -> dict:
    """Issue (or reuse) the local session. The cookie is HttpOnly and SameSite=Strict; the CSRF
    token in the body must accompany every mutating request.

    With LAUNCH_TOKEN set (the packaged app), a NEW session needs the X-Launch-Token header with
    that value; a request holding a live session cookie keeps it without the header."""
    sessions = request.app.state.sessions
    existing = request.cookies.get(SESSION_COOKIE)
    launch_token = get_settings().launch_token
    if launch_token and sessions.csrf_for(existing) is None and not token_matches(
            request.headers.get("x-launch-token", ""), launch_token):
        raise HTTPException(status_code=401, detail="launch_token_required")
    sid, csrf, is_new = sessions.issue(existing)
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
            reachable = OllamaProvider(s.ollama_base_url, s.auditor_model,
                                       allow_remote=s.ollama_allow_remote).is_available()
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
    always_mask_family: dict[str, str] | None = None  # round-trips what GET returned


@router.get("/settings")
def get_user_settings() -> dict:
    return load_user_settings(get_settings()).model_dump()


@router.put("/settings")
def put_user_settings(body: SettingsBody) -> dict:
    """One read-modify-write under the settings lock. A file that cannot be read is never
    overwritten: 500 until it is fixed or moved away."""
    changes = {k: v for k, v in body.model_dump().items() if v is not None}

    def apply(current: UserSettings) -> UserSettings:
        return UserSettings.model_validate({**current.model_dump(), **changes})

    try:
        return update_user_settings(get_settings(), apply).model_dump()
    except UserSettingsUnreadable as e:
        raise HTTPException(status_code=500, detail="internal_error") from e

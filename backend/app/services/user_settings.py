"""Settings a user changes in the app (Settings dialog), persisted next to the document store.

Environment variables (app.config.Settings) provide the defaults; this file stores what the user
chose. The term lists are global: "always mask" and "never mask" apply to every document. They
are empty by default. `pipeline.terms.effective_terms` adds them to every pipeline run whose
storage root holds this file — the standalone evaluation runners included — unless
`Settings.term_lists` is False. The scorecard runs with it False and a fresh storage root under
its own work directory, so these lists never reach a reported number.
"""
from __future__ import annotations

import json
import os
import threading
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.config import Settings

_LOCK = threading.Lock()
_FILE = "user_settings.json"
_MAX_TERMS = 500
_MAX_TERM_CHARS = 200


class UserSettings(BaseModel):
    default_mode: Literal["mapping", "destructive"] = "mapping"
    chat_default_provider: Literal["ollama", "claude_cli", "codex_cli"] = "ollama"
    always_mask: list[str] = Field(default_factory=list)
    never_mask: list[str] = Field(default_factory=list)

    @field_validator("always_mask", "never_mask")
    @classmethod
    def _clean_terms(cls, terms: list[str]) -> list[str]:
        out: list[str] = []
        for t in terms:
            t = " ".join(str(t).split())
            if t and len(t) <= _MAX_TERM_CHARS and t not in out:
                out.append(t)
        return out[:_MAX_TERMS]


def _defaults(settings: Settings) -> UserSettings:
    # The lists start empty: project terms from the environment (DENY_TERMS / ALLOW_TERMS) are
    # added on top in pipeline.terms and are not editable from the app.
    return UserSettings(
        default_mode=settings.anonymization_mode,
        chat_default_provider=getattr(settings, "chat_default_provider", "ollama"),
    )


def load_user_settings(settings: Settings) -> UserSettings:
    path = settings.storage_root / _FILE
    with _LOCK:
        if not path.exists():
            return _defaults(settings)
        try:
            return UserSettings.model_validate(json.loads(path.read_text(encoding="utf-8")))
        except (ValueError, OSError):
            return _defaults(settings)


def save_user_settings(settings: Settings, value: UserSettings) -> UserSettings:
    path = settings.storage_root / _FILE
    data = json.dumps(value.model_dump(), ensure_ascii=False).encode("utf-8")
    with _LOCK:
        settings.storage_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        tmp = path.with_name(path.name + ".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    return value

"""Settings a user changes in the app (Settings dialog), persisted next to the document store.

Environment variables (app.config.Settings) provide the defaults; this file stores what the user
chose. The term lists are global: "always mask" and "never mask" apply to every document, and a
term masked globally from the review screen keeps the family the reviewer chose
(`always_mask_family`). They are empty by default. `pipeline.terms.effective_terms` adds the lists
to every pipeline run whose storage root holds this file — the standalone evaluation runners
included — unless `Settings.term_lists` is False. The scorecard runs with it False and a fresh
storage root under its own work directory, so these lists never reach a reported number.

Robustness: an invalid FIELD falls back to its default alone (only its name is logged, never a
value); a file that cannot be read at all is never overwritten (writes raise
UserSettingsUnreadable until it is fixed); every change goes through `update_user_settings`, which
holds the lock across the whole read-modify-write.
"""
from __future__ import annotations

import json
import logging
import threading
from collections.abc import Callable
from typing import Literal

from pydantic import BaseModel, Field, ValidationError, ValidationInfo, field_validator

from app.anonymization.lists import term_key
from app.anonymization.types import valid_family
from app.config import Settings
from app.storage.local import write_private

logger = logging.getLogger(__name__)
_LOCK = threading.Lock()
_FILE = "user_settings.json"
_MAX_TERMS = 500
_MAX_TERM_CHARS = 200


class UserSettingsUnreadable(Exception):
    """user_settings.json exists but cannot be read or parsed; it is left untouched."""


class UserSettings(BaseModel):
    default_mode: Literal["mapping", "destructive"] = "mapping"
    chat_default_provider: Literal["ollama", "claude_cli", "codex_cli"] = "ollama"
    always_mask: list[str] = Field(default_factory=list)
    never_mask: list[str] = Field(default_factory=list)
    # Placeholder family of a globally masked term, keyed by its spelling in `always_mask`.
    always_mask_family: dict[str, str] = Field(default_factory=dict)

    @field_validator("always_mask", "never_mask")
    @classmethod
    def _clean_terms(cls, terms: list[str]) -> list[str]:
        out: list[str] = []
        seen: set[str] = set()
        for t in terms:
            t = " ".join(str(t).split())
            if t and len(t) <= _MAX_TERM_CHARS and term_key(t) not in seen:
                seen.add(term_key(t))
                out.append(t)
        return out[:_MAX_TERMS]

    @field_validator("always_mask_family")
    @classmethod
    def _families_follow_the_list(cls, families: dict[str, str],
                                  info: ValidationInfo) -> dict[str, str]:
        """Only terms still in `always_mask`, keyed by that spelling; invalid families drop."""
        spelled = {term_key(t): t for t in info.data.get("always_mask", [])}
        return {spelled[term_key(term)]: fam for term, fam in families.items()
                if term_key(term) in spelled and valid_family(fam)}


def _defaults(settings: Settings) -> UserSettings:
    # The lists start empty: project terms from the environment (DENY_TERMS / ALLOW_TERMS) are
    # added on top in pipeline.terms and are not editable from the app.
    return UserSettings(
        default_mode=settings.anonymization_mode,
        chat_default_provider=getattr(settings, "chat_default_provider", "ollama"),
    )


def _read(settings: Settings) -> UserSettings:
    """The stored settings; the defaults when there is no file. The caller holds _LOCK."""
    path = settings.storage_root / _FILE
    if not path.exists():
        return _defaults(settings)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        logger.warning("user settings unreadable: %s", type(e).__name__)
        raise UserSettingsUnreadable from e
    if not isinstance(raw, dict):
        logger.warning("user settings unreadable: not a JSON object")
        raise UserSettingsUnreadable
    return _valid_fields(raw, _defaults(settings))


def _valid_fields(raw: dict, defaults: UserSettings) -> UserSettings:
    """Every field that validates on its own is kept; an invalid one falls back to its default
    and only its NAME is logged (a value may be a personal term). In the term lists, a bad entry
    drops alone, so one stray value cannot switch a whole always-mask list off."""
    merged = defaults.model_dump()
    for name in UserSettings.model_fields:
        if name not in raw:
            continue
        value = _usable_entries(name, raw[name])
        try:
            UserSettings.model_validate({**merged, name: value})
        except ValidationError:
            logger.warning("user settings: invalid field %s ignored", name)
            continue
        merged[name] = value
    return UserSettings.model_validate(merged)


def _usable_entries(name: str, value: object) -> object:
    if isinstance(value, list):
        kept = [v for v in value if isinstance(v, str)]
    elif isinstance(value, dict):
        kept = {k: v for k, v in value.items() if isinstance(k, str) and isinstance(v, str)}
    else:
        return value
    if len(kept) != len(value):
        logger.warning("user settings: %d invalid entries in %s ignored", len(value) - len(kept),
                       name)
    return kept


def load_user_settings(settings: Settings) -> UserSettings:
    """What the user chose. An unreadable file gives the defaults so the app still starts;
    writing stays refused until the file is fixed."""
    with _LOCK:
        try:
            return _read(settings)
        except UserSettingsUnreadable:
            return _defaults(settings)


def readable(settings: Settings) -> bool:
    """False when the user's lists are in use but the file cannot be read: their always-mask
    terms are then missing from every run (pipeline.runner.note_settings makes that blocking)."""
    if not settings.term_lists:
        return True
    with _LOCK:
        try:
            _read(settings)
        except UserSettingsUnreadable:
            return False
    return True


def update_user_settings(settings: Settings,
                         change: Callable[[UserSettings], UserSettings]) -> UserSettings:
    """Read, change and write under ONE lock, so concurrent changes cannot lose each other's
    terms. Raises UserSettingsUnreadable, writing nothing, when the file cannot be read."""
    with _LOCK:
        new = UserSettings.model_validate(change(_read(settings)).model_dump())
        settings.storage_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        data = json.dumps(new.model_dump(), ensure_ascii=False).encode("utf-8")
        write_private(settings.storage_root / _FILE, data)
        return new


def save_user_settings(settings: Settings, value: UserSettings) -> UserSettings:
    return update_user_settings(settings, lambda _current: value)


def mask_families(settings: Settings) -> dict[str, str]:
    """Family of each globally masked term, for the engine ({} when term lists are off, like
    `pipeline.terms.effective_terms`; the file is then not read)."""
    if not settings.term_lists:
        return {}
    return dict(load_user_settings(settings).always_mask_family)


def with_always(prefs: UserSettings, term: str, family: str | None = None) -> UserSettings:
    """`term` joins the always-mask list (keeping `family`) and leaves the never-mask list."""
    key = term_key(term)
    spelled = next((t for t in prefs.always_mask if term_key(t) == key), None)
    families = {k: v for k, v in prefs.always_mask_family.items() if term_key(k) != key}
    if family:
        families[spelled or term] = family
    return UserSettings.model_validate({
        **prefs.model_dump(),
        "always_mask": prefs.always_mask if spelled else [*prefs.always_mask, term],
        "never_mask": [t for t in prefs.never_mask if term_key(t) != key],
        "always_mask_family": families,
    })


def with_never(prefs: UserSettings, term: str) -> UserSettings:
    """`term` joins the never-mask list and leaves the always-mask list (with its family)."""
    key = term_key(term)
    listed = any(term_key(t) == key for t in prefs.never_mask)
    return UserSettings.model_validate({
        **prefs.model_dump(),
        "always_mask": [t for t in prefs.always_mask if term_key(t) != key],
        "always_mask_family": {k: v for k, v in prefs.always_mask_family.items()
                               if term_key(k) != key},
        "never_mask": prefs.never_mask if listed else [*prefs.never_mask, term],
    })

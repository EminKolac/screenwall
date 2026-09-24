"""The one place that assembles the always-mask and never-mask lists for a run.

The seeded Turkish allow-list is still included here: removing it is the first measured
experiment of Faz 2 (plan §4), and it must change in exactly one place when that happens.

`Settings.term_lists=False` turns every list off at once — the seeded allow-list, ALLOW_TERMS /
DENY_TERMS and the user's Settings lists (user_settings.json is then not even read). The
evaluation scorecard runs that way so no reported number depends on a list.
"""
from __future__ import annotations

from app.anonymization.allowlist_tr import default_allow_list
from app.config import Settings
from app.services.user_settings import load_user_settings


def effective_terms(settings: Settings) -> tuple[list[str], list[str]]:
    """(always-mask, never-mask) for one run."""
    if not settings.term_lists:
        return [], []
    prefs = load_user_settings(settings)
    deny = _unique(settings.deny_list() + prefs.always_mask)
    allow = _unique(default_allow_list() + settings.allow_list() + prefs.never_mask)
    return deny, allow


def _unique(terms: list[str]) -> list[str]:
    return list(dict.fromkeys(t for t in terms if t and t.strip()))

"""Deterministic placeholder mapping.

Same entity value → same token across the whole document (e.g. "Ahmet Yılmaz" → <PERSON_1>
everywhere). The mapping (placeholder ↔ original) is sensitive and persists only in storage
layer 2 (extracted); it is never serialized to clients or sent to any provider.

Codex Phase-1 review (HIGH): normalization adds Unicode NFKC so width/diacritic/compatibility
variants collapse consistently. KNOWN LIMITATION (documented collision policy): two *different*
people sharing an identical normalized display name map to the SAME token — acceptable for
anonymization (no information is leaked; it can only over-merge). Phase 3 adds entity-specific
canonicalizers (checksum-aware IDs, phone/IBAN digit-only) and context disambiguation.
"""
from __future__ import annotations

import re
import unicodedata


def _normalize(value: str) -> str:
    value = unicodedata.normalize("NFKC", value)
    return re.sub(r"\s+", " ", value).strip().casefold()


class PlaceholderMapper:
    """Assigns and reuses `<TYPE_n>` tokens deterministically within one document."""

    def __init__(self) -> None:
        self._assigned: dict[str, dict[str, str]] = {}   # type -> {normalized -> token}
        self._counters: dict[str, int] = {}              # type -> next index
        self.mapping: dict[str, str] = {}                # token -> original (layer-2 only)

    def placeholder_for(self, entity_type: str, original: str) -> str:
        key = _normalize(original)
        per_type = self._assigned.setdefault(entity_type, {})
        if key in per_type:
            return per_type[key]
        idx = self._counters.get(entity_type, 0) + 1
        self._counters[entity_type] = idx
        token = f"<{entity_type}_{idx}>"
        per_type[key] = token
        self.mapping[token] = original
        return token

    def counts(self) -> dict[str, int]:
        return dict(self._counters)

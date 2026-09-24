"""Entity type table — the one place that says how each detector entity type behaves.

Before Faz 1 this knowledge lived in five overlapping sets and two mapping tables spread over
engine.py and presidio_engine.py. Every flag below reproduces the old behaviour exactly; the parity
snapshots in tests/parity prove it.

- family: placeholder family, rendered as <FAMILY_n>. Several detector types fold into one family
  so the same value always gets the same token (TR_GSM and PHONE_NUMBER are both PHONE).
- tier: overlap priority in resolve_spans. 0 = format/checksum-validated pattern, 2 = statistical
  NER (spaCy gives every hit the same 0.85, so its score carries no confidence), 1 = the rest.
- adjacency_safe: structural type that may be re-detected across table cells or line wraps.
- propagate: a masked value's spelling variants are masked document-wide ("any" mode).
- ortho_gated: statistical NER type subject to the lowercase-initial gate (gates.py).
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class TypeInfo:
    family: str
    tier: int = 1
    adjacency_safe: bool = False
    propagate: bool = False
    ortho_gated: bool = False


def _pattern(family: str, *, tier: int = 1, adjacent: bool = True) -> TypeInfo:
    return TypeInfo(family, tier=tier, adjacency_safe=adjacent, propagate=adjacent)


def _ner(family: str, *, gated: bool = True) -> TypeInfo:
    return TypeInfo(family, tier=2, ortho_gated=gated)


TYPES: dict[str, TypeInfo] = {
    # Validated patterns (tier 0), all adjacency-safe and propagating.
    "TR_IBAN": _pattern("IBAN", tier=0),
    "TR_TCKN": _pattern("TCKN", tier=0),
    "TR_GSM": _pattern("PHONE", tier=0),
    "TR_PHONE": _pattern("PHONE", tier=0),
    "IBAN_CODE": _pattern("IBAN", tier=0),
    "CREDIT_CARD": _pattern("CARD", tier=0),
    "EMAIL_ADDRESS": _pattern("EMAIL", tier=0),
    "US_SSN": _pattern("SSN", tier=0),
    "UK_PHONE": _pattern("PHONE", tier=0),
    "IP_ADDRESS": _pattern("IP", tier=0),
    "URL": _pattern("URL", tier=0),
    # Other structural patterns (tier 1), adjacency-safe and propagating.
    "TR_ACCOUNT": _pattern("ACCOUNT"),
    "SECRET_KEY": _pattern("SECRET"),
    "TR_PLATE": _pattern("PLATE"),
    "TR_PASSPORT": _pattern("PASSPORT"),
    "TR_VKN": _pattern("VKN"),
    # Structural Turkish recognizers that propagate but are not re-joined across cells.
    "TR_ADDRESS": TypeInfo("LOCATION", propagate=True),
    "TR_COMPANY": TypeInfo("ORG", propagate=True),
    # Presidio's phonenumbers-based recognizer: tier 1, not re-joined, not propagated.
    "PHONE_NUMBER": TypeInfo("PHONE"),
    # Context/list recognizers (tier 1).
    "TR_PERSON_CTX": TypeInfo("PERSON"),
    "TR_SALARY_BAND": TypeInfo("SALARY"),
    "TR_DISABILITY": TypeInfo("SENSITIVE"),
    "TR_HEALTH": TypeInfo("SENSITIVE"),
    "SENSITIVE": TypeInfo("SENSITIVE"),
    "PASSPORT": TypeInfo("PASSPORT"),
    "DRIVER_LICENSE": TypeInfo("DL"),
    "US_DRIVER_LICENSE": TypeInfo("DL"),
    # Families fed by the optional Privacy Filter label map.
    "ACCOUNT": TypeInfo("ACCOUNT"),
    "SECRET": TypeInfo("SECRET"),
    "USERNAME": TypeInfo("USERNAME"),
    "PLATE": TypeInfo("PLATE"),
    # Statistical NER (tier 2). DATE_TIME is outranked like NER but not orthographically gated.
    "PERSON": _ner("PERSON"),
    "LOCATION": _ner("LOCATION"),
    "ORGANIZATION": _ner("ORG"),
    "NRP": _ner("NRP"),
    "DATE_TIME": _ner("DATE", gated=False),
}


USER_PREFIX = "USER:"  # a human decision: "USER:ORG" masks with the ORG family and always wins
_FAMILY_NAME = re.compile(r"[A-Z][A-Z_]{1,19}")


def user_type(family_name: str) -> str:
    return f"{USER_PREFIX}{family_name}"


def valid_family(name: object) -> bool:
    """A family a reviewer may choose: "ORG", "PERSON", ... (the WHOLE string must match, so
    "ORG\\n" or "org" are refused)."""
    return isinstance(name, str) and _FAMILY_NAME.fullmatch(name) is not None


def info(entity_type: str) -> TypeInfo:
    """Unknown detector types keep their own name as family and sit in tier 1."""
    known = TYPES.get(entity_type)
    if known is not None:
        return known
    if entity_type.startswith(USER_PREFIX):
        return TypeInfo(entity_type[len(USER_PREFIX):] or "SENSITIVE", tier=0)
    return TypeInfo(entity_type)


def family(entity_type: str) -> str:
    return info(entity_type).family


def tier(entity_type: str) -> int:
    return info(entity_type).tier


ADJACENCY_SAFE = frozenset(t for t, i in TYPES.items() if i.adjacency_safe)
PROPAGATION = frozenset(t for t, i in TYPES.items() if i.propagate)
ORTHO_GATED = frozenset(t for t, i in TYPES.items() if i.ortho_gated)

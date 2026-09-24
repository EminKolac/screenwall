"""Compatibility import path for the engine (pre-Faz-1 name).

The engine now lives in `app.anonymization.engine.Engine`; Presidio remains its recognizer
framework (analyzer.py). This module keeps the old names working for callers and tests until
they are migrated. The original implementation is kept in archive/anonymization_v1/.
"""
from __future__ import annotations

from app.anonymization.engine import Engine as PresidioEngine
from app.anonymization.gates import implausible_person_ner as _is_implausible_person_ner
from app.anonymization.gates import lowercase_initial_ner as _is_lowercase_initial_ner
from app.anonymization.propagate import norm_projection as _norm_projection
from app.anonymization.propagate import projection_prefixes as _projection_prefixes
from app.anonymization.types import family as _ph_type

__all__ = [
    "PresidioEngine", "_is_implausible_person_ner",
    "_is_lowercase_initial_ner", "_norm_projection", "_projection_prefixes", "_ph_type",
]

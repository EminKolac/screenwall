"""Anonymize a filename stem so the generated PDF's name never leaks PII.

Data-room filenames are themselves confidential ("e2vc Fund III Deck", "List of LPs…"). This runs
the stem through the SAME Presidio recognizers as the content, turns detected PII into
filesystem-safe `TYPE_n` tokens, and keeps non-PII words. It is stateless (no mapping read), so the
download path still touches only storage layer 3.
"""
from __future__ import annotations

import re
from pathlib import Path

from app.anonymization.presidio_engine import PresidioEngine
from app.extraction.base import Block, ExtractedContent
from app.models.document import FileKind, Language

_UNSAFE = re.compile(r"[^\w.\-]+", re.UNICODE)  # keep letters (incl. Turkish), digits, . _ -
_MAX_LEN = 80


def anonymize_filename(
    name: str, language: Language = Language.unknown, deny_terms: list[str] | None = None,
) -> str:
    """Return a filesystem-safe, PII-masked stem (no extension) derived from `name`.

    `deny_terms` (fund/brand names NER can't catch, e.g. "e2vc") are masked here too — otherwise a
    deny-listed term masked in the content would still leak through the download's filename.
    """
    stem = Path(name).stem.strip() or "document"
    content = ExtractedContent(kind=FileKind.pdf, blocks=[Block(block_id="fn", text=stem)])
    masked = PresidioEngine().anonymize(
        content, language, extra_deny_terms=deny_terms
    ).content.plain_text or stem
    masked = masked.replace("<", "").replace(">", "")   # <PERSON_1> -> PERSON_1 (no angle brackets)
    safe = _UNSAFE.sub("_", masked).strip("._-")
    return (safe or "document")[:_MAX_LEN]

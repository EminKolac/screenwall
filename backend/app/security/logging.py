"""PII-safe logging (SECURITY.md §2.4).

A logging filter redacts common TR/EN PII from the fully-formatted record (message + args +
exception text) so logs never contain emails, phones, national IDs, tax IDs, IBANs, plates, or
card numbers. Application code should log `document_id` and entity counts/types, never raw values.

Codex Phase-1 review: redact the *formatted* message (not just `msg`/`args`), expand the
recognizer set (VKN/SSN/plate/spaced-IBAN/passport), and make setup idempotent (HIGH/LOW).
"""
from __future__ import annotations

import logging
import re

# Order: specific patterns before broad ones (over-redaction is the safe direction).
_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("EMAIL", re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")),
    ("IBAN", re.compile(r"\bTR(?:[ ]?\d){24}\b", re.IGNORECASE)),     # incl. space-grouped
    ("SSN", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    ("TCKN", re.compile(r"\b[1-9]\d{10}\b")),                          # 11 digits
    ("VKN", re.compile(r"\b\d{10}\b")),                                # 10 digits
    ("PLATE", re.compile(r"\b\d{2}\s?[A-ZÇĞİÖŞÜ]{1,3}\s?\d{2,4}\b")),  # TR vehicle plate
    ("PASSPORT", re.compile(r"\b[A-Z]\d{8}\b")),                       # TR passport style
    ("CARD", re.compile(r"\b(?:\d[ -]?){13,19}\b")),
    ("PHONE", re.compile(r"(?<!\d)(?:\+?\d[\d ()-]{7,}\d)(?!\d)")),
]


def redact(text: str) -> str:
    for label, pattern in _PATTERNS:
        text = pattern.sub(f"<{label}_REDACTED>", text)
    return text


class PIIRedactionFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        # Redact the fully-formatted message, then neutralize args so nothing leaks downstream.
        try:
            formatted = record.getMessage()
        except Exception:  # noqa: BLE001
            formatted = str(record.msg)
        record.msg = redact(formatted)
        record.args = ()
        if record.exc_text:
            record.exc_text = redact(record.exc_text)
        return True


_FILTER = PIIRedactionFilter()


def configure_pii_safe_logging(level: int = logging.INFO) -> None:
    """Attach the redaction filter idempotently without clobbering host/test logging config."""
    root = logging.getLogger()
    root.setLevel(level)
    if not root.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        root.addHandler(handler)
    for h in root.handlers:
        if not any(isinstance(f, PIIRedactionFilter) for f in h.filters):
            h.addFilter(_FILTER)

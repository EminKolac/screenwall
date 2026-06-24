"""Turkish-specific Presidio recognizers (regex + checksum, context-boosted).

TCKN uses the official checksum (high precision). VKN/landline/plate/passport use low base
scores raised by context words, so bare numbers are not over-flagged below the score threshold.
"""
from __future__ import annotations

from presidio_analyzer import Pattern, PatternRecognizer


def valid_tckn(text: str) -> bool:
    """Validate a Turkish national ID (TCKN) by its checksum digits."""
    s = "".join(ch for ch in text if ch.isdigit())
    if len(s) != 11 or s[0] == "0":
        return False
    d = [int(c) for c in s]
    if sum(d[:10]) % 10 != d[10]:
        return False
    odd = d[0] + d[2] + d[4] + d[6] + d[8]
    even = d[1] + d[3] + d[5] + d[7]
    return (odd * 7 - even) % 10 == d[9]


class _TcknRecognizer(PatternRecognizer):
    def __init__(self) -> None:
        super().__init__(
            supported_entity="TR_TCKN",
            supported_language="tr",
            patterns=[Pattern("tckn", r"\b[1-9][0-9]{10}\b", 0.3)],
            context=["tckn", "kimlik", "t.c.", "tc kimlik", "kimlik no"],
        )

    def validate_result(self, pattern_text: str):  # noqa: D102
        return valid_tckn(pattern_text)


def turkish_recognizers() -> list[PatternRecognizer]:
    return [
        _TcknRecognizer(),
        PatternRecognizer(
            supported_entity="TR_VKN", supported_language="tr",
            patterns=[Pattern("vkn", r"\b\d{10}\b", 0.2)],
            context=["vkn", "vergi", "vergi no", "vergi kimlik", "vergi dairesi"],
        ),
        PatternRecognizer(
            supported_entity="TR_GSM", supported_language="tr",
            patterns=[Pattern("gsm", r"\b(?:\+?90[ -]?|0)?5\d{2}[ -]?\d{3}[ -]?\d{2}[ -]?\d{2}\b", 0.5)],
            context=["gsm", "cep", "telefon", "tel"],
        ),
        PatternRecognizer(
            supported_entity="TR_PHONE", supported_language="tr",
            patterns=[Pattern("landline", r"\b(?:\+?90[ -]?|0)?(?:2|3|4)\d{2}[ -]?\d{3}[ -]?\d{2}[ -]?\d{2}\b", 0.3)],
            context=["tel", "telefon", "faks", "sabit"],
        ),
        PatternRecognizer(
            supported_entity="TR_IBAN", supported_language="tr",
            patterns=[Pattern("tr_iban", r"\bTR\d{2}[ ]?(?:\d{4}[ ]?){5}\d{2}\b", 0.7)],
            context=["iban", "hesap"],
        ),
        PatternRecognizer(
            supported_entity="TR_PLATE", supported_language="tr",
            patterns=[Pattern("plate", r"\b(?:0[1-9]|[1-7]\d|8[01])[ ]?[A-ZÇĞİÖŞÜ]{1,3}[ ]?\d{2,4}\b", 0.4)],
            context=["plaka", "araç", "arac"],
        ),
        PatternRecognizer(
            supported_entity="TR_PASSPORT", supported_language="tr",
            patterns=[Pattern("tr_passport", r"\b[A-Z]\d{8}\b", 0.3)],
            context=["pasaport", "passport"],
        ),
    ]

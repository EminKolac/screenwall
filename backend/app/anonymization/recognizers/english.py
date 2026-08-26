"""English-specific Presidio recognizers (complement Presidio's predefined EN set).

Presidio already ships US_SSN, US_DRIVER_LICENSE, EMAIL, PHONE, CREDIT_CARD, IBAN, IP, URL for
'en'. These add UK phone, a generic passport, and a context-gated SSN/DL backstop.
"""
from __future__ import annotations

from presidio_analyzer import Pattern, PatternRecognizer


def english_recognizers() -> list[PatternRecognizer]:
    return [
        PatternRecognizer(
            supported_entity="US_SSN", supported_language="en",
            patterns=[Pattern("ssn", r"\b\d{3}-\d{2}-\d{4}\b", 0.5)],
            context=["ssn", "social security"],
        ),
        PatternRecognizer(
            supported_entity="UK_PHONE", supported_language="en",
            # `(?<![\w+])` yerine `\b` KULLANILMAZ: `\b` boşluk ile "+" arasında eşleşmez (ikisi de
            # word-karakteri değil), bu yüzden "+44 7911 123456" span'i "+"ı DIŞARIDA bırakıyordu
            # ve maskeleme sonrası metinde yalnız "+" kalıyordu (kısmi span — PLAN.md §14.4'teki
            # "0532 <DATE> 123" sınıfının aynısı, ölçümle bulundu). Lookbehind hem "+"ı içeri alır
            # hem de sayının bir kelimenin/başka bir "+"ın ortasından başlamasını engeller.
            patterns=[Pattern("uk_phone", r"(?<![\w+])(?:\+?44[ -]?|0)(?:\d[ -]?){9,10}\b", 0.4)],
            context=["phone", "tel", "mobile", "telephone"],
        ),
        PatternRecognizer(
            supported_entity="PASSPORT", supported_language="en",
            patterns=[Pattern("passport", r"\b[A-Z]{1,2}\d{7,8}\b", 0.2)],
            context=["passport", "passport no"],
        ),
        PatternRecognizer(
            supported_entity="DRIVER_LICENSE", supported_language="en",
            patterns=[Pattern("dl", r"\b[A-Z]{1,2}\d{5,7}\b", 0.2)],
            context=["driver", "license", "licence", "dl no"],
        ),
    ]

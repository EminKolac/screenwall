"""Synthetic labelled corpus for the anonymization eval harness.

Each sample is text + the ground-truth PII spans we PLANTED, so the answer key is exact and free.
Design choices that make the numbers trustworthy:

- **Genuinely detectable values** — valid-checksum TCKN, TR-IBAN format, GSM numbers — so a
  miss reflects a real detector gap, not malformed input we fed it.
- **Context words present** ("TCKN:", "IBAN:", "cep:") — the low-base-score TR recognizers only
  fire above threshold when context boosts them (turkish.py), exactly as in real documents.
- **Distractor samples carry NO PII** (business terms, non-PII numbers) so over-masking shows up
  as a precision hit — where the old heuristic-auditor bug ("File Name" → PII) would surface.
- **Deterministic** (fixed seed) → identical corpus every run → CI-stable.

This is the *synthetic* tier (repo-safe, on-device). A real hand-labelled tier can be layered on
top later (local-only; real documents never enter the repo).
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field


@dataclass(frozen=True)
class GoldSpan:
    """A planted PII span, in ORIGINAL-text coordinates. `entity_type` is a canonical family
    (PERSON / TCKN / IBAN / EMAIL / PHONE / SSN) used for the per-type recall breakdown."""

    start: int
    end: int
    entity_type: str


@dataclass
class EvalSample:
    text: str
    spans: list[GoldSpan] = field(default_factory=list)
    lang: str = "mixed"  # tr / en / mixed — informational only


class _Builder:
    """Assembles a sample while tracking exact char offsets of each planted PII value."""

    def __init__(self) -> None:
        self._parts: list[str] = []
        self._spans: list[GoldSpan] = []
        self._n = 0

    def t(self, s: str) -> _Builder:
        self._parts.append(s)
        self._n += len(s)
        return self

    def pii(self, s: str, entity_type: str) -> _Builder:
        start = self._n
        self.t(s)
        self._spans.append(GoldSpan(start, self._n, entity_type))
        return self

    def done(self, lang: str) -> EvalSample:
        return EvalSample("".join(self._parts), self._spans, lang)


def complete_tckn(nine: str) -> str:
    """Append the two checksum digits so the result passes `turkish.valid_tckn`."""
    d = [int(c) for c in nine]
    d9 = ((d[0] + d[2] + d[4] + d[6] + d[8]) * 7 - (d[1] + d[3] + d[5] + d[7])) % 10
    d10 = (sum(d) + d9) % 10
    return nine + str(d9) + str(d10)


_TR_NAMES = ["Mehmet Yılmaz", "Ayşe Kaya", "Mustafa Demir", "Zeynep Şahin", "Ali Çelik",
             "Elif Aydın", "Hasan Doğan", "Fatma Arslan"]
_EN_NAMES = ["John Smith", "Emily Clark", "Michael Brown", "Sarah Johnson", "David Wilson"]
_EMAILS = ["ahmet.yilmaz@example.com", "info@sirket.com.tr", "j.smith@acme.co", "contact@fund.io"]
_GSM = ["0532 123 45 67", "+90 505 987 65 43", "0543 222 11 00"]
_TCKN9 = ["123456789", "234567890", "345678901", "456789012", "198765432", "111222333"]
_IBANS = ["TR33 0006 1005 1978 6457 8413 26", "TR12 0001 0002 0003 0004 0005 06"]
_SSN = ["123-45-6789", "078-05-1120"]

# Distractor sentences — deliberately NO PII. If detection masks anything here it is over-masking
# (a precision hit). Mix of EN + TR business language that NER is tempted to over-tag.
_DISTRACTORS = [
    "File Name and Tax Structure were reviewed during due diligence.",
    "The Fund reported strong performance in the third quarter.",
    "Total Revenue increased compared to the previous reporting period.",
    "Management fee and carried interest terms are summarized in the annex.",
    "Bu bölümde Vergi Yapısı ve Dosya Adı başlıkları ele alınmıştır.",
    "Portföy şirketinin gelirleri geçen döneme göre artış göstermiştir.",
]


def _tr_tckn(rng: random.Random) -> EvalSample:
    return (_Builder().t("Sayın ").pii(rng.choice(_TR_NAMES), "PERSON")
            .t(", TCKN: ").pii(complete_tckn(rng.choice(_TCKN9)), "TCKN")
            .t(" numaralı kaydınız oluşturulmuştur.").done("tr"))


def _tr_contact(rng: random.Random) -> EvalSample:
    return (_Builder().t("İletişim kişisi ").pii(rng.choice(_TR_NAMES), "PERSON")
            .t(", cep: ").pii(rng.choice(_GSM), "PHONE")
            .t(", e-posta: ").pii(rng.choice(_EMAILS), "EMAIL").t(".").done("tr"))


def _tr_iban(rng: random.Random) -> EvalSample:
    return (_Builder().t("Ödeme, IBAN: ").pii(rng.choice(_IBANS), "IBAN")
            .t(" hesabına yapılacaktır. Yetkili: ").pii(rng.choice(_TR_NAMES), "PERSON")
            .t(".").done("tr"))


def _en_contact(rng: random.Random) -> EvalSample:
    return (_Builder().t("Please contact ").pii(rng.choice(_EN_NAMES), "PERSON")
            .t(" at ").pii(rng.choice(_EMAILS), "EMAIL")
            .t(" for further details.").done("en"))


def _en_ssn(rng: random.Random) -> EvalSample:
    return (_Builder().t("The record with SSN: ").pii(rng.choice(_SSN), "SSN")
            .t(" belongs to ").pii(rng.choice(_EN_NAMES), "PERSON").t(".").done("en"))


def _mixed(rng: random.Random) -> EvalSample:
    return (_Builder().t("Meeting with ").pii(rng.choice(_TR_NAMES), "PERSON")
            .t(" confirmed. IBAN: ").pii(rng.choice(_IBANS), "IBAN")
            .t(", email ").pii(rng.choice(_EMAILS), "EMAIL").t(".").done("mixed"))


_TEMPLATES = [_tr_tckn, _tr_contact, _tr_iban, _en_contact, _en_ssn, _mixed]


def build_corpus(n_per_template: int = 6) -> list[EvalSample]:
    """Deterministic corpus: `n_per_template` samples from each template + the distractor set."""
    rng = random.Random(1234)
    samples: list[EvalSample] = []
    for template in _TEMPLATES:
        for _ in range(n_per_template):
            samples.append(template(rng))
    samples.extend(EvalSample(text=d, spans=[], lang="mixed") for d in _DISTRACTORS)
    return samples

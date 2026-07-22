"""Synthetic canary catalog for the BIST-30 benchmark.

Canaries are FAKE PII (no real person/company) planted into carrier documents at known positions,
giving exact ground truth: for each value we know its type, the placeholder family the platform
SHOULD assign, and whether the base Presidio stack can even detect it. The benchmark then measures
extracted → detected → masked → survived-in-export per canary.

SECURITY: reports and logs must print only `vhash` (sha256[:16]) + type — never the raw value.
The values here are synthetic test fixtures (e.g. Luhn-valid TEST card 4111-1111-1111-1111), safe
in-repo; the GENERATED carrier documents that embed them live only in the gitignored data dir.

`base_detectable` is a PREDICTION (which the benchmark then confirms or refutes): base Presidio has
no ACCOUNT or SECRET recognizer and weak free-text address detection, so those are expected critical
false-negatives in the offline configuration (they need the optional Privacy Filter stage).
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass

from evaluation.corpus import complete_tckn


def value_hash(value: str) -> str:
    """Stable non-reversible id for a canary value — safe to print in reports."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class Canary:
    cid: str               # stable short id
    label: str             # human description (no raw value)
    value: str             # SYNTHETIC PII — never emitted raw in reports/logs
    expected_family: str   # placeholder family to assign (a _TYPE_TO_PLACEHOLDER value)
    lang: str              # tr / en
    context: str           # context word placed adjacent (low-score TR recognizers need it)
    critical: bool         # a miss here is a critical false-negative (real privacy breach)
    base_detectable: bool  # PREDICTION: can base Presidio (no Privacy Filter) detect it at all?
    note: str = ""

    @property
    def vhash(self) -> str:
        return value_hash(self.value)


# Checksum-valid synthetic TCKNs (pass turkish.valid_tckn) + a Luhn-valid TEST card number.
_TCKN_A = complete_tckn("102030405")


def canary_catalog() -> list[Canary]:
    """The fixed set of canaries. Deterministic → identical ground truth every run."""
    return [
        # names — EN NER strong, TR NER weak (expect partial recall)
        Canary("prs_tr", "Person name (TR)", "Kemal Vardar", "PERSON", "tr", "Sayın", True, True),
        Canary("prs_en", "Name (EN)", "Jonathan Whitfield", "PERSON", "en", "Mr.", True, True),
        # phone
        Canary("gsm_tr", "Mobile (TR GSM)", "0532 764 21 09", "PHONE", "tr", "cep", True, True),
        Canary("lnd_tr", "Landline (TR)", "0212 555 34 76", "PHONE", "tr", "tel", True, True),
        Canary("phn_uk", "Phone (UK)", "+44 7911 123456", "PHONE", "en", "phone", True, True),
        # email
        Canary("eml", "Personal email", "kemal.vardar@ornekposta.com", "EMAIL", "tr", "e-posta",
               True, True),
        # address — weak base detection (expect FN)
        Canary("adr", "Address (TR)", "Bağdat Caddesi No 145 Kadıköy İstanbul", "LOCATION", "tr",
               "adres", True, False, "base free-text address detection is weak"),
        # IBAN
        Canary("iban", "IBAN (TR)", "TR84 0009 1000 8765 4321 0987 65", "IBAN", "tr", "IBAN",
               True, True),
        # credit card — Luhn-valid TEST number
        Canary("card", "Credit card (TEST)", "4111 1111 1111 1111", "CARD", "en", "kart",
               True, True),
        # national id
        Canary("tckn", "National ID (TCKN)", _TCKN_A, "TCKN", "tr", "TCKN", True, True),
        # account / customer number — NO base recognizer (needs Privacy Filter)
        Canary("acct", "Account/customer no", "8842-556310-04", "ACCOUNT", "tr", "Müşteri No",
               True, False, "base Presidio has no ACCOUNT recognizer"),
        # IP address (lower severity)
        Canary("ip", "IP address", "192.168.14.203", "IP", "en", "IP", False, True),
        # secret / API key — NO base recognizer (needs Privacy Filter)
        Canary("secret", "API key / secret", "sk_live_9Qm2fXbT7hVrN4KpLZ", "SECRET", "en",
               "secret", True, False, "base Presidio has no SECRET recognizer"),
        # URL with embedded token
        Canary("url_tok", "URL with token", "https://portal.ornek.com/r?token=aZ39Kp7Qw12M", "URL",
               "en", "link", True, True),
        # vehicle plate (medium severity)
        Canary("plate", "Vehicle plate (TR)", "34 KVR 218", "PLATE", "tr", "plaka", False, True),
        # passport
        Canary("passport", "Passport", "U12345678", "PASSPORT", "en", "passport", True, True),
    ]


def catalog_by_id() -> dict[str, Canary]:
    return {c.cid: c for c in canary_catalog()}

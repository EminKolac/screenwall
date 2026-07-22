"""OpenAI Privacy Filter — optional LOCAL, on-device PII detector (detection stage ② of 3).

An open-weight (Apache-2.0) Hugging Face token-classification model that runs entirely on-device via
`transformers` — no external call, so it preserves the platform's local-first invariant. It adds a
context-aware detection pass alongside Presidio (stage ①); its spans are merged into the same
`resolve_spans` machinery inside `presidio_engine._anon_text`, then the shared audit is stage ③.

Enabled via `use_privacy_filter` (default OFF); needs the `[privacy]` extra (transformers+torch).
Loading is ALWAYS `local_files_only=True` — zero network at runtime (local-first). Pre-download the
model once via `scripts/setup_macos.sh` (PRIVACY_FILTER=1) or `huggingface-cli download <model>`.
If enabled but unavailable: `require_privacy_filter` makes it fail closed (→ human review);
otherwise it logs a warning and falls back to Presidio-only.

The default model (`OpenMed/privacy-filter-multilingual`, a TR-capable fine-tune of
`openai/privacy-filter`) emits the 54-label ai4privacy taxonomy; the original base model emits 8
`private_*` labels. `_LABEL_MAP` folds BOTH into the platform's entity types so a value caught by
Presidio and by Privacy Filter lands in the SAME placeholder family (deterministic `<TYPE_n>`:
same value = same token everywhere). Unknown labels fall back to SENSITIVE — fail-safe: still
masked, never a novel placeholder family. Noisy, non-identifying labels (dates, amounts,
currencies, job titles) are excluded by default via `privacy_filter_exclude_labels`.
"""
from __future__ import annotations

import logging
import threading
from functools import lru_cache

from app.anonymization.engine import EntitySpan
from app.config import get_settings

logger = logging.getLogger(__name__)

# Privacy Filter label → platform entity_type (then `_ph_type` maps it to a placeholder family).
# Covers the 54-label ai4privacy taxonomy (verified against the OpenMed model's id2label) AND the
# original openai/privacy-filter 8-label taxonomy. Keys are the model's labels, uppercased.
_LABEL_MAP = {
    # people
    "FIRSTNAME": "PERSON", "MIDDLENAME": "PERSON", "LASTNAME": "PERSON", "PREFIX": "PERSON",
    "USERNAME": "USERNAME",
    # contact
    "EMAIL": "EMAIL_ADDRESS", "PHONE": "PHONE_NUMBER", "URL": "URL",
    # address / location
    "STREET": "LOCATION", "BUILDINGNUMBER": "LOCATION", "SECONDARYADDRESS": "LOCATION",
    "CITY": "LOCATION", "COUNTY": "LOCATION", "STATE": "LOCATION", "ZIPCODE": "LOCATION",
    "GPSCOORDINATES": "LOCATION", "ORDINALDIRECTION": "LOCATION",
    # organizations ("Visa" the card issuer is an org name, not a card number)
    "ORGANIZATION": "ORGANIZATION", "CREDITCARDISSUER": "ORGANIZATION",
    # dates
    "DATE": "DATE_TIME", "TIME": "DATE_TIME", "DATEOFBIRTH": "DATE_TIME",
    # government / personal IDs
    "SSN": "US_SSN",
    # financial
    "CREDITCARD": "CREDIT_CARD", "IBAN": "IBAN_CODE",
    "BANKACCOUNT": "ACCOUNT", "ACCOUNTNAME": "ACCOUNT", "BIC": "ACCOUNT",
    "MASKEDNUMBER": "ACCOUNT",
    "BITCOINADDRESS": "ACCOUNT", "ETHEREUMADDRESS": "ACCOUNT", "LITECOINADDRESS": "ACCOUNT",
    # secrets / credentials
    "PASSWORD": "SECRET", "PIN": "SECRET", "CVV": "SECRET",
    # network / device / vehicle
    "IPADDRESS": "IP_ADDRESS", "VRM": "PLATE",
    "MACADDRESS": "SENSITIVE", "IMEI": "SENSITIVE", "USERAGENT": "SENSITIVE",
    "VIN": "SENSITIVE",
    # quasi-identifying attributes (rare in business docs; masking them is low-cost)
    "AGE": "SENSITIVE", "GENDER": "SENSITIVE", "SEX": "SENSITIVE",
    "EYECOLOR": "SENSITIVE", "HEIGHT": "SENSITIVE",
    "JOBTITLE": "SENSITIVE", "JOBDEPARTMENT": "SENSITIVE", "OCCUPATION": "SENSITIVE",
    "AMOUNT": "SENSITIVE", "CURRENCY": "SENSITIVE", "CURRENCYCODE": "SENSITIVE",
    "CURRENCYNAME": "SENSITIVE", "CURRENCYSYMBOL": "SENSITIVE",
    # original openai/privacy-filter 8-label taxonomy (base-model support)
    "PRIVATE_PERSON": "PERSON", "PRIVATE_EMAIL": "EMAIL_ADDRESS",
    "PRIVATE_PHONE": "PHONE_NUMBER", "PRIVATE_ADDRESS": "LOCATION",
    "PRIVATE_URL": "URL", "PRIVATE_DATE": "DATE_TIME",
    "ACCOUNT_NUMBER": "ACCOUNT", "SECRET": "SECRET",
}

# The HF pipeline is not guaranteed thread-safe; serialize inference (like the analyzer).
_PF_LOCK = threading.Lock()


def _norm_label(raw: str) -> str:
    """Uppercase and strip a BIOES prefix (defensive: aggregation normally strips it already)."""
    label = raw.upper()
    if len(label) > 2 and label[1] == "-" and label[0] in "BIES":
        return label[2:]
    return label


class PrivacyFilter:
    """HF token-classification pipeline → `EntitySpan`s (source='privacy_filter')."""

    def __init__(self, pipe, threshold: float, exclude_labels: frozenset[str]) -> None:
        self._pipe = pipe
        self._threshold = threshold
        self._exclude = exclude_labels

    def detect(self, text: str) -> list[EntitySpan]:
        if not text or not text.strip():
            return []
        with _PF_LOCK:
            results = self._pipe(text)
        spans: list[EntitySpan] = []
        for r in results:
            score = float(r.get("score", 0.0))
            if score < self._threshold:
                continue
            label = _norm_label(str(r.get("entity_group") or r.get("entity") or ""))
            if not label or label == "O" or label in self._exclude:
                continue
            start, end = r.get("start"), r.get("end")
            if start is None or end is None or int(end) <= int(start):
                continue
            # Fail-safe fallback: an unknown label is still masked, in the generic SENSITIVE
            # family — never a novel placeholder family leaking the model's raw taxonomy.
            entity_type = _LABEL_MAP.get(label, "SENSITIVE")
            spans.append(EntitySpan(start=int(start), end=int(end), entity_type=entity_type,
                                    score=score, source="privacy_filter"))
        return spans


def _load_pipeline(model: str):
    # Lazy import: only when enabled + [privacy] installed. `local_files_only=True` on BOTH the
    # tokenizer and the model guarantees zero network at runtime (local-first invariant); a
    # missing cache raises OSError → get_privacy_filter degrades or fails closed.
    from transformers import AutoModelForTokenClassification, AutoTokenizer, pipeline

    tok = AutoTokenizer.from_pretrained(model, local_files_only=True)
    mdl = AutoModelForTokenClassification.from_pretrained(model, local_files_only=True)
    return pipeline(task="token-classification", model=mdl, tokenizer=tok,
                    aggregation_strategy="simple")


@lru_cache
def get_privacy_filter() -> PrivacyFilter | None:
    """Cached PrivacyFilter if enabled AND loadable, else None (Presidio-only fallback).

    Raises only when `require_privacy_filter` is set and the model cannot load — the caller then
    fails closed to human review (the raise is not cached, so it re-evaluates each call).
    """
    s = get_settings()
    if not s.use_privacy_filter:
        return None
    try:
        pipe = _load_pipeline(s.privacy_filter_model)
        logger.info("OpenAI Privacy Filter ready (model=%s)", s.privacy_filter_model)
        return PrivacyFilter(pipe, s.privacy_filter_threshold, s.privacy_filter_excluded())
    except Exception as e:  # noqa: BLE001 — transformers/torch missing, or model not pre-downloaded
        if s.require_privacy_filter:
            raise RuntimeError(
                f"Privacy Filter required but unavailable ({type(e).__name__}); install the "
                "[privacy] extra and pre-download the model (scripts/setup_macos.sh with "
                "PRIVACY_FILTER=1), or unset REQUIRE_PRIVACY_FILTER."
            ) from e
        logger.warning("Privacy Filter enabled but unavailable (%s) — Presidio-only.",
                       type(e).__name__)
        return None

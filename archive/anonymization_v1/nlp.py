"""Presidio NLP engine + analyzer construction (cached).

EN → spaCy en_core_web_sm; TR/other → spaCy multilingual xx_ent_wiki_sm (PER/LOC/ORG without
torch). The NER label map normalizes both English (PERSON/GPE/ORG) and multilingual (PER/LOC/ORG)
labels to Presidio entities. Custom TR/EN recognizers are registered on top. An optional
transformers Turkish NER (savasy/bert-base-turkish-ner-cased) can be enabled via the [tr] extra.
"""
from __future__ import annotations

import logging
from functools import lru_cache

from presidio_analyzer import AnalyzerEngine
from presidio_analyzer.nlp_engine import NlpEngineProvider

from app.anonymization.context_enhancer import SurfaceFormContextAwareEnhancer
from app.anonymization.recognizers.english import english_recognizers
from app.anonymization.recognizers.turkish import turkish_recognizers
from app.config import get_settings

logger = logging.getLogger(__name__)

_NER_MAPPING = {
    "PER": "PERSON", "PERSON": "PERSON",
    "LOC": "LOCATION", "GPE": "LOCATION", "FAC": "LOCATION",
    "ORG": "ORGANIZATION",
    "MISC": "NRP", "NORP": "NRP",
    "DATE": "DATE_TIME", "TIME": "DATE_TIME",
}


@lru_cache
def get_analyzer() -> AnalyzerEngine:
    s = get_settings()
    configuration = {
        "nlp_engine_name": "spacy",
        "models": [
            {"lang_code": "en", "model_name": s.spacy_en_model},
            {"lang_code": "tr", "model_name": s.spacy_multilingual_model},
        ],
        "ner_model_configuration": {
            "model_to_presidio_entity_mapping": _NER_MAPPING,
            "low_confidence_score_multiplier": 0.4,
            # GoldBench measured over-masking at 100% (24/24 ordinary business terms masked) —
            # "Genel Kurul", "Fatura Dönemi" etc. all wrongly flagged. Root cause: spaCy has no
            # real confidence signal, so every NER hit is hard-coded to 0.85 (presidio's
            # NerModelConfiguration.default_score) regardless of label, and this multiplier was
            # neutered by an empty low_score_entity_names — nothing was ever discounted.
            #
            # IMPORTANT CAVEAT (checked, not assumed): presidio's built-in SpacyRecognizer sets
            # `context = []`, so listing a type here does NOT make it "recoverable via context" —
            # 0.85 * 0.4 = 0.34 is permanently below the 0.4 threshold for that type, full stop.
            # This is therefore closer to a kill switch than a dial. ORGANIZATION and NRP go here
            # because they are not a defined identifier class in our own schema and are the two
            # largest over-masking families (BIST run: ORG 41k, NRP 36k occurrences) — losing them
            # has no DIRECT-identifier cost. LOCATION and PERSON are deliberately NOT here:
            # there is no dedicated Turkish address recognizer (grepped — none exists), so address
            # masking depends entirely on generic LOCATION NER; PERSON is the highest-criticality
            # type. Zeroing LOCATION would silently crash address recall. Verify with GoldBench
            # (critical entity recall >= 0.95, esp. the 'adr'/ADDRESS type) before ever adding
            # LOCATION here — see docs/CALIBRATION.md.
            "low_score_entity_names": ["ORGANIZATION", "NRP"],
            # DATE_TIME is the single largest over-masking family AND the mechanism behind a
            # partial-PII leak: a generic "date-shaped" span (e.g. "45 67" inside a phone number)
            # can outscore/fragment a real pattern match (TR_GSM base score 0.5) in resolve_spans,
            # leaving the middle of the number unmasked. Turkish/English financial documents are
            # full of numeric noise that looks date-like, so we drop DATE_TIME entirely rather
            # than rescore it — it is rarely PII on its own, and see engine.py::resolve_spans for
            # the complementary fix (pattern recognizers now also outrank statistical NER on
            # overlap).
            "labels_to_ignore": ["DATE_TIME"],
        },
    }
    nlp_engine = NlpEngineProvider(nlp_configuration=configuration).create_engine()
    # xx_ent_wiki_sm (tr) has no lemmatizer, so Presidio's default lemma-based context boost never
    # fires for Turkish — every low-base-score TR recognizer (VKN, TR_PHONE, TR_ACCOUNT, generic
    # SECRET_KEY) was permanently stuck below the 0.4 threshold. See context_enhancer.py for the
    # measured root cause. en_core_web_sm has a real lemmatizer, so English is unaffected.
    analyzer = AnalyzerEngine(nlp_engine=nlp_engine, supported_languages=["en", "tr"],
                              context_aware_enhancer=SurfaceFormContextAwareEnhancer())
    for rec in turkish_recognizers() + english_recognizers():
        analyzer.registry.add_recognizer(rec)
    logger.info("Presidio analyzer ready (en=%s, tr=%s)",
                s.spacy_en_model, s.spacy_multilingual_model)
    return analyzer

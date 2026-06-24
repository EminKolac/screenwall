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
            "low_score_entity_names": [],
        },
    }
    nlp_engine = NlpEngineProvider(nlp_configuration=configuration).create_engine()
    analyzer = AnalyzerEngine(nlp_engine=nlp_engine, supported_languages=["en", "tr"])
    for rec in turkish_recognizers() + english_recognizers():
        analyzer.registry.add_recognizer(rec)
    logger.info("Presidio analyzer ready (en=%s, tr=%s)", s.spacy_en_model, s.spacy_multilingual_model)
    return analyzer

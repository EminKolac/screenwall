"""Presidio analyzer construction (cached) — Presidio stays the recognizer framework.

EN → spaCy en_core_web_sm; TR/other → spaCy multilingual xx_ent_wiki_sm. The NER label map folds
English (PERSON/GPE/ORG) and multilingual (PER/LOC/ORG) labels into Presidio entities; the custom
Turkish and English pattern recognizers are registered on top.

Two settings shape NER, both unchanged from before Faz 1 (the parity snapshots pin them):
- ORGANIZATION and NRP get the low-confidence multiplier (0.85 × 0.4 = 0.34 < threshold 0.4);
  Presidio's SpacyRecognizer has no context words, so this switches them off entirely. They were
  the two largest over-masking families on real reports and are not identifiers in our schema.
- DATE_TIME is ignored: date-shaped fragments inside phone numbers used to outrank real patterns.

The registry is Presidio's predefined set minus `_UNUSED` (recognizers that never fired on the dev
set, the stress corpus or 30 real BIST documents; thoughts/EXPERIMENTS.md, Faz 1 inventory), with
the e-mail recognizer swapped for an offline one. US/UK recognizers that DID fire stay until a
Faz 2 measurement decides.
"""
from __future__ import annotations

import logging
from functools import lru_cache

import tldextract
from presidio_analyzer import AnalyzerEngine
from presidio_analyzer.context_aware_enhancers import LemmaContextAwareEnhancer
from presidio_analyzer.nlp_engine import NlpArtifacts, NlpEngineProvider
from presidio_analyzer.predefined_recognizers import EmailRecognizer

from app.anonymization.recognizers.english import english_recognizers
from app.anonymization.recognizers.turkish import turkish_recognizers
from app.config import get_settings

logger = logging.getLogger(__name__)

_UNUSED = frozenset({"CryptoRecognizer", "MacAddressRecognizer", "MedicalLicenseRecognizer",
                     "NhsRecognizer", "UsItinRecognizer", "UsLicenseRecognizer"})

# tldextract's bundled public-suffix snapshot only: the default extractor downloads the list from
# publicsuffix.org on first use, a network call from a tool that promises nothing leaves the
# machine.
_OFFLINE_TLDS = tldextract.TLDExtract(suffix_list_urls=(), cache_dir=None)


class OfflineEmailRecognizer(EmailRecognizer):
    """Presidio's e-mail recognizer (same pattern, score and context) with an offline TLD check."""

    def validate_result(self, pattern_text: str) -> bool:
        return _OFFLINE_TLDS(pattern_text).fqdn != ""

_NER_MAPPING = {
    "PER": "PERSON", "PERSON": "PERSON",
    "LOC": "LOCATION", "GPE": "LOCATION", "FAC": "LOCATION",
    "ORG": "ORGANIZATION",
    "MISC": "NRP", "NORP": "NRP",
    "DATE": "DATE_TIME", "TIME": "DATE_TIME",
}


class SurfaceFormContextAwareEnhancer(LemmaContextAwareEnhancer):
    """Context words matched on surface forms because `xx_ent_wiki_sm` has no lemmatizer.

    Measured root cause: Presidio's default enhancer looks context words up in
    `nlp_artifacts.lemmas`, which are all empty strings for the Turkish model, so a context word
    right next to a value never boosted it and every low-base-score Turkish recognizer (VKN 0.2,
    TR_PHONE 0.3, TR_ACCOUNT 0.25, generic SECRET_KEY 0.15) stayed below the 0.4 threshold.
    Known limit: no stemming, so "hesap" does not match "hesabınız".
    """

    def _extract_surrounding_words(
        self, nlp_artifacts: NlpArtifacts, word: str, start: int,
    ) -> list[str]:
        if not nlp_artifacts.tokens:
            return [""]
        tokens = list(nlp_artifacts.tokens)
        token_index = self._find_index_of_match_token(
            word, start, nlp_artifacts.tokens, nlp_artifacts.tokens_indices)
        lo = max(0, token_index - self.context_prefix_count)
        hi = min(len(tokens), token_index + self.context_suffix_count + 1)
        return [tokens[i].text.lower() for i in range(lo, hi) if i != token_index] or [""]


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
            "low_score_entity_names": ["ORGANIZATION", "NRP"],
            "labels_to_ignore": ["DATE_TIME"],
        },
    }
    nlp_engine = NlpEngineProvider(nlp_configuration=configuration).create_engine()
    analyzer = AnalyzerEngine(nlp_engine=nlp_engine, supported_languages=["en", "tr"],
                              context_aware_enhancer=SurfaceFormContextAwareEnhancer())
    registry = analyzer.registry
    registry.recognizers = [r for r in registry.recognizers
                            if r.name not in _UNUSED and not isinstance(r, EmailRecognizer)]
    for lang in ("en", "tr"):
        registry.add_recognizer(OfflineEmailRecognizer(supported_language=lang))
    for rec in turkish_recognizers() + english_recognizers():
        registry.add_recognizer(rec)
    logger.info("Presidio analyzer ready (en=%s, tr=%s)",
                s.spacy_en_model, s.spacy_multilingual_model)
    return analyzer

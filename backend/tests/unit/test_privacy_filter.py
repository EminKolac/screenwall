"""Unit tests for the OpenAI Privacy Filter detector (stage ②).

All tests use a stub pipeline callable — no transformers/torch required. Covered: label folding
(54-label ai4privacy taxonomy AND original 8-label taxonomy → platform entity types), the
default exclude-list, score threshold, fail-safe SENSITIVE fallback for unknown labels, invalid
span hygiene, the enabled/required load paths (degrade vs fail-closed), and end-to-end masking
through PresidioEngine with the same <TYPE_n> families Presidio uses.
"""
from __future__ import annotations

import pytest

import app.anonymization.privacy_filter as pf_mod
from app.anonymization.presidio_engine import PresidioEngine
from app.anonymization.privacy_filter import PrivacyFilter, get_privacy_filter
from app.config import Settings
from app.extraction.base import Block, ExtractedContent
from app.models.document import FileKind, Language

_EXCLUDE = Settings().privacy_filter_excluded()


def _pf(results, threshold: float = 0.5, exclude=_EXCLUDE) -> PrivacyFilter:
    return PrivacyFilter(lambda text: results, threshold, exclude)


def _r(label: str, start: int, end: int, score: float = 0.99) -> dict:
    return {"entity_group": label, "score": score, "start": start, "end": end}


@pytest.fixture
def pf_cache():
    """get_privacy_filter is lru_cached process-wide; isolate it per test."""
    get_privacy_filter.cache_clear()
    yield
    get_privacy_filter.cache_clear()


# --- label folding -------------------------------------------------------------------------

def test_multilingual_labels_fold_into_platform_types():
    spans = _pf([_r("FIRSTNAME", 0, 5), _r("EMAIL", 6, 22), _r("IBAN", 23, 49),
                 _r("PASSWORD", 50, 58), _r("SSN", 59, 70)]).detect("x" * 80)
    assert [s.entity_type for s in spans] == [
        "PERSON", "EMAIL_ADDRESS", "IBAN_CODE", "SECRET", "US_SSN"]
    assert all(s.source == "privacy_filter" for s in spans)


def test_original_openai_taxonomy_still_supported():
    spans = _pf([_r("private_person", 0, 5), _r("secret", 6, 12),
                 _r("account_number", 13, 20)]).detect("x" * 30)
    assert [s.entity_type for s in spans] == ["PERSON", "SECRET", "ACCOUNT"]


def test_bioes_prefix_stripped_defensively():
    spans = _pf([_r("B-FIRSTNAME", 0, 5), _r("S-EMAIL", 6, 22)]).detect("x" * 30)
    assert [s.entity_type for s in spans] == ["PERSON", "EMAIL_ADDRESS"]


def test_unknown_label_falls_back_to_sensitive_not_a_novel_family():
    spans = _pf([_r("ZODIACSIGN", 0, 5)]).detect("x" * 10)
    assert [s.entity_type for s in spans] == ["SENSITIVE"]  # still masked, fail-safe


# --- filtering -----------------------------------------------------------------------------

def test_default_excluded_labels_are_dropped():
    spans = _pf([_r("DATE", 0, 10), _r("JOBTITLE", 11, 14), _r("AMOUNT", 15, 20),
                 _r("FIRSTNAME", 21, 26)]).detect("x" * 30)
    assert [s.entity_type for s in spans] == ["PERSON"]  # only the non-excluded one survives


def test_below_threshold_dropped():
    spans = _pf([_r("FIRSTNAME", 0, 5, score=0.3)], threshold=0.5).detect("x" * 10)
    assert spans == []


def test_invalid_and_noise_results_dropped():
    spans = _pf([
        {"entity_group": "FIRSTNAME", "score": 0.9},                # no offsets
        _r("FIRSTNAME", 5, 5),                                      # empty span
        _r("FIRSTNAME", 7, 3),                                      # inverted span
        _r("O", 0, 4),                                              # outside tag
        {"entity_group": "", "score": 0.9, "start": 0, "end": 4},   # empty label
    ]).detect("x" * 10)
    assert spans == []


def test_empty_text_never_calls_the_model():
    def _explode(_text):
        raise AssertionError("pipeline must not run on empty text")
    assert PrivacyFilter(_explode, 0.5, _EXCLUDE).detect("   ") == []


def test_config_exclude_helper_normalizes():
    s = Settings(privacy_filter_exclude_labels=" date , Time ,jobtitle ")
    assert s.privacy_filter_excluded() == frozenset({"DATE", "TIME", "JOBTITLE"})


# --- load paths (enable/require) -----------------------------------------------------------

def test_disabled_by_default_returns_none(pf_cache):
    assert get_privacy_filter() is None


def test_enabled_but_unavailable_degrades_to_none(pf_cache, monkeypatch):
    monkeypatch.setenv("USE_PRIVACY_FILTER", "true")
    from app.config import get_settings
    get_settings.cache_clear()
    monkeypatch.setattr(pf_mod, "_load_pipeline",
                        lambda model: (_ for _ in ()).throw(OSError("not cached")))
    assert get_privacy_filter() is None  # require_privacy_filter=False → Presidio-only


def test_enabled_and_required_fails_closed(pf_cache, monkeypatch):
    monkeypatch.setenv("USE_PRIVACY_FILTER", "true")
    monkeypatch.setenv("REQUIRE_PRIVACY_FILTER", "true")
    from app.config import get_settings
    get_settings.cache_clear()
    monkeypatch.setattr(pf_mod, "_load_pipeline",
                        lambda model: (_ for _ in ()).throw(OSError("not cached")))
    with pytest.raises(RuntimeError):
        get_privacy_filter()


# --- end-to-end through the engine ---------------------------------------------------------

def test_firstname_span_masks_into_person_family(monkeypatch):
    """A value only the Privacy Filter catches must land in the SAME <PERSON_n> family Presidio
    uses — the deterministic same-value=same-token invariant across detectors."""
    import app.anonymization.presidio_engine as pe

    name = "Rumpelstiltskin"

    def _pipe(text):
        i = text.find(name)
        return [] if i == -1 else [_r("FIRSTNAME", i, i + len(name))]

    monkeypatch.setattr(pe, "get_privacy_filter",
                        lambda: PrivacyFilter(_pipe, 0.5, _EXCLUDE))
    content = ExtractedContent(kind=FileKind.docx,
                               blocks=[Block(block_id="0", text=f"Please ask {name} today.")])
    out = PresidioEngine().anonymize(content, Language.en)
    text = out.content.plain_text
    assert name not in text
    assert "<PERSON_" in text and "<FIRSTNAME_" not in text
    assert out.by_source.get("privacy_filter", 0) >= 1

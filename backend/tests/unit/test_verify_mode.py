"""Unit tests for evaluation.corpus_bist10.verify_mode — the M1-M3 / D1-D3 assertion logic.

Fast, no NLP models: repos are faked so these test the CHECKING logic itself, independent of
whether the pipeline correctly persists/omits layers (that's covered by
tests/integration/test_anonymization_modes.py, which exercises the real pipeline end to end).
"""
from __future__ import annotations

from app.extraction.base import Block, ExtractedContent
from app.models.document import FileKind
from evaluation.corpus_bist10.verify_mode import (
    check_destructive_mode,
    check_mapping_mode,
    full_tree_pii_sweep,
)


class _FakeRepo:
    def __init__(self, *, mapping=None, anonymized=None, original=None, extracted=None):
        self._mapping = mapping
        self._anon = anonymized
        self._original = original
        self._extracted = extracted

    def get_mapping(self, doc_id):
        return self._mapping

    def get_anonymized(self, doc_id):
        return self._anon

    def get_original(self, doc_id):
        return self._original

    def get_extracted(self, doc_id):
        return self._extracted


def _content(text: str) -> ExtractedContent:
    return ExtractedContent(kind=FileKind.docx, blocks=[Block(block_id="0", text=text)])


# ---------- Benchmark M ----------

def test_mapping_mode_all_checks_pass_when_complete_and_contained():
    repo = _FakeRepo(
        mapping={"<PERSON_1>": "Ahmet Yılmaz", "<EMAIL_1>": "ahmet@example.com"},
        anonymized=_content("<PERSON_1>, <EMAIL_1>"),
    )
    r = check_mapping_mode(
        "d1", repo, canary_values=["Ahmet Yılmaz", "ahmet@example.com"],
        shareable_blobs={"api_detail": '{"id": "d1", "status": "approved"}'},
    )
    assert r.passed
    assert r.checks["M1_mapping_complete"]
    assert r.checks["M2_roundtrip_complete"]
    assert r.checks["M3_mapping_contained"]


def test_m1_fails_on_unresolved_token():
    repo = _FakeRepo(mapping={}, anonymized=_content("<PERSON_1> signed."))
    r = check_mapping_mode("d2", repo, canary_values=[], shareable_blobs={"x": ""})
    assert not r.checks["M1_mapping_complete"]
    assert r.details["M1_unresolved_tokens"] == 1


def test_m2_fails_when_masked_value_not_recoverable():
    # Text is masked, but the map's entry doesn't actually hold the canary value -> no round-trip.
    repo = _FakeRepo(mapping={"<PERSON_1>": "Someone Else"}, anonymized=_content("<PERSON_1>"))
    r = check_mapping_mode("d3", repo, canary_values=["Ahmet Yılmaz"], shareable_blobs={"x": ""})
    assert not r.checks["M2_roundtrip_complete"]
    assert r.details["M2_masked_count"] == 1
    assert r.details["M2_recoverable_count"] == 0


def test_m2_ignores_a_canary_that_was_never_masked():
    # If the value still appears in plain text, it was never masked at all — that's a detection
    # miss (measured elsewhere), not a round-trip failure, so M2 must not penalize it.
    repo = _FakeRepo(mapping={}, anonymized=_content("Ahmet Yılmaz remains in the clear."))
    r = check_mapping_mode("d3b", repo, canary_values=["Ahmet Yılmaz"], shareable_blobs={"x": ""})
    assert r.checks["M2_roundtrip_complete"]
    assert r.details["M2_masked_count"] == 0


def test_m3_fails_when_mapping_leaks_into_a_shareable_blob():
    repo = _FakeRepo(mapping={"<PERSON_1>": "Ahmet Yılmaz"}, anonymized=_content("<PERSON_1>"))
    r = check_mapping_mode(
        "d4", repo, canary_values=["Ahmet Yılmaz"],
        shareable_blobs={"api_detail": "..no leak..", "logs": "raw: Ahmet Yılmaz"},
    )
    assert not r.checks["M3_mapping_contained"]
    assert r.details["M3_leaked_in"] == ["logs"]


def test_m3_fails_closed_when_no_blobs_provided():
    """No blobs checked = containment not verified — must not silently report 'passed'."""
    repo = _FakeRepo(mapping={"<PERSON_1>": "Ahmet Yılmaz"}, anonymized=_content("<PERSON_1>"))
    r = check_mapping_mode("d4b", repo, canary_values=["Ahmet Yılmaz"], shareable_blobs={})
    assert not r.checks["M3_mapping_contained"]


# ---------- Benchmark D ----------

def test_destructive_mode_d2_d3_pass_when_layers_absent():
    repo = _FakeRepo(mapping=None, original=None, extracted=None)
    r = check_destructive_mode("d5", repo)
    assert r.passed
    assert r.checks["D2_no_original"]
    assert r.checks["D2_no_extracted"]
    assert r.checks["D2_no_mapping_file"]
    assert r.checks["D3_reversal_fails"]


def test_destructive_mode_d2_fails_if_original_persisted():
    repo = _FakeRepo(mapping=None, original=b"raw bytes", extracted=None)
    r = check_destructive_mode("d6", repo)
    assert not r.passed
    assert not r.checks["D2_no_original"]


def test_destructive_mode_d3_fails_if_mapping_recoverable():
    repo = _FakeRepo(mapping={"<PERSON_1>": "Ahmet Yılmaz"}, original=None, extracted=None)
    r = check_destructive_mode("d7", repo)
    assert not r.checks["D3_reversal_fails"]


# ---------- D1 — full-tree sweep ----------

def test_full_tree_sweep_zero_hits_on_clean_tree(tmp_path):
    d = tmp_path / "3_anonymized" / "d8"
    d.mkdir(parents=True)
    (d / "anonymized.json").write_text('{"plain_text": "<PERSON_1>"}', encoding="utf-8")
    hits = full_tree_pii_sweep(tmp_path, ["Ahmet Yılmaz", "ahmet@example.com"])
    assert len(hits) == 2  # one entry per distinct canary value, even with zero hits
    assert sum(hits.values()) == 0


def test_full_tree_sweep_detects_leaked_value(tmp_path):
    d = tmp_path / "1_original" / "d9"
    d.mkdir(parents=True)
    (d / "original.bin").write_bytes("Contact Ahmet Yılmaz for details.".encode())
    hits = full_tree_pii_sweep(tmp_path, ["Ahmet Yılmaz"])
    assert sum(hits.values()) == 1


def test_full_tree_sweep_missing_root_returns_zero_hits(tmp_path):
    hits = full_tree_pii_sweep(tmp_path / "does-not-exist", ["Ahmet Yılmaz"])
    assert sum(hits.values()) == 0


def test_full_tree_sweep_reports_only_hashes_never_raw_values(tmp_path):
    """The whole point of D1 is a report-safe result: no raw PII in the return value."""
    hits = full_tree_pii_sweep(tmp_path, ["Ahmet Yılmaz"])
    assert "Ahmet Yılmaz" not in str(hits)
    assert all(len(k) == 16 for k in hits)  # sha256[:16] hex digest

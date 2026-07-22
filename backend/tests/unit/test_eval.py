"""Tests for the evaluation harness itself (no NLP models needed).

The scorer must be trustworthy before its numbers mean anything, so we pin its behaviour on
hand-built spans, and check the corpus generates genuinely-detectable, correctly-offset PII.
"""
from __future__ import annotations

from app.anonymization.recognizers.turkish import valid_tckn
from evaluation.corpus import GoldSpan, build_corpus, complete_tckn
from evaluation.score import Aggregate, overlaps, score


def _span(start, end):
    return GoldSpan(start, end, "X")


def test_overlaps_boundaries():
    assert overlaps(0, 5, 4, 9)          # partial overlap
    assert overlaps(2, 8, 3, 4)          # containment
    assert not overlaps(0, 5, 5, 9)      # adjacent, half-open → no overlap
    assert not overlaps(0, 5, 6, 9)      # disjoint


def test_perfect_prediction_scores_one():
    gold = [_span(0, 5), _span(10, 15)]
    pred = [_span(0, 5), _span(10, 15)]
    a = score(gold, pred)
    assert a.recall == 1.0 and a.precision == 1.0 and a.f1 == 1.0
    assert a.over_mask == 0


def test_missed_gold_drops_recall():
    a = score([_span(0, 5), _span(10, 15)], [_span(0, 5)])
    assert a.recall == 0.5
    assert a.precision == 1.0  # the one prediction was a real hit


def test_over_masking_drops_precision():
    # two predictions, only one overlaps the single gold span → precision 1/2, over_mask 1
    a = score([_span(0, 5)], [_span(0, 5), _span(50, 60)])
    assert a.recall == 1.0
    assert a.precision == 0.5
    assert a.over_mask == 1


def test_partial_overlap_counts_as_covered():
    # a prediction that only partially covers the gold still HIDES those chars → covered
    a = score([_span(4, 12)], [_span(0, 6)])
    assert a.covered == 1 and a.recall == 1.0


def test_empty_gold_and_pred_are_defined():
    a = score([], [])
    assert a.recall == 1.0 and a.precision == 1.0 and a.f1 == 1.0


def test_accumulation_across_samples():
    a = Aggregate()
    score([_span(0, 5)], [_span(0, 5)], a)
    score([_span(0, 5)], [], a)  # a miss
    assert a.gold == 2 and a.covered == 1 and a.recall == 0.5


def test_generated_tckns_pass_checksum():
    for nine in ("123456789", "234567890", "111222333", "456789012"):
        tckn = complete_tckn(nine)
        assert len(tckn) == 11
        assert valid_tckn(tckn), f"{tckn} should be a valid TCKN"


def test_corpus_spans_align_with_text():
    # every gold span must slice exactly the PII substring it marks (offsets are correct)
    samples = build_corpus(n_per_template=2)
    assert samples, "corpus should not be empty"
    for s in samples:
        for g in s.spans:
            assert 0 <= g.start < g.end <= len(s.text)
            assert s.text[g.start:g.end].strip() == s.text[g.start:g.end], "no stray whitespace"
    # distractors carry no PII
    assert any(not s.spans for s in samples), "expected distractor samples with no PII"
    assert any(s.spans for s in samples), "expected samples with PII"

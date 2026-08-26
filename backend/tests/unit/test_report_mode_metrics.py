"""Unit tests for evaluation.corpus_bist10.report.mode_check_metrics — aggregation logic only,
independent of a real benchmark run (synthetic ModeCheckResult.safe_dict()-shaped rows)."""
from __future__ import annotations

from evaluation.corpus_bist10.report import mode_check_metrics


def _mapping_row(m1=True, m2=True, m3=True, passed=None):
    checks = {"M1_mapping_complete": m1, "M2_roundtrip_complete": m2, "M3_mapping_contained": m3}
    return {"mode": "mapping", "passed": all(checks.values()) if passed is None else passed,
            "checks": checks}


def _destructive_row(d2a=True, d2b=True, d2c=True, d3=True, passed=None):
    checks = {"D2_no_original": d2a, "D2_no_extracted": d2b, "D2_no_mapping_file": d2c,
              "D3_reversal_fails": d3}
    return {"mode": "destructive", "passed": all(checks.values()) if passed is None else passed,
            "checks": checks}


def test_all_passed_mapping():
    rows = [_mapping_row(), _mapping_row(), _mapping_row()]
    m = mode_check_metrics(rows, "mapping")
    assert m["documents_checked"] == 3
    assert m["all_checks_passed"] == 3
    assert m["all_checks_passed_rate"] == 1.0
    assert m["per_check_pass_rate"]["M1_mapping_complete"] == 1.0
    assert m["per_check_pass_rate"]["M2_roundtrip_complete"] == 1.0
    assert m["per_check_pass_rate"]["M3_mapping_contained"] == 1.0


def test_partial_failure_isolated_to_one_check():
    rows = [_mapping_row(), _mapping_row(m2=False, passed=False), _mapping_row()]
    m = mode_check_metrics(rows, "mapping")
    assert m["all_checks_passed"] == 2
    assert round(m["all_checks_passed_rate"], 4) == round(2 / 3, 4)
    assert m["per_check_pass_rate"]["M1_mapping_complete"] == 1.0
    assert round(m["per_check_pass_rate"]["M2_roundtrip_complete"], 4) == round(2 / 3, 4)
    assert m["per_check_pass_rate"]["M3_mapping_contained"] == 1.0


def test_destructive_checks_use_d_names_not_m_names():
    rows = [_destructive_row(), _destructive_row(d2a=False, passed=False)]
    m = mode_check_metrics(rows, "destructive")
    assert set(m["per_check_pass_rate"]) == {
        "D2_no_original", "D2_no_extracted", "D2_no_mapping_file", "D3_reversal_fails"}
    assert m["per_check_pass_rate"]["D2_no_original"] == 0.5
    assert m["per_check_pass_rate"]["D2_no_extracted"] == 1.0


def test_empty_rows_do_not_divide_by_zero():
    m = mode_check_metrics([], "mapping")
    assert m["documents_checked"] == 0
    assert m["all_checks_passed_rate"] == 0.0
    assert all(v == 0.0 for v in m["per_check_pass_rate"].values())


def test_unknown_mode_returns_no_named_checks():
    m = mode_check_metrics([_mapping_row()], "bogus")
    assert m["per_check_pass_rate"] == {}

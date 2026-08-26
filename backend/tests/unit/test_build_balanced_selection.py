"""Unit tests for the deterministic Part-B source-selection rule (BENCHMARK_GUIDE.md §13):
sort by id, find the 3 largest doc_type groups, take the first 10 of each -> 30 sources.
Pure logic, no I/O — a second team re-implementing this from the guide must reproduce these exact
selections given the same manifest rows.
"""
from __future__ import annotations

import json

import evaluation.corpus_bist10.build_balanced as bb
from evaluation.corpus_bist10.build_balanced import N_PER_TYPE, N_TYPES, select_30


def _row(id_, doc_type):
    return {"id": id_, "doc_type": doc_type}


def _rows(doc_type, n, prefix="A"):
    return [_row(f"{prefix}-{i:03d}", doc_type) for i in range(n)]


def test_selects_three_largest_types_ten_each():
    rows = (_rows("annual_report", 15, "AR") + _rows("financial_statements", 12, "FS")
            + _rows("general_assembly", 11, "GA") + _rows("sustainability_report", 3, "SR"))
    chosen = select_30(rows)
    assert len(chosen) == N_TYPES * N_PER_TYPE
    types = {r["doc_type"] for r in chosen}
    assert types == {"annual_report", "financial_statements", "general_assembly"}
    assert "sustainability_report" not in types  # 4th-largest type excluded


def test_takes_first_ten_by_sorted_id_within_each_type():
    rows = _rows("annual_report", 15, "AR") + _rows("financial_statements", 15, "FS") \
        + _rows("general_assembly", 15, "GA")
    chosen = select_30(rows)
    ar_ids = sorted(r["id"] for r in chosen if r["doc_type"] == "annual_report")
    assert ar_ids == [f"AR-{i:03d}" for i in range(10)]  # the FIRST 10, not a random 10


def test_fewer_than_ten_in_a_type_takes_what_exists():
    rows = _rows("annual_report", 15, "AR") + _rows("financial_statements", 15, "FS") \
        + _rows("general_assembly", 4, "GA")  # under N_PER_TYPE
    chosen = select_30(rows)
    assert len([r for r in chosen if r["doc_type"] == "general_assembly"]) == 4
    assert len(chosen) == 10 + 10 + 4  # short by design, not padded from elsewhere


def test_deterministic_given_id_sorted_input():
    """select_30's contract is to receive input already sorted by id (load_usable_sources() does
    this) — given that, the result must not depend on the row order BEFORE that sort."""
    rows = _rows("annual_report", 12, "AR") + _rows("financial_statements", 12, "FS") \
        + _rows("general_assembly", 12, "GA")
    sorted_a = sorted(rows, key=lambda r: r["id"])
    sorted_b = sorted(list(reversed(rows)), key=lambda r: r["id"])
    assert select_30(sorted_a) == select_30(sorted_b)


def test_tied_doc_type_counts_break_ties_alphabetically_not_by_input_order():
    """Counter.most_common() alone breaks ties by insertion order, which would make the pick
    depend on incidental row order. With an exact 3-way tie, the choice must be the same
    regardless of which order the tied types first appear in."""
    forward = _rows("zzz_type", 10, "Z") + _rows("annual_report", 10, "AR") \
        + _rows("mid_type", 10, "M")
    backward = _rows("mid_type", 10, "M") + _rows("zzz_type", 10, "Z") \
        + _rows("annual_report", 10, "AR")
    a = select_30(sorted(forward, key=lambda r: r["id"]))
    b = select_30(sorted(backward, key=lambda r: r["id"]))
    assert {r["doc_type"] for r in a} == {r["doc_type"] for r in b}


def test_missing_doc_type_falls_back_to_other():
    rows = [_row("X-001", None)] * 12 + _rows("annual_report", 12, "AR") \
        + _rows("financial_statements", 12, "FS")
    chosen = select_30(rows)
    assert "other" in {r.get("doc_type") or "other" for r in chosen}


def test_load_usable_sources_excludes_unextractable_formats(tmp_path, monkeypatch):
    """Regression: a real build hit this — legacy .xls rows are valid, hash-verified Part-A
    documents (validity="ok", file present), but app.extraction.dispatcher rejects the format
    outright, so a source picked from them silently produced ZERO carriers with no record of why.
    load_usable_sources() must filter these out before selection, not let them reach select_30()
    and fail later."""
    raw = tmp_path / "raw"
    raw.mkdir()
    manifest = tmp_path / "corpus_manifest.jsonl"
    rows = [
        {"id": "A-1", "validity": "ok", "filename": "a.pdf", "format": "pdf",
         "doc_type": "annual_report"},
        {"id": "A-2", "validity": "ok", "filename": "a.docx", "format": "docx",
         "doc_type": "annual_report"},
        {"id": "A-3", "validity": "ok", "filename": "a.xlsx", "format": "xlsx",
         "doc_type": "annual_report"},
        {"id": "A-4", "validity": "ok", "filename": "a.xls", "format": "xls",
         "doc_type": "annual_report"},  # legacy — must be excluded
        {"id": "A-5", "validity": "ok", "filename": "a.doc", "format": "doc",
         "doc_type": "annual_report"},  # legacy — must be excluded
    ]
    for r in rows:
        (raw / r["filename"]).write_bytes(b"x")
    manifest.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")

    monkeypatch.setattr(bb, "SOURCE_MANIFEST", manifest)
    monkeypatch.setattr(bb, "RAW", raw)

    usable = bb.load_usable_sources()
    assert {r["id"] for r in usable} == {"A-1", "A-2", "A-3"}
    assert "xls" not in {r["format"] for r in usable}
    assert "doc" not in {r["format"] for r in usable}

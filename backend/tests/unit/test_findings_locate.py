"""Locating the auditor's residual terms in the masked text (review hardening C11).

A term is never matched inside a placeholder, a kept value matches whitespace-normalized, and a
finding that ends right where a split-cell fragment was removed does not stretch over the removed
fragment when mapped back to original offsets.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.anonymization.spans import MaskEdit
from app.extraction.base import Block, ExtractedContent
from app.main import app
from app.models.document import Document, DocumentStatus, FileKind
from app.review.findings import locate
from app.services.deps import get_repository

client = TestClient(app)


def _ranges(findings: list[dict]) -> list[tuple[int, int]]:
    return [(f["masked_start"], f["masked_end"]) for f in findings]


def test_a_term_is_never_matched_inside_a_placeholder() -> None:
    findings, unlocated = locate([("u1", "<PERSON_1> ile PERSON görüştü")], ["PERSON"], [])
    assert _ranges(findings) == [(15, 21)]
    assert unlocated == []


def test_a_term_found_only_inside_placeholders_is_unlocated() -> None:
    findings, unlocated = locate([("u1", "<US_BANK_NUMBER_1> geldi")], ["BANK_NUMBER"], [])
    assert findings == [] and unlocated == ["BANK_NUMBER"]


def test_spellings_of_one_term_give_one_finding() -> None:
    terms = ["Ahmet Bey", "ahmet  bey", "AHMET BEY"]
    findings, unlocated = locate([("u1", "Ahmet Bey geldi")], terms, [])
    assert _ranges(findings) == [(0, 9)] and unlocated == []


def test_kept_values_match_whitespace_normalized() -> None:
    findings, _ = locate([("u1", "Kuzey  Grubu geldi")], ["Kuzey Grubu"], ["kuzey   GRUBU"])
    assert [f["status"] for f in findings] == ["kept"]


def test_a_finding_ending_at_an_empty_edit_keeps_its_own_end() -> None:
    """Split-cell continuation fragments are empty edits; mapping a finding's END back to the
    original must not jump over the removed fragment that sits exactly there."""
    repo = get_repository()
    repo.save_document(Document(id="emptyedit1", filename="t.docx", kind=FileKind.docx,
                                status=DocumentStatus.NEEDS_HUMAN_REVIEW))
    repo.save_extracted("emptyedit1", ExtractedContent(
        kind=FileKind.docx, blocks=[Block(block_id="b1", text="Ali Veli21 09")]))
    repo.save_anonymized("emptyedit1", ExtractedContent(
        kind=FileKind.docx, blocks=[Block(block_id="b1", text="Ali Veli")]))
    edit = MaskEdit(start=8, end=13, masked_start=8, masked_end=8, text="",
                    entity_type="TR_GSM", source="adjacency")
    repo.save_edits("emptyedit1", {"b1": [edit.model_dump()]})
    repo.save_findings("emptyedit1", [{
        "id": "f1", "unit_id": "b1", "masked_start": 0, "masked_end": 8,
        "code": "audit_residual", "severity": "high", "status": "open"}])
    item = client.get("/api/documents/emptyedit1/review").json()["items"][0]
    assert (item["start"], item["end"]) == (0, 8)

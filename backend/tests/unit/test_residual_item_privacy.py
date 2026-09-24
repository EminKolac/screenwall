"""The LLM auditor's residual items are stored in layer 4 (document.json, every iteration).

Only non-identifying hints may stay: a known type, the snippet's length and a bare page
reference. The model's free text (`note`, a descriptive `location`, an invented `type`) can
repeat the very value it found, so it never reaches storage. The raw snippets still feed the
next masking pass, in memory only (`raw_terms`).
"""
from __future__ import annotations

import json

from app.models.findings import AuditResult, SensitiveItem

VERDICT = {
    "approved": False,
    "risk_level": "high",
    "remaining_sensitive_items": [
        {"type": "PERSON: Ahmet Yılmaz", "snippet": "Ahmet Yılmaz",
         "location": "Sayfa 2, Ahmet Yılmaz'ın imzası",
         "note": "Ahmet Yılmaz açıkta kalmış; TCKN 10000000146"},
        {"type": "email", "snippet": "ayse.kaya@example.com", "location": "page 3 footer",
         "note": "e-posta"},
        {"type": "Phone Number", "snippet": "0532 111 22 33", "location": "the signature block"},
    ],
    "summary": "",
    "recommended_next_action": "reanonymize",
}


def test_only_type_length_and_page_are_kept():
    res = AuditResult.parse_llm_json(json.dumps(VERDICT, ensure_ascii=False))
    stored = json.dumps(res.model_dump(mode="json"), ensure_ascii=False)
    for value in ("Ahmet", "Yılmaz", "10000000146", "ayse.kaya", "0532", "imza", "signature"):
        assert value not in stored
    person, email, phone = res.remaining_sensitive_items
    assert (person.type, person.snippet, person.location, person.note) == (
        "UNKNOWN", "‹12 chars›", "page 2", "")
    assert (email.type, email.location, email.note) == ("EMAIL", "page 3", "")
    assert (phone.type, phone.location) == ("PHONE_NUMBER", "")
    # The next masking pass still gets the literal values — in memory, never serialized.
    assert res.raw_terms == ["Ahmet Yılmaz", "ayse.kaya@example.com", "0532 111 22 33"]


def test_the_heuristic_labels_are_kept():
    for label in ("EMAIL", "IBAN", "CARD", "TR_PHONE", "SECRET", "TR_TCKN"):
        assert SensitiveItem(type=label, snippet="x").type == label


def test_a_page_number_cannot_smuggle_an_identifier():
    item = SensitiveItem(type="TCKN", location="page 10000000146")
    assert item.location == "" and item.type == "TCKN"


def test_stored_hints_survive_a_round_trip():
    """document.json is read back and saved again on every status change."""
    res = AuditResult.parse_llm_json(json.dumps(VERDICT, ensure_ascii=False))
    stored = res.model_dump(mode="json")
    again = AuditResult.model_validate(stored).model_dump(mode="json")
    assert again["remaining_sensitive_items"] == stored["remaining_sensitive_items"]
    assert stored["remaining_sensitive_items"][0]["snippet"] == "‹12 chars›"

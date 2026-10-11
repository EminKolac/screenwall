"""v0.1.2: a statistical PERSON span that contains a document-type noun is a heading, not a name.

Found in a live test of the app (2026-10-11): the DOCX heading "Tedarik Sözleşmesi (örnek, sentetik
veri)" became <PERSON_1> with evidence ['recognizer:PERSON', 'detector:en'] — the English spaCy
model reads any two title-case words as a person. The rule's word list is a closed list of
document-type nouns written from general knowledge (app/anonymization/gates.py), not benchmark
terms.
"""
from __future__ import annotations

import pytest

from app.anonymization.engine import Engine, EntitySpan
from app.anonymization.gates import contains_document_noun, implausible_person_ner
from app.extraction.base import Block, BlockType, ExtractedContent
from app.models.document import FileKind, Language

_PERSONISH = ("PERSON", "TR_PERSON_CTX")


def _span(text: str, surface: str, *, entity_type: str = "PERSON", source: str = "en"):
    start = text.index(surface)
    return EntitySpan(entity_type=entity_type, start=start, end=start + len(surface), score=0.85,
                      source=source)


# --------------------------------------------------------------- the gate itself

@pytest.mark.parametrize("surface", [
    "Tedarik Sözleşmesi",
    "Hizmet Sözleşmeleri",
    "Faaliyet Raporu",
    "Satış Faturası",
    "Fiyat Teklifi",
    "Toplantı Tutanağı",
    "Teknik Şartname",
    "Gizlilik Protokolü",
    "İzin Dilekçesi",
    "Disiplin Yönetmeliği",
    "Kurul Kararı",
    "Kira Sözleşmesi'nin",
    "SUPPLY AGREEMENT",
    "Annual Report",
    "Service Contract",
    "Proforma Invoice",
])
@pytest.mark.parametrize("source", ["en", "tr"])
def test_person_span_with_a_document_noun_is_rejected(surface, source):
    assert implausible_person_ner(_span(surface, surface, source=source), surface) is True


@pytest.mark.parametrize("surface", [
    "Ahmet Yılmaz",
    "Ayşe Demir",
    "Ekrem Karaca",       # "Ek" is in the list; a name that merely starts with it is not
    "Raporlu Bey",        # neither is a word that only starts with "Rapor"
    "Kemal Vardar",
    "John Smith",
    "Bill Gates",         # "bill" is deliberately not in the list (it is a given name)
])
def test_real_names_are_not_touched_by_the_document_noun_rule(surface):
    assert contains_document_noun(surface) is False
    assert implausible_person_ner(_span(surface, surface), surface) is False


@pytest.mark.parametrize("entity_type,source", [
    ("ORGANIZATION", "en"),   # PERSON-only rule
    ("LOCATION", "tr"),
    ("PERSON", "deny"),       # an explicit always-mask term is never gated
])
def test_rule_applies_only_to_statistical_person_spans(entity_type, source):
    text = "Tedarik Sözleşmesi"
    span = _span(text, text, entity_type=entity_type, source=source)
    assert implausible_person_ner(span, text) is False


# --------------------------------------------------------------- end to end (real models)

def _detected(text: str) -> list[tuple[str, str]]:
    return [(s.entity_type, text[s.start:s.end]) for s in Engine().detect(text)]


@pytest.mark.parametrize("text", [
    "Tedarik Sözleşmesi (örnek, sentetik veri)",
    "Hizmet Sözleşmesi",
    "Faaliyet Raporu",
    "Satış Faturası",
])
def test_title_case_document_heading_is_not_a_person(text):
    assert not [d for d in _detected(text) if d[0] in _PERSONISH]


@pytest.mark.parametrize("text,name", [
    ("Yetkili: Ahmet Yılmaz", "Ahmet Yılmaz"),
    ("Sözleşmeyi imzalayan Ayşe Demir", "Ayşe Demir"),
    ("Kira Sözleşmesi Ahmet Yılmaz", "Ahmet Yılmaz"),
    ("Raporu hazırlayan: Mehmet Kaya", "Mehmet Kaya"),
])
def test_names_next_to_document_nouns_are_still_persons(text, name):
    found = _detected(text)
    assert any(t in _PERSONISH and surface == name for t, surface in found), found
    # ...and the document noun itself is not swallowed into a person span
    assert not any(t in _PERSONISH and contains_document_noun(surface) for t, surface in found)


def test_docx_heading_from_the_live_test_stays_readable():
    heading = "Tedarik Sözleşmesi (örnek, sentetik veri)"
    content = ExtractedContent(kind=FileKind.docx, blocks=[
        Block(block_id="h", type=BlockType.heading, text=heading),
        Block(block_id="p", text="Yetkili: Ahmet Yılmaz"),
    ])
    out = Engine().anonymize(content, Language.mixed)
    texts = {b.block_id: b.text for b in out.content.blocks}
    assert texts["h"] == heading
    assert "Ahmet Yılmaz" not in texts["p"] and "<PERSON_1>" in texts["p"]

from app.anonymization.engine import EntitySpan, resolve_spans
from app.anonymization.presidio_engine import PresidioEngine
from app.anonymization.recognizers.turkish import valid_tckn
from app.extraction.base import Block, BlockType, ExtractedContent, TableCell
from app.models.document import FileKind, Language

eng = PresidioEngine()


def _content(*texts: str) -> ExtractedContent:
    return ExtractedContent(
        kind=FileKind.docx,
        blocks=[Block(block_id=str(i), text=t) for i, t in enumerate(texts)],
    )


def test_valid_tckn_checksum():
    assert valid_tckn("10000000146")
    assert not valid_tckn("12345678901")
    assert not valid_tckn("00000000000")


def test_resolve_spans_priority_prevents_partial_leak():
    spans = [
        EntitySpan(start=0, end=19, entity_type="NRP", score=0.85),
        EntitySpan(start=5, end=37, entity_type="IBAN_CODE", score=1.0),
        EntitySpan(start=10, end=24, entity_type="DATE_TIME", score=0.85),
    ]
    kept = resolve_spans(spans)
    iban = next(s for s in kept if s.entity_type == "IBAN_CODE")
    assert (iban.start, iban.end) == (5, 37)
    assert all(s is iban or s.end <= iban.start or s.start >= iban.end for s in kept)


def test_turkish_pii_fully_masked_no_partial_leak():
    c = _content(
        "Ahmet Yılmaz, TCKN 10000000146, e-posta ahmet@example.com, "
        "IBAN TR33 0006 1005 1978 6457 8413 26."
    )
    t = eng.anonymize(c, Language.tr).content.plain_text
    for leak in ["Ahmet Yılmaz", "10000000146", "ahmet@example.com", "1978", "6457", "8413"]:
        assert leak not in t, f"leaked '{leak}': {t}"
    assert "<TCKN_1>" in t and "<EMAIL_1>" in t and "<IBAN_1>" in t and "<PERSON_1>" in t


def test_deterministic_placeholders_reuse_token():
    c = _content("Ahmet Yılmaz ile Ahmet Yılmaz aynı kişidir.")
    t = eng.anonymize(c, Language.tr).content.plain_text
    assert "Ahmet Yılmaz" not in t
    assert "<PERSON_2>" not in t  # same value reuses <PERSON_1>


def test_extra_deny_terms_masked():
    c = _content("Project Falcon remains confidential across the deal.")
    t = eng.anonymize(c, Language.en, extra_deny_terms=["Falcon"]).content.plain_text
    assert "Falcon" not in t


def test_table_cells_anonymized():
    c = ExtractedContent(kind=FileKind.xlsx, blocks=[Block(
        block_id="t", type=BlockType.table,
        cells=[TableCell(row=0, col=0, text="Ahmet Yılmaz"),
               TableCell(row=0, col=1, text="ahmet@example.com")])])
    t = eng.anonymize(c, Language.tr).content.plain_text
    assert "Ahmet Yılmaz" not in t and "ahmet@example.com" not in t


def test_mapping_excluded_from_serialization():
    out = eng.anonymize(_content("Reach me at ahmet@example.com"), Language.en)
    assert "mapping" not in out.model_dump()
    assert out.mapping  # accessible as attribute (layer-2 only)

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


def test_tr_phone_masked_whole_no_fragment_leak():
    """Regression: '0532 123 45 67' used to mask as '<DATE_2> 123 <DATE_1>' — spaCy split the
    number into two DATE_TIME fragments (hard-coded 0.85 score) that outranked the validated
    TR_GSM pattern match (0.5-0.85) by pure score, leaving the middle digits in the clear. The
    trust-tiered resolve_spans + dropping DATE_TIME (nlp.py) must mask it as one contiguous span."""
    c = _content("Kayıt için cep: 0532 123 45 67 numaralı hattı arayınız.")
    t = eng.anonymize(c, Language.tr).content.plain_text
    for fragment in ["0532", "123", "45 67", "45", "67"]:
        assert fragment not in t, f"leaked phone fragment '{fragment}': {t}"
    assert "<PHONE_1>" in t
    assert "<DATE_" not in t  # DATE_TIME is dropped entirely (nlp.py labels_to_ignore)


def test_resolve_spans_pattern_outranks_higher_scored_statistical_fragment():
    """A short, high-scored statistical NER fragment must not beat a longer, lower-scored but
    format-validated pattern match — the exact shape of the phone-fragmentation bug, at the
    resolve_spans unit level (no NLP models involved)."""
    # "0.85" NER fragment covering the middle of a value vs. a 0.5-scored pattern match covering
    # the whole value.
    fragment = EntitySpan(start=5, end=8, entity_type="DATE_TIME", score=0.85)
    whole = EntitySpan(start=0, end=12, entity_type="TR_GSM", score=0.5)
    kept = resolve_spans([fragment, whole])
    assert kept == [whole]


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


def test_by_source_reports_presidio_stage():
    out = eng.anonymize(_content("Ahmet Yılmaz, e-posta ahmet@example.com"), Language.tr)
    assert out.by_source.get("presidio", 0) >= 1  # stage ① attributed


# --- Stage ② — OpenAI Privacy Filter (local detector) merges into the same resolution ---

def test_privacy_filter_span_wins_overlap_by_score():
    # A Privacy Filter person span (0.9) beats an overlapping weaker Presidio NRP span (0.3).
    pf = EntitySpan(start=0, end=12, entity_type="PERSON", score=0.9, source="privacy_filter")
    weak = EntitySpan(start=0, end=5, entity_type="NRP", score=0.3, source="tr")
    assert resolve_spans([weak, pf]) == [pf]


def test_privacy_filter_detector_spans_masked_and_counted(monkeypatch):
    import app.anonymization.presidio_engine as pe

    class FakePF:  # a made-up brand NER wouldn't catch; PF "detects" it
        def detect(self, text):
            i = text.find("Zorptech")
            return [] if i == -1 else [EntitySpan(
                start=i, end=i + len("Zorptech"),
                entity_type="PERSON", score=0.99, source="privacy_filter")]

    monkeypatch.setattr(pe, "get_privacy_filter", lambda: FakePF())
    out = eng.anonymize(_content("Please contact Zorptech about the deal."), Language.en)
    assert "Zorptech" not in out.content.plain_text
    assert "<PERSON_" in out.content.plain_text
    assert out.by_source.get("privacy_filter", 0) >= 1


def test_detection_cache_preserves_output_and_determinism():
    """The per-document detection cache must be an exact memo, not an approximation: repeating the
    same text must still be masked everywhere, with the SAME placeholder token each time."""
    line = "İletişim: Kemal Vardar, e-posta kemal.vardar@ornekposta.com"
    out = eng.anonymize(_content(line, line, line, line), Language.mixed)
    texts = [b.text for b in out.content.blocks]

    assert all("kemal.vardar@ornekposta.com" not in t for t in texts), "repeat occurrence leaked"
    assert len(set(texts)) == 1, "identical input produced different placeholders"
    assert "<EMAIL_1>" in texts[0]

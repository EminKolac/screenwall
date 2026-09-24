"""Engine-level decision semantics (review hardening C1, C2, C6, C7).

C1  keep and allow terms use CONTAINMENT: a span is suppressed only when it lies fully inside an
    occurrence of the term. Keeping "Barış" (a false LOCATION) must not reveal "Barış Demir".
C2  a reviewer's document-wide mask is a forced range applied before detection, so no allow or
    keep term can drop it.
C6  the table pre-mask (values split across cells) respects the reviewer's keep ranges.
C7  a global always-mask term keeps the family the reviewer chose.
"""
from __future__ import annotations

from app.anonymization.engine import Engine, Overrides
from app.extraction.base import Block, BlockType, ExtractedContent, TableCell
from app.models.document import FileKind, Language


def _doc(*texts: str) -> ExtractedContent:
    return ExtractedContent(kind=FileKind.docx, blocks=[
        Block(block_id=f"p{i}", type=BlockType.paragraph, text=t) for i, t in enumerate(texts)])


def _text(out) -> str:
    return out.content.plain_text


# ---------------------------------------------------------------- C1 containment

def test_an_allow_term_does_not_drop_a_longer_overlapping_span() -> None:
    out = Engine().anonymize(_doc("Barış Demir toplantıya geldi."), Language.tr,
                             extra_deny_terms=["Barış Demir"], extra_allow_terms=["Barış"])
    assert "Barış Demir" not in _text(out)


def test_an_allow_term_still_drops_a_span_inside_it() -> None:
    out = Engine().anonymize(_doc("Barış Demir Holding toplantıya geldi."), Language.tr,
                             extra_deny_terms=["Barış Demir"],
                             extra_allow_terms=["barış  demir holding"])
    assert "Barış Demir Holding" in _text(out)


def test_keeping_a_false_location_does_not_reveal_the_person() -> None:
    """The reported bug with real NER: "Barış" alone is a false LOCATION the reviewer keeps; the
    person "Barış Demir" must stay masked in this and every later document."""
    text = "Barış Demir ve Barış Yılmaz geldi. Barış görüşmesi sürdü."
    out = Engine().anonymize(_doc(text), Language.tr, overrides=Overrides(keep_terms=["Barış"]))
    assert "Barış Demir" not in _text(out)
    assert "Barış görüşmesi" in _text(out)


def test_a_keep_range_only_protects_spans_inside_it() -> None:
    text = "Barış Demir toplantıya geldi."
    out = Engine().anonymize(_doc(text), Language.tr, extra_deny_terms=["Barış Demir"],
                             overrides=Overrides(keep_ranges={"p0": [(0, 5)]}))
    assert "Barış Demir" not in _text(out)


# ---------------------------------------------------------------- C2 forced document masks

def test_a_document_mask_survives_a_seeded_allow_term() -> None:
    text = "Kuzey Grubu Protokol Ekibi toplandı."
    out = Engine().anonymize(_doc(text), Language.tr, extra_allow_terms=["Protokol"],
                             overrides=Overrides(mask_terms={"Kuzey Grubu Protokol Ekibi": "ORG"}))
    assert "Kuzey Grubu" not in _text(out) and "<ORG_1>" in _text(out)


def test_a_keep_term_cannot_drop_a_document_mask() -> None:
    text = "Kuzey Grubu Toplantısı yapıldı."
    ov = Overrides(mask_terms={"Kuzey Grubu": "ORG"}, keep_terms=["Kuzey Grubu Toplantısı"])
    out = Engine().anonymize(_doc(text), Language.tr, overrides=ov)
    assert _text(out).startswith("<ORG_1> Toplantısı")
    user = [e for e in out.edits["p0"] if e.source == "user"]
    assert [(e.start, e.end, e.entity_type) for e in user] == [(0, 11, "USER:ORG")]


def test_a_keep_range_exempts_one_occurrence_of_a_document_mask() -> None:
    text = "Kuzey Grubu geldi. Kuzey Grubu gitti."
    ov = Overrides(mask_terms={"kuzey  GRUBU": "ORG"}, keep_ranges={"p0": [(0, 11)]})
    out = Engine().anonymize(_doc(text), Language.tr, overrides=ov)
    assert _text(out) == "Kuzey Grubu geldi. <ORG_1> gitti."


# ---------------------------------------------------------------- C6 tables

def _split_phone(keep: dict | None = None):
    cells = [TableCell(row=3, col=1, text="0532 76"), TableCell(row=3, col=2, text="4 21 09")]
    content = ExtractedContent(kind=FileKind.xlsx,
                               blocks=[Block(block_id="t", type=BlockType.table, cells=cells)])
    return Engine().anonymize(content, Language.tr, overrides=Overrides(keep_ranges=keep or {}))


def test_the_table_premask_masks_a_split_value_without_keeps() -> None:
    texts = [c.text for c in _split_phone().content.blocks[0].cells]
    assert "0532" not in " ".join(texts)


def test_the_table_premask_respects_keep_ranges() -> None:
    out = _split_phone({"t:r3c1": [(0, 7)], "t:r3c2": [(0, 7)]})
    assert [c.text for c in out.content.blocks[0].cells] == ["0532 76", "4 21 09"]


# ---------------------------------------------------------------- C7 global families

def test_a_global_term_keeps_its_family_whatever_the_spelling() -> None:
    out = Engine().anonymize(_doc("Zeytinfon raporu hazır. ZEYTINFON onayladı."), Language.tr,
                             extra_deny_terms=["zeytinfon"],
                             deny_families={"Zeytinfon": "ORG"})
    assert _text(out) == "<ORG_1> raporu hazır. <ORG_1> onayladı."
    assert {e.source for e in out.edits["p0"]} == {"deny"}


def test_an_explicit_deny_term_beats_an_identical_allow_entry() -> None:
    """A global mask of a word the seeded allow-list happens to hold must not be dropped by it."""
    out = Engine().anonymize(_doc("Protokol imzalandı."), Language.tr,
                             extra_deny_terms=["Protokol"], extra_allow_terms=["protokol"])
    assert "Protokol" not in _text(out)


def test_a_document_keep_still_beats_a_global_mask() -> None:
    out = Engine().anonymize(_doc("Zeytinfon raporu."), Language.tr,
                             extra_deny_terms=["Zeytinfon"],
                             overrides=Overrides(keep_terms=["zeytinfon"]))
    assert _text(out) == "Zeytinfon raporu."

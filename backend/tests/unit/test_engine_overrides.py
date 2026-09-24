"""Human review decisions (Overrides) and the metadata guarantee."""
from __future__ import annotations

from app.anonymization.engine import Engine, Overrides
from app.extraction.base import Block, BlockType, ExtractedContent
from app.models.document import FileKind, Language

TEXT = "Sayın Ayşe Kaya toplantıya katıldı. Kuzey Grubu raporu Ayşe Kaya imzaladı."


def _doc(text: str = TEXT, **meta: str) -> ExtractedContent:
    return ExtractedContent(kind=FileKind.docx, metadata=dict(meta),
                            blocks=[Block(block_id="p1", type=BlockType.paragraph, text=text)])


def test_mask_occurrence_uses_the_chosen_family() -> None:
    start = TEXT.index("Kuzey Grubu")
    ov = Overrides(mask_ranges={"p1": [(start, start + len("Kuzey Grubu"), "ORG")]})
    out = Engine().anonymize(_doc(), Language.tr, overrides=ov)
    masked = out.content.blocks[0].text
    assert "Kuzey Grubu" not in masked and "<ORG_" in masked
    user = [e for e in out.edits["p1"] if e.source == "user"]
    assert len(user) == 1 and (user[0].start, user[0].entity_type) == (start, "USER:ORG")


def test_keep_occurrence_leaves_only_that_occurrence_open() -> None:
    first = TEXT.index("Ayşe Kaya")
    ov = Overrides(keep_ranges={"p1": [(first, first + len("Ayşe Kaya"))]})
    out = Engine().anonymize(_doc(), Language.tr, overrides=ov)
    masked = out.content.blocks[0].text
    assert masked.startswith("Sayın Ayşe Kaya ")  # kept occurrence
    assert masked.count("Ayşe Kaya") == 1  # the second one is still masked (by NER or propagation)


def test_document_wide_terms() -> None:
    ov = Overrides(mask_terms={"Kuzey Grubu": "ORG"}, keep_terms=["Ayşe Kaya"])
    out = Engine().anonymize(_doc(), Language.tr, overrides=ov)
    masked = out.content.blocks[0].text
    assert masked.count("Ayşe Kaya") == 2
    assert "Kuzey Grubu" not in masked and "<ORG_" in masked


def test_anonymized_copy_never_carries_extractor_metadata() -> None:
    out = Engine().anonymize(_doc(author="Selin Özdemir", sheets="Maaşlar,Özdemir"), Language.tr)
    assert out.content.metadata == {}

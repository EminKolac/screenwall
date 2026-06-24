from app.extraction.base import Block, ExtractedContent
from app.language.detector import detect_content_language, detect_language
from app.models.document import FileKind, Language
from tests.conftest import EN_PARA, TR_PARA


def test_detect_turkish():
    assert detect_language(TR_PARA) == Language.tr


def test_detect_english():
    assert detect_language(EN_PARA) == Language.en


def test_short_text_unknown():
    assert detect_language("ok") == Language.unknown


def test_mixed_content_and_per_block_annotation():
    content = ExtractedContent(
        kind=FileKind.docx,
        blocks=[Block(block_id="1", text=TR_PARA), Block(block_id="2", text=EN_PARA)],
    )
    assert detect_content_language(content) == Language.mixed
    assert content.blocks[0].language == Language.tr
    assert content.blocks[1].language == Language.en


def test_single_language_content():
    content = ExtractedContent(kind=FileKind.docx, blocks=[Block(block_id="1", text=TR_PARA)])
    assert detect_content_language(content) == Language.tr

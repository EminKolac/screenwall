"""The engine's edit list ties every placeholder to its original range (review screen contract)."""
from __future__ import annotations

from app.anonymization.engine import Engine
from app.extraction.base import Block, BlockType, ExtractedContent, TableCell
from app.models.document import FileKind, Language


def _check_unit(original: str, masked: str, edits) -> None:
    prev_o = prev_m = 0
    for e in edits:
        assert original[prev_o:e.start] == masked[prev_m:e.masked_start]
        assert masked[e.masked_start:e.masked_end] == e.text
        prev_o, prev_m = e.end, e.masked_end
    assert original[prev_o:] == masked[prev_m:]


def test_paragraph_edits_map_both_ways() -> None:
    text = ("Sayın Ayşe Kaya, TCKN 10000000146 ve e-posta ayse.kaya@example.com. "
            "Kaya ailesi adına imza.")
    content = ExtractedContent(kind=FileKind.docx,
                               blocks=[Block(block_id="p1", type=BlockType.paragraph, text=text)])
    out = Engine().anonymize(content, Language.tr)
    masked = out.content.blocks[0].text
    edits = out.edits["p1"]
    assert edits, "expected masked spans"
    _check_unit(text, masked, edits)
    by_text = {text[e.start:e.end]: e for e in edits}
    assert "10000000146" in by_text
    assert by_text["10000000146"].text.startswith("<TCKN_")
    # the value never appears in the edit records themselves
    assert all("10000000146" not in e.model_dump_json() for e in edits)


def test_table_cells_get_their_own_unit_ids() -> None:
    cells = [TableCell(row=1, col=1, text="0532 76"), TableCell(row=1, col=2, text="4 21 09"),
             TableCell(row=2, col=1, text="Toplam"), TableCell(row=2, col=2, text="42")]
    content = ExtractedContent(kind=FileKind.xlsx,
                               blocks=[Block(block_id="t0", type=BlockType.table, cells=cells)])
    out = Engine().anonymize(content, Language.tr)
    assert set(out.edits) == {"t0:r1c1", "t0:r1c2", "t0:r2c1", "t0:r2c2"}
    by_cell = {(c.row, c.col): c.text for c in out.content.blocks[0].cells}
    for cell in cells:
        uid = f"t0:r{cell.row}c{cell.col}"
        _check_unit(cell.text, by_cell[(cell.row, cell.col)], out.edits[uid])
    # the split phone number: first cell carries the placeholder, the second loses its fragment
    first, second = out.edits["t0:r1c1"], out.edits["t0:r1c2"]
    assert first and first[0].text.startswith("<PHONE_") and first[0].source == "adjacency"
    assert second and second[0].text == "" and second[0].masked_start == second[0].masked_end


def test_propagated_variant_is_recorded_with_its_mode() -> None:
    text = "Adres: Bağdat Caddesi No 145 Kadıköy. Yazışma: BağdatCaddesiNo145 Kadıköy."
    content = ExtractedContent(kind=FileKind.docx,
                               blocks=[Block(block_id="p1", type=BlockType.paragraph, text=text)])
    out = Engine().anonymize(content, Language.tr)
    masked = out.content.blocks[0].text
    _check_unit(text, masked, out.edits["p1"])
    assert "BağdatCaddesiNo145" not in masked

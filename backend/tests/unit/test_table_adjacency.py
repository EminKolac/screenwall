"""Deney döngüsü Faz 2 iterasyon 1: tablo satırı bitişiklik (adjacency) düzeltmesi.

GoldBench stres testinin `split_run_pii` senaryosu bunu kanıtladı: PII bir tablo satırında komşu
hücrelere bölünmüşse (klasik XLSX split-run tuzağı), hücreler tek tek taranınca değer hiçbir
dedektörü tetiklemez ve APPROVED belgeye açıkta sızar (release gate ihlali — 3/6 kritik yanlış
onayın kaynağıydı). `PresidioEngine._row_adjacency_premask` bunu satırı birleştirip ikinci bir
tespit turuyla kapatıyor.
"""
from __future__ import annotations

from app.anonymization.presidio_engine import PresidioEngine
from app.extraction.base import Block, BlockType, ExtractedContent, TableCell
from app.models.document import FileKind, Language


def _table(cells: list[TableCell]) -> ExtractedContent:
    return ExtractedContent(
        kind=FileKind.xlsx,
        blocks=[Block(block_id="0", type=BlockType.table, cells=cells)])


def _row_texts(out, row: int = 3) -> list[str]:
    cells = sorted(
        (c for c in out.content.blocks[0].cells if c.row == row), key=lambda c: c.col)
    return [c.text for c in cells]


def test_phone_split_across_adjacent_cells_is_masked():
    cells = [TableCell(row=3, col=1, text="0532 76"), TableCell(row=3, col=2, text="4 21 09")]
    out = PresidioEngine().anonymize(_table(cells), Language.tr)
    texts = _row_texts(out)
    assert "0532" not in " ".join(texts)
    assert "4 21 09" not in " ".join(texts)
    assert any("<PHONE_" in t for t in texts)


def test_card_split_across_adjacent_cells_is_masked():
    cells = [TableCell(row=3, col=1, text="4111 1111"), TableCell(row=3, col=2, text="1111 1111")]
    out = PresidioEngine().anonymize(_table(cells), Language.tr)
    texts = _row_texts(out)
    assert "4111 1111 1111 1111" not in " ".join(texts)
    assert any("<CARD_" in t for t in texts)


def test_same_cell_pii_is_masked_exactly_once():
    """Tek bir hücreye tam sığan PII, satır bitişiklik turu YÜZÜNDEN çift maskelenmemeli (aynı
    değer için iki farklı token üretilmemeli) — normal per-hücre yolu zaten yeterli. İkinci
    hücrenin içeriği NER-nötr (rakam) seçildi ki test, bu dosyanın konusu olmayan bağımsız bir
    NER yanlış-pozitifiyle (bkz. dosya sonu notu) karışmasın."""
    cells = [TableCell(row=1, col=1, text="0532 764 21 09"), TableCell(row=1, col=2, text="42")]
    out = PresidioEngine().anonymize(_table(cells), Language.tr)
    texts = _row_texts(out, row=1)
    assert texts[0].count("<PHONE_") == 1
    assert texts[1] == "42"


def test_unrelated_adjacent_cells_do_not_trigger_adjacency_pass_false_positive():
    """İki alakasız kısa hücre yan yana geldi diye bitişiklik turu rastgele bir PII üretmemeli.
    Bitişiklik turu YALNIZ deterministik/yapısal türlerle sınırlı (`_ADJACENCY_SAFE_TYPES`) —
    istatistiksel NER türleri (PERSON dahil) kapsam dışı, bu yüzden birleştirilmiş "42 99" gibi
    bir metin adjacency turunda hiçbir şeyi tetiklemez. (Not: bu satır iki NER-nötr rakam hücresi
    kullanıyor — "Ürün"/"Genel" gibi bazı sıradan Türkçe kelimeler bu küçük modelde PER-HÜCRE
    turunda zaten PERSON'a yanlış-pozitif üretiyor; o, bu testin veya bitişiklik turunun konusu
    DEĞİL, ayrı ve önceden bilinen bir NER sınırı — bkz. CALIBRATION.md.)"""
    cells = [TableCell(row=5, col=1, text="42"), TableCell(row=5, col=2, text="99")]
    out = PresidioEngine().anonymize(_table(cells), Language.tr)
    texts = _row_texts(out, row=5)
    assert texts == ["42", "99"]

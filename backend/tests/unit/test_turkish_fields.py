"""Labelled name fields, official address notation and the NER noise gates (2026-09-25).

Regression for a real e-Devlet residence certificate whose holder's name ("Adı : …" /
"Soyadı : …", in capitals) and address ("… MAH. … SK. NO: 123 NO: 45 İLÇE / İL") stayed unmasked.
Every value here is made up; the real document never enters the repository.
"""
from __future__ import annotations

import pytest

from app.anonymization.engine import Engine
from app.anonymization.gates import caps_line_ner, date_shaped_phone, form_label_ner
from app.anonymization.recognizers.turkish_fields import (
    official_address_recognizer,
    person_field_recognizer,
)
from app.anonymization.spans import EntitySpan
from app.extraction.base import Block, BlockType, ExtractedContent, TableCell
from app.models.document import FileKind, Language


def _tckn(nine: str) -> str:
    d = [int(c) for c in nine]
    d10 = ((d[0] + d[2] + d[4] + d[6] + d[8]) * 7 - (d[1] + d[3] + d[5] + d[7])) % 10
    return nine + str(d10) + str((sum(d) + d10) % 10)


FAKE_ID = _tckn("123456780")


def _residence_certificate() -> ExtractedContent:
    cells = [
        TableCell(row=0, col=0, text="KİMLİK BİLGİLERİ"),
        TableCell(row=1, col=0, text=f"Kimlik No : {FAKE_ID}\nAdı : AYŞE NUR\nSoyadı : YILDIRIM"),
        TableCell(row=2, col=0, text="Adres Tipi"), TableCell(row=2, col=1, text="Adres Türü"),
        TableCell(row=2, col=3, text="Adres"),
        TableCell(row=3, col=0, text="Yerleşim Yeri\nAdresi"),
        TableCell(row=3, col=1, text="Yurtiçi"),
        TableCell(row=3, col=3, text="DENEME MAH. ÖRNEK SK. NO: 123\nNO: 45 ÖRNEKİLÇE / ÖRNEKİL"),
    ]
    return ExtractedContent(kind=FileKind.pdf, blocks=[
        Block(block_id="t1", type=BlockType.table, text="", cells=cells),
        # Both dates are ones Presidio's phone parser accepts, so the date gate is exercised.
        Block(block_id="p1", text="İŞBU BELGE, www.turkiye.gov.tr ADRESİNDEN 03.01.2026 TARİHİNDE "
                                  "ALINMIŞ OLUP, 02.02.2026 TARİHİNE KADAR GEÇERLİDİR."),
    ])


@pytest.fixture(scope="module")
def masked() -> dict[str, str]:
    out = Engine().anonymize(_residence_certificate(), Language.mixed)
    cells = {f"r{c.row}c{c.col}": c.text for b in out.content.blocks for c in b.cells}
    cells["p1"] = next(b.text for b in out.content.blocks if b.block_id == "p1")
    return cells


def test_labelled_name_in_capitals_is_masked_and_the_label_stays(masked) -> None:
    identity = masked["r1c0"]
    for value in ("AYŞE", "NUR", "YILDIRIM", FAKE_ID):
        assert value not in identity
    assert identity.startswith("Kimlik No : <TCKN_1>\nAdı : <PERSON_")
    assert "\nSoyadı : <PERSON_" in identity


def test_official_address_notation_is_masked_whole(masked) -> None:
    address = masked["r3c3"]
    for value in ("DENEME", "ÖRNEK", "123", "ÖRNEKİLÇE"):
        assert value not in address
    assert address.startswith("<LOCATION_")


def test_form_captions_and_capitalised_legal_text_stay_readable(masked) -> None:
    assert masked["r2c0"] == "Adres Tipi" and masked["r2c1"] == "Adres Türü"
    assert masked["r3c0"] == "Yerleşim Yeri\nAdresi"
    assert "İŞBU BELGE" in masked["p1"] and "ALINMIŞ OLUP" in masked["p1"]
    assert "<PHONE_" not in masked["p1"]  # dates are not phone numbers


@pytest.mark.parametrize("address", [
    "DENEME MAH. ÖRNEK SK. NO: 123 / NO: 45 ÖRNEKİLÇE / ÖRNEKİL",  # the e-Devlet slash form
    "DENEME MAH. ÖRNEK SK. NO: 123/ NO: 45 ÖRNEKİLÇE / ÖRNEKİL",
    "DENEME MAH. ÖRNEK SK. NO: 123 /\nNO: 45 ÖRNEKİLÇE / ÖRNEKİL",
    "DENEME MAH. ÖRNEK SK. NO: 123\nNO: 45 ÖRNEKİLÇE / ÖRNEKİL",
    "DENEME MAH. ÖRNEK SK. NO: 12/3 ÖRNEKİLÇE / ÖRNEKİL",
    "DENEME MAH. ÖRNEK SK. DIŞ KAPI NO: 123 İÇ KAPI NO: 45 ÖRNEKİLÇE / ÖRNEKİL",
    "Deneme Mah. Örnek Sk. Dış Kapı No: 123 İç Kapı No: 45 Örnekilçe / Örnekil",
])
def test_official_address_forms_match_whole(address) -> None:
    found = [address[r.start:r.end] for r in official_address_recognizer().analyze(
        address, ["TR_ADDRESS"])]
    assert found == [address]


def test_slash_form_leaves_no_unit_district_or_city() -> None:
    content = ExtractedContent(kind=FileKind.pdf, blocks=[Block(
        block_id="p1", text="Adres: DENEME MAH. ÖRNEK SK. NO: 123 / NO: 45 ÖRNEKİLÇE / ÖRNEKİL")])
    text = Engine().anonymize(content, Language.mixed).content.blocks[0].text
    for value in ("DENEME", "123", "45", "ÖRNEKİLÇE", "ÖRNEKİL"):
        assert value not in text
    assert text.startswith("Adres: <LOCATION_")


@pytest.mark.parametrize("text", ["Şirket Adı : KUZEY ENERJİ A.Ş.", "Adı: ", "Ürün Adı : Kalem",
                                  "Adı : 12345"])
def test_person_field_needs_a_name_label_at_line_start(text) -> None:
    results = person_field_recognizer().analyze(text, ["TR_PERSON_CTX"])
    assert not results


def test_person_field_span_is_only_the_value() -> None:
    text = "Kimlik No : 1\nAdı Soyadı : Ayşe Nur Yıldırım\nBaba Adı : VELİ"
    found = sorted(text[r.start:r.end] for r in person_field_recognizer().analyze(
        text, ["TR_PERSON_CTX"]))
    assert found == ["Ayşe Nur Yıldırım", "VELİ"]


def _span(text: str, surface: str, entity_type: str, source: str = "tr") -> EntitySpan:
    start = text.index(surface)
    return EntitySpan(start=start, end=start + len(surface), entity_type=entity_type,
                      source=source)


def test_gates() -> None:
    line = "BU BELGE 5490 SAYILI NÜFUS HİZMETLERİ KANUNUNUN FIKRASI KAPSAMINDA VERİLMEKTEDİR."
    assert caps_line_ner(_span(line, "FIKRASI", "LOCATION"), line)
    assert not caps_line_ner(_span(line, "FIKRASI", "TR_ADDRESS"), line)  # structural: kept
    mixed = "Toplantıya Ayşe Kaya katıldı ve raporu onayladı."
    assert not caps_line_ner(_span(mixed, "Ayşe Kaya", "PERSON"), mixed)
    assert form_label_ner(_span("Adres Tipi", "Adres Tipi", "PERSON"), "Adres Tipi")
    assert date_shaped_phone(_span("03.01.2026", "03.01.2026", "PHONE_NUMBER"), "03.01.2026")
    assert not date_shaped_phone(_span("0532 764 21 09", "0532 764 21 09", "TR_GSM"),
                                 "0532 764 21 09")

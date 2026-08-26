"""Deney v5 iter 1-2: satır-kaydırma tespiti + varyant yayılımı regresyonları.

İkisi de GoldBench stres testinin son iki kritik yanlış onayını kapatır (ölçüldü):
  - `pdf-split_run_pii-07`: PDF çıkarımı bir URL'yi TEK blok içinde '\\n' ile bölüyor; boşluk-
    toleranssız desenler '\\n' üzerinden eşleşemiyordu.
  - `pdf-format_variants-06`: aynı adresin boşluksuz/BÜYÜK-ASCII-I'lı/birleştirici-noktalı
    yazımları regex kelime-sınırı varsayımını kırıyordu.
"""
from __future__ import annotations

from app.anonymization.presidio_engine import PresidioEngine, _norm_projection
from app.extraction.base import Block, BlockType, ExtractedContent
from app.models.document import FileKind, Language


def _mask(texts: list[str]) -> str:
    content = ExtractedContent(kind=FileKind.pdf, blocks=[
        Block(block_id=str(i), type=BlockType.paragraph, text=t, page=1)
        for i, t in enumerate(texts)])
    return PresidioEngine().anonymize(content, Language.tr).content.plain_text


# --- 1) Satır-kaydırma ('\n' blok İÇİNDE) ---

def test_url_wrapped_across_newline_is_masked():
    out = _mask(["link bilgisi: https://portal.ornek.c\nom/r?token=aZ39Kp7Qw12M"])
    assert "portal.ornek" not in out
    assert "token=aZ39Kp7Qw12M" not in out
    assert "<URL_" in out


def test_sentence_boundary_newline_does_not_create_cross_line_span():
    """Cümle sonu '\\n'ı (öncesinde noktalama) satır-KAYDIRMA değildir; daraltılmış görünümün
    "açıklama.İkinci" gibi sahte birleşik token'lardan URL üretmesi ölçülen bir hataydı
    (noktalama korkuluğuyla kapatıldı). Bu test yalnız İLGİLİ iddiayı sınar: hiçbir span '\\n'
    üzerinden geçmemeli. (Tek kelimelik NER yanlış pozitifleri — "Birinci"→PERSON — bu dosyanın
    konusu değil, önceden var olan ayrı bir sınır; bkz. CALIBRATION.md.)"""
    from app.anonymization.presidio_engine import PresidioEngine
    t = "Birinci satır açıklama.\nİkinci satır devam ediyor."
    for s in PresidioEngine().detect(t):
        assert "\n" not in t[s.start:s.end], \
            f"cümle sınırı üzerinden sahte span: {t[s.start:s.end]!r}"


# --- 2) Varyant yayılımı ---

def test_nospace_and_case_variants_of_masked_address_are_masked():
    out = _mask([
        "adres: Bağdat Caddesi No 145 Kadıköy İstanbul",
        "adres: BağdatCaddesiNo145Kadıköyİstanbul",
        "adres: BAĞDAT CADDESI NO 145 KADIKÖY İSTANBUL",   # ASCII I — Türkçe I/ı tuzağı
    ])
    assert "Bağdat" not in out and "BAĞDAT" not in out
    assert "Kadıköy" not in out and "KADIKÖY" not in out


def test_propagation_is_limited_to_deterministic_types():
    """ÖLÇÜLEN GERİLEMENİN regresyonu: NER'in tek seferlik yanlış pozitifi ("SÖZLEŞME" başlığı →
    LOCATION) yayılım yüzünden belgedeki her "sözleşme" kelimesine bulaşmıştı
    (test_destructive_mode_never_persists_layers_1_2 yakaladı). İstatistiksel NER yüzeyleri
    yayılMAZ — küçük harfli sıradan geçişler dokunulmadan kalmalı."""
    out = _mask([
        "SÖZLEŞMESİ BELGESİ",                            # NER bunu LOCATION/PERSON sanabilir
        "Bu sözleşmesi belgesi hükümlerine tabidir.",     # eş-yazım, PII DEĞİL
    ])
    assert "sözleşmesi belgesi hükümlerine tabidir" in out


def test_norm_projection_folds_turkish_i_family_and_whitespace():
    p1, _ = _norm_projection("Kadıköy İstanbul")
    p2, _ = _norm_projection("KADIKOY ISTANBUL")
    p3, _ = _norm_projection("kadıköyistanbul")
    # aksanlar ayrıştırılır (ö→o), i-ailesi katlanır, boşluk atılır → hepsi aynı izdüşüm
    assert p1 == p2 == p3 == "kadikoyistanbul"

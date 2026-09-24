"""Deney döngüsü 3: ortografik kapı + telefon "+" öneki (kısmi span) regresyonları.

İkisi de ÖLÇÜMLE bulundu (`scripts/measure_canary.py`), varsayımla değil:

1. `xx_ent_wiki_sm` Türkçe'de sıradan fiil/isim öbeklerini PERSON sanıyordu ("hükümleri saklıdır",
   "mutabık kalınarak"). Türkçede özel isim istisnasız büyük harfle başlar → küçük harfle başlayan
   bir istatistiksel-NER span'i yanlış pozitiftir.
2. `\b` boşluk ile "+" arasında eşleşmediği için telefon desenleri "+"ı span dışında bırakıyordu
   ("+44 7911 123456" → yalnız "44 7911 123456" maskeleniyor, "+" açıkta kalıyordu).
"""
from __future__ import annotations

import pytest

from app.anonymization.presidio_engine import PresidioEngine


def _types(text: str) -> list[tuple[str, str]]:
    return [(s.entity_type, text[s.start:s.end]) for s in PresidioEngine().detect(text)]


# --- 1) Ortografik kapı ---

@pytest.mark.parametrize("sentence", [
    "Ödeme planı taraflarca mutabık kalınarak belirlenmiştir.",
    "Söz konusu işlemde Vergi Usul Kanunu hükümleri saklıdır.",
    "Görev süresi üç yıldır ve yeniden seçilmek mümkündür.",
])
def test_lowercase_phrases_are_not_flagged_as_person(sentence):
    """Küçük harfle başlayan hiçbir öbek PERSON/LOCATION/ORG olarak işaretlenmemeli."""
    for entity_type, surface in _types(sentence):
        if entity_type in ("PERSON", "LOCATION", "ORGANIZATION", "NRP"):
            assert surface.lstrip()[:1].isupper(), \
                f"küçük harfle başlayan {entity_type} yanlış pozitifi: {surface!r}"


def test_real_capitalised_name_still_detected():
    """Kapı yalnız küçük harfe bakar — gerçek bir ad ETKİLENMEMELİ (yanlış negatif üretmemeli).
    Tip PERSON ya da TR_PERSON_CTX olabilir (Deney v5: "Sayın" gibi etiketli adlar artık
    etiket-bağlamlı tanıyıcıdan geliyor; ikisi de <PERSON_n> ailesine katlanır)."""
    assert any(t in ("PERSON", "TR_PERSON_CTX")
               for t, _ in _types("Sayın Kemal Vardar toplantıya katıldı."))


def test_gate_does_not_touch_structural_types():
    """Yapısal tanıyıcılar küçük harfle başlayabilir (e-posta, secret) — kapı onları elememeli."""
    found = _types("İletişim: kemal.vardar@ornekposta.com adresinden sağlanır.")
    assert any(t == "EMAIL_ADDRESS" for t, _ in found)


# --- 2) Telefon "+" öneki (kısmi span) ---

@pytest.mark.parametrize("text,value", [
    ("phone +44 7911 123456", "+44 7911 123456"),
    ("cep +90 532 764 21 09", "+90 532 764 21 09"),
])
def test_international_prefix_is_inside_the_span(text, value):
    """"+" span'in İÇİNDE olmalı — dışarıda kalırsa maskeleme sonrası metinde yalnız "+" kalır."""
    start = text.find(value)
    spans = PresidioEngine().detect(text)
    assert any(s.start <= start and s.end >= start + len(value) for s in spans), \
        f"{value!r} tam kapsanmadı: {[(s.entity_type, text[s.start:s.end]) for s in spans]}"


def test_local_format_without_prefix_still_matches():
    """Önek YOKKEN de eşleşme bozulmamalı (lookbehind bir regresyon getirmemiş olmalı)."""
    text = "cep 0532 764 21 09"
    start = text.find("0532")
    spans = PresidioEngine().detect(text)
    assert any(s.start <= start and s.end >= len(text) - 1 for s in spans)


def test_person_span_crossing_a_line_break_is_rejected():
    """Slayt/tablo bloklarında blok metni AYRI görsel öğeleri alt alta birleştiriyor; spaCy bunu
    tek bir PERSON sanıyor. Gerçek belgede ölçülen yanlış pozitifler:
    'Abone Kazanımı\\nMobilde', 'Toplam Abone Sayısı\\nSatış Gelirleri', 'Ae Wh\\nSon'."""
    from app.anonymization.engine import EntitySpan
    from app.anonymization.presidio_engine import _is_implausible_person_ner

    text = "Toplam Abone Sayısı\nSatış Gelirleri"
    span = EntitySpan(entity_type="PERSON", start=0, end=len(text), score=0.85, source="tr")
    assert _is_implausible_person_ner(span, text) is True


def test_two_word_person_wrapped_across_lines_survives():
    """Satır sonunda BÖLÜNMÜŞ gerçek bir ad iki kelimedir ve korunmalı — PERSON yayılım/
    bitişiklik mekanizmalarının kapsamında değil, elenirse doğrudan recall kaybı olur."""
    from app.anonymization.engine import EntitySpan
    from app.anonymization.presidio_engine import _is_implausible_person_ner

    text = "Selin\nÖzdemir"
    span = EntitySpan(entity_type="PERSON", start=0, end=len(text), score=0.85, source="tr")
    assert _is_implausible_person_ner(span, text) is False


def test_wrapped_location_is_not_rejected_addresses_depend_on_it():
    """Kural BİLİNÇLİ olarak LOCATION'a uygulanmaz: Türkçe adresler uzun, çok kelimeli ve
    PDF'te düzenli olarak satıra bölünür; özel bir adres tanıyıcısı yok. LOCATION'a da
    uygulandığında holdout'ta 2 KRİTİK adres kaybedildi (kritik recall 1.0000 → 0.9985)."""
    from app.anonymization.engine import EntitySpan
    from app.anonymization.presidio_engine import _is_implausible_person_ner

    text = "Bağdat Caddesi No 145\nKadıköy İstanbul"
    span = EntitySpan(entity_type="LOCATION", start=0, end=len(text), score=0.85, source="tr")
    assert _is_implausible_person_ner(span, text) is False

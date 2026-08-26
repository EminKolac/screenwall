"""Deney döngüsü Faz 2'de eklenen tanıyıcılar (SALARY, COMPANY, ADDRESS, DISABILITY, HEALTH).

En kritik test `test_company_pattern_does_not_bleed_into_preceding_lowercase_words`: iterasyon
2'de bulunan gerçek hatanın (Presidio PatternRecognizer varsayılan re.IGNORECASE içerir, büyük/
küçük harf ayrımına dayanan desenleri anlamsızlaştırır) regresyonudur.
"""
from __future__ import annotations

from app.anonymization.allowlist_tr import default_allow_list
from app.anonymization.presidio_engine import PresidioEngine
from app.extraction.base import Block, BlockType, ExtractedContent
from app.models.document import FileKind, Language


def _content(text: str) -> ExtractedContent:
    return ExtractedContent(kind=FileKind.docx,
                            blocks=[Block(block_id="0", type=BlockType.paragraph, text=text)])


def _mask(text: str, *, with_allow_list: bool = False) -> str:
    """`PresidioEngine.anonymize()` allow-list'i KENDİSİ uygulamaz — onu enjekte eden
    `run_pipeline` (bkz. `app/pipeline/runner.py`). Aşırı-maskeleme testleri gerçek pipeline
    davranışını yansıtsın diye `with_allow_list=True` ister."""
    allow = default_allow_list() if with_allow_list else None
    return PresidioEngine().anonymize(
        _content(text), Language.tr, extra_allow_terms=allow).content.plain_text


# --- SALARY ---

def test_salary_range_is_masked_with_context():
    out = _mask("Maaş bandı 60.000-85.000 TL olarak belirlenmiştir.")
    assert "60.000-85.000 TL" not in out


def test_salary_floor_is_masked():
    out = _mask("Ücret 120.000 TL üzeri bir bantta değerlendirilir.")
    assert "120.000 TL üzeri" not in out


def test_single_amount_is_not_caught_by_salary_pattern():
    """Tekil bir tutar (aralık değil, "üzeri" de yok) SALARY deseniyle çakışmamalı."""
    out = _mask("Sözleşme Bedeli 480.000 TL olarak belirlenmiştir.")
    assert "480.000 TL" in out


# --- COMPANY ---

def test_company_with_as_suffix_is_masked_fully():
    out = _mask("İşveren Anadolu Metal Sanayi A.Ş. olarak kayıtlıdır.")
    assert "Anadolu Metal Sanayi A.Ş." not in out


def test_company_with_ltd_sti_suffix_is_masked_fully():
    out = _mask("İşyeri: Kuzey İnşaat Taahhüt Ltd. Şti.")
    assert "Kuzey İnşaat Taahhüt Ltd. Şti." not in out


def test_company_pattern_does_not_bleed_into_preceding_lowercase_words():
    """REGRESYON (iterasyon 2 hatası): Presidio'nun varsayılan re.IGNORECASE'i büyük/küçük harf
    sinyalini anlamsızlaştırıyordu — "Sözleşme bedeli hakkında Anadolu Metal Sanayi A.Ş." gibi
    span'lerde önceki cümlenin küçük harfli kelimeleri de yutuluyordu."""
    out = _mask("Sözleşme bedeli hakkında Anadolu Metal Sanayi A.Ş. ile görüşüldü.")
    assert "Sözleşme bedeli hakkında" in out
    assert "Anadolu Metal Sanayi A.Ş." not in out


# --- ADDRESS ---

def test_address_pattern_is_masked_with_context():
    out = _mask("Adres: Atatürk Bulvarı No 207 Keçiören Ankara.")
    assert "Atatürk Bulvarı No 207 Keçiören Ankara" not in out


def test_address_pattern_does_not_bleed_into_preceding_sentence():
    out = _mask("Toplantı yapıldı. Adres: Atatürk Bulvarı No 207 Keçiören Ankara şeklindedir.")
    assert "Toplantı yapıldı" in out


# --- DISABILITY ---

def test_disability_percentage_kayip_form_is_masked():
    out = _mask("Engel durumu: %40 işitme kaybı olarak bildirilmiştir.")
    assert "%40 işitme kaybı" not in out


def test_disability_engel_parenthetical_form_is_masked():
    out = _mask("Rapor: ortopedik engel (%30) olarak değerlendirilmiştir.")
    assert "ortopedik engel (%30)" not in out


# --- HEALTH ---

def test_known_health_term_is_masked():
    out = _mask("Tanı: tip 2 diyabet olarak konulmuştur.")
    assert "tip 2 diyabet" not in out


def test_health_term_list_covers_more_than_goldbench_examples():
    """Sözlük yalnız GoldBench'in 7 örneğine değil, gerçek dünyada yaygın terimlere de
    genellenmeli — aksi halde bu benchmark'a özel bir kısayol olurdu."""
    from app.anonymization.recognizers.turkish import _HEALTH_TERMS
    goldbench_terms = {"tip 2 diyabet", "hipertansiyon", "astım", "bel fıtığı", "migren",
                       "romatoid artrit", "tiroid rahatsızlığı"}
    assert len(set(_HEALTH_TERMS) - goldbench_terms) >= 10


def test_unlisted_rare_diagnosis_is_not_caught_by_health_recognizer():
    """Dürüstlük testi: sözlükte olmayan nadir bir tanı TR_HEALTH tarafından YAKALANMAZ — bu,
    HEALTH'in bilinen sınırıdır (Privacy Filter'ın kapatacağı boşluk), sessizce başarılı gibi
    davranmamalı. (Metnin bütünüyle maskelenmeden kalması İDDİA EDİLMİYOR — önceden var olan
    LOCATION NER, alakasız yabancı-görünümlü özel adları kendi başına yakalayabilir; test yalnız
    TR_HEALTH'in span üretmediğini doğrular.)"""
    spans = PresidioEngine().detect("Tanı: Ehlers-Danlos sendromu olarak konulmuştur.")
    assert not any(s.entity_type == "TR_HEALTH" for s in spans)


# --- Genel regresyon: aşırı-maskeleme yeni tanıyıcılarla geri gelmemeli ---

def test_new_recognizers_do_not_reintroduce_over_masking():
    """Allow-list'in kendisi `run_pipeline` tarafından enjekte edilir (bkz. `_mask` docstring'i);
    burada gerçek üretim yoluyla eşleşecek şekilde açıkça geçiriliyor."""
    out = _mask("Genel Kurul toplantısında Sözleşme Bedeli görüşüldü.", with_allow_list=True)
    assert "Genel Kurul" in out
    assert "Sözleşme Bedeli" in out

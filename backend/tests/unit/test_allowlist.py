"""Allow-list — GoldBench'in %100 aşırı-maskeleme bulgusuna karşı ana savunmanın regresyon testi.

En kritik test `test_allowlist_does_not_shadow_real_pii_via_overlap`: allow-listenin
`resolve_spans`'ten SONRA değil ÖNCE uygulandığını kanıtlar — sonra uygulansaydı, allow'lanan bir
span'in çakışma nedeniyle bastırdığı gerçek bir PII span'i asla geri gelmezdi.
"""
from __future__ import annotations

from app.anonymization.allowlist_tr import TR_ALLOWLIST, default_allow_list
from app.anonymization.presidio_engine import PresidioEngine
from app.extraction.base import Block, BlockType, ExtractedContent
from app.models.document import FileKind, Language


def _content(text: str) -> ExtractedContent:
    return ExtractedContent(kind=FileKind.docx,
                            blocks=[Block(block_id="0", type=BlockType.paragraph, text=text)])


def test_default_allow_list_is_sorted_and_deduped():
    lst = default_allow_list()
    assert lst == sorted(set(lst))
    assert len(lst) == len(TR_ALLOWLIST)


def test_allow_term_suppresses_exact_match():
    out = PresidioEngine().anonymize(
        _content("Genel Kurul toplantısı yapılacaktır."), Language.tr,
        extra_allow_terms=["Genel Kurul"])
    assert "Genel Kurul" in out.content.plain_text
    assert "<" not in out.content.plain_text.split("toplantısı")[0]


def test_allow_term_is_case_and_whitespace_flexible():
    """deny-list ile AYNI kural: büyük/küçük harf ve fazla boşluk fark etmez."""
    out = PresidioEngine().anonymize(
        _content("GENEL  KURUL toplantısı yapılacaktır."), Language.tr,
        extra_allow_terms=["Genel Kurul"])
    assert "<" not in out.content.plain_text.split("toplantısı")[0]


def test_allow_list_does_not_affect_unlisted_pii():
    """Allow-list yalnız listedeki terimleri bastırır — gerçek PII'ye dokunmaz."""
    out = PresidioEngine().anonymize(
        _content("Ahmet Yılmaz, TC Kimlik No 10203040550."), Language.tr,
        extra_allow_terms=["Genel Kurul"])
    assert "Ahmet Yılmaz" not in out.content.plain_text
    assert "10203040550" not in out.content.plain_text


def test_allowlist_does_not_shadow_real_pii_via_overlap():
    """`resolve_spans`'ten ÖNCE filtreleme regresyonu: allow'lanan bir span, çakıştığı için
    bastırdığı gerçek bir PII span'ini SONRADAN kilitlememeli.

    "Fatura Dönemi 1234567890" — allow-terimi "Fatura Dönemi" NER tarafından muhtemelen daha uzun
    bir span olarak (örn. tarih/ifade) yakalanabilir; asıl garanti edilecek şey, hemen yanındaki
    gerçek bir kimlik numarasının (VKN-benzeri) allow filtrelemesinden ETKİLENMEMESİdir.
    """
    out = PresidioEngine().anonymize(
        _content("Fatura Dönemi: Vergi no 1234567890 olarak bildirilmiştir."), Language.tr,
        extra_allow_terms=["Fatura Dönemi"])
    text = out.content.plain_text
    assert "Fatura Dönemi" in text
    assert "1234567890" not in text  # VKN hâlâ maskelenmeli


def test_no_allow_terms_is_a_noop():
    out = PresidioEngine().anonymize(
        _content("Genel Kurul toplantısı yapılacaktır."), Language.tr, extra_allow_terms=[])
    assert "Genel Kurul" not in out.content.plain_text  # allow-list boşsa eski davranış korunur


def test_allow_list_is_reusable_via_detect_for_eval_harness():
    """`detect()` (eval yolu) `anonymize()` (üretim yolu) ile AYNI allow davranışını vermeli —
    ikisi aynı `_detect`'i paylaşıyor, sürüklenmemeli."""
    spans = PresidioEngine().detect("Genel Kurul toplantısı yapılacaktır.",
                                    extra_allow_terms=["Genel Kurul"])
    assert not any(s.entity_type in ("ORGANIZATION", "LOCATION", "NRP") for s in spans
                  if 0 <= s.start < len("Genel Kurul"))


# -------------------------------------------------- Settings.term_lists: all lists at once

def _user_lists(root) -> None:
    import json

    (root / "user_settings.json").write_text(
        json.dumps({"never_mask": ["Genel Kurul"], "always_mask": ["Gizli Fon"]}), "utf-8")


def test_term_lists_on_assembles_every_list(tmp_path, monkeypatch):
    from app.config import Settings
    from app.pipeline.terms import effective_terms

    monkeypatch.setenv("ALLOW_TERMS", "Proje Adı")
    monkeypatch.setenv("DENY_TERMS", "e2vc")
    _user_lists(tmp_path)
    deny, allow = effective_terms(Settings(storage_root=tmp_path))
    assert deny == ["e2vc", "Gizli Fon"]
    assert set(default_allow_list()) | {"Proje Adı", "Genel Kurul"} == set(allow)


def test_term_lists_off_turns_every_list_off_without_reading_user_settings(tmp_path,
                                                                            monkeypatch):
    import pytest

    import app.pipeline.terms as terms
    from app.config import Settings

    monkeypatch.setenv("ALLOW_TERMS", "Proje Adı")
    monkeypatch.setenv("DENY_TERMS", "e2vc")
    _user_lists(tmp_path)
    monkeypatch.setattr(terms, "load_user_settings",
                        lambda s: pytest.fail("user_settings.json must not be read"))
    assert terms.effective_terms(Settings(storage_root=tmp_path, term_lists=False)) == ([], [])
    monkeypatch.setenv("TERM_LISTS", "false")
    assert Settings().term_lists is False  # the env switch

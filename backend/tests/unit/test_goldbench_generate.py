"""GoldBench korpus üretimi — determinizm, cevap anahtarı tutarlılığı, şema geçerliliği.

En kritik test `test_content_sha_is_deterministic`: cevap anahtarı yeniden üretilemezse benchmark'ın
tamamı geçersizdir (ikinci bir ekip aynı korpusu kurduğunu doğrulayamaz).
"""
from __future__ import annotations

import hashlib
import json

import pytest

from evaluation.corpus_bist10.emit_carriers import emit
from evaluation.goldbench.generate import DOMAIN_ORDER, build_document
from evaluation.goldbench.schema import IdentifierClass, locate


def _doc(doc_id="hr-000", domain="hr", index=0, seed=20260812, split="dev", gi=0):
    return build_document(doc_id, domain, index, seed, split, global_index=gi)


def _content_sha(gdoc) -> str:
    payload = gdoc.text + "␟" + json.dumps(
        [m.to_gold_dict() for m in gdoc.mentions], ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def test_content_sha_is_deterministic():
    """Aynı seed → aynı metin + aynı cevap anahtarı. Benchmark'ın temel sözü budur."""
    a, _ = _doc()
    b, _ = _doc()
    assert _content_sha(a) == _content_sha(b)
    assert a.text == b.text
    assert len(a.mentions) == len(b.mentions)


def test_different_seed_gives_different_corpus():
    """Holdout ayrı seed'den üretilir — seed gerçekten farklı korpus vermiyorsa holdout'un
    ayrılığı sahte olur ve dev üstünde ayarlanan eşikler holdout'a sızar."""
    a, _ = _doc(seed=20260812)
    b, _ = _doc(seed=20260812 + 900_000)
    assert a.text != b.text


@pytest.mark.parametrize("domain", DOMAIN_ORDER)
def test_every_domain_builds_and_all_mentions_locatable(domain):
    """Her mention üretilen metinde BULUNABİLİR olmalı. Bulunamayan bir mention, skorlamada
    sessizce 'kaçırıldı' sayılır ve recall'u haksız yere düşürür — cevap anahtarı hatası
    sistemin hatası gibi görünür."""
    gdoc, _ = _doc(f"{domain}-000", domain, 0)
    assert gdoc.mentions, f"{domain}: hiç mention üretilmedi"
    for m in gdoc.mentions:
        assert locate(gdoc.text, m.surface, m.occurrence) is not None, (
            f"{domain}: '{m.surface[:20]}' (occ {m.occurrence}) metinde bulunamadı")


@pytest.mark.parametrize("domain", DOMAIN_ORDER)
def test_every_domain_has_required_annotation_mix(domain):
    """Plan gereği her belge: ≥2 veri sahibi, ≥3 PII türü, ≥1 tekrarlanan entity,
    ≥1 NO_MASK kontrolü. Sonuncusu olmadan aşırı-maskeleme ölçülemez."""
    gdoc, _ = _doc(f"{domain}-000", domain, 0)
    assert len(gdoc.subjects) >= 2
    types = {m.entity_type for m in gdoc.mentions}
    assert len(types) >= 3, f"{domain}: sadece {types}"

    counts: dict[str, int] = {}
    for m in gdoc.mentions:
        counts[m.entity_id] = counts.get(m.entity_id, 0) + 1
    assert any(v > 1 for v in counts.values()), f"{domain}: tekrarlanan entity yok"

    klasses = {m.identifier_class for m in gdoc.mentions}
    assert IdentifierClass.NO_MASK in klasses, f"{domain}: NO_MASK negatif kontrolü yok"
    assert IdentifierClass.DIRECT in klasses


def test_quasi_and_sensitive_coverage_exists_somewhere():
    """QUASI, KVKK m.3'ün 'başka verilerle eşleştirilerek dahi' ibaresinin konusu; SENSITIVE ise
    m.6 özel nitelikli veri. İkisi de korpusta yoksa o iddialar ölçülemez."""
    seen: set[IdentifierClass] = set()
    for i, domain in enumerate(DOMAIN_ORDER):
        gdoc, _ = _doc(f"{domain}-000", domain, 0, gi=i)
        seen |= {m.identifier_class for m in gdoc.mentions}
    assert IdentifierClass.QUASI in seen
    assert IdentifierClass.SENSITIVE_ATTRIBUTE in seen


def test_ooxml_carriers_are_byte_deterministic():
    """DOCX/XLSX byte determinizmi — emit_carriers'daki normalleştirmenin regresyon testi.
    Ham python-docx/openpyxl çıktısı ZIP girdi tarihlerine üretim anını yazar ve bu test kırılır.
    """
    _, content = _doc()
    for fmt in ("docx", "xlsx"):
        assert emit(content, fmt) == emit(content, fmt), f"{fmt} deterministik değil"


def test_carriers_roundtrip_through_the_apps_own_extractor():
    """Taşıyıcılar, ürünün KENDİ çıkarıcısıyla okunabilmeli — okunamayan bir taşıyıcı korpusu
    sessizce boşaltır ve recall'u ölçülemez kılar."""
    from app.extraction.dispatcher import extract

    gdoc, content = _doc()
    for fmt in ("pdf", "docx", "xlsx"):
        _, ex = extract(emit(content, fmt), f"x.{fmt}", 20 * 1024 * 1024)
        assert ex.plain_text.strip(), f"{fmt}: boş çıkarım"
        # En az bir DIRECT değer geri okunabilmeli (yoksa cevap anahtarı taşıyıcıda yok demektir)
        directs = [m for m in gdoc.mentions if m.identifier_class == IdentifierClass.DIRECT]
        assert any(locate(ex.plain_text, m.surface, 0) for m in directs), f"{fmt}: PII taşınmamış"

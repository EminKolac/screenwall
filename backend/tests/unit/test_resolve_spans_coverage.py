"""`resolve_spans` kapsama (containment) regresyonu — ölçümle bulunmuş bir GİZLİLİK hatası.

Hata: çakışan span'ler tamamen elendiği için, KISA ama yüksek skorlu bir tespit, KENDİSİNİ İÇEREN
uzun bir span'i bastırıyor ve geri kalanını AÇIKTA bırakıyordu. Somut ölçüm: 20 karakterlik tam
maskeli bir kişi adı, 0.99 skorlu 4 karakterlik bir parça eklenince 4 karaktere düşüyordu.

Pratik sonucu şuydu: YENİ BİR DEDEKTÖR EKLEMEK KAPSAMI DÜŞÜREBİLİYORDU — Privacy Filter açıkken
bağımsız TAB korpusunda doğrudan-tanımlayıcı recall 0.638 → 0.574'e geriledi. Bu testlerin asıl
işi, o "dedektör eklemek zarar veremez" değişmezini korumak.
"""
from __future__ import annotations

from app.anonymization.engine import EntitySpan, resolve_spans


def _covered(spans: list[EntitySpan]) -> set[int]:
    out: set[int] = set()
    for s in spans:
        out.update(range(s.start, s.end))
    return out


def test_short_high_score_span_does_not_shrink_the_span_containing_it():
    long_span = EntitySpan(start=0, end=20, entity_type="PERSON", score=0.85, source="en")
    short_span = EntitySpan(start=0, end=4, entity_type="PERSON", score=0.99,
                            source="privacy_filter")
    kept = resolve_spans([long_span, short_span])
    assert _covered(kept) >= _covered([long_span])


def test_adding_a_detector_never_reduces_masked_coverage():
    """Değişmez: ikinci bir dedektörün span'lerini EKLEMEK, maskelenen karakter kümesini
    KÜÇÜLTEMEZ. Bu, güvenlik öncelikli sistemde pazarlık edilmeyen taraftır."""
    base = [
        EntitySpan(start=10, end=30, entity_type="PERSON", score=0.85, source="en"),
        EntitySpan(start=50, end=70, entity_type="LOCATION", score=0.85, source="en"),
    ]
    extra = [
        EntitySpan(start=12, end=16, entity_type="PERSON", score=0.99, source="privacy_filter"),
        EntitySpan(start=55, end=60, entity_type="LOCATION", score=0.97, source="privacy_filter"),
    ]
    assert _covered(resolve_spans(base + extra)) >= _covered(resolve_spans(base))


def test_partial_overlap_semantics_are_unchanged():
    """KOŞULSUZ birleştirme BİLEREK yapılmadı: kısmi çakışmada da birleştirmek, yanlış pozitif
    bir NER span'inin gerçek bir IBAN'ın maskesini geriye doğru büyütmesine (aşırı-maskeleme)
    yol açıyordu. Kapsama olmayan çakışmalarda eski davranış korunmalı."""
    nrp = EntitySpan(start=0, end=19, entity_type="NRP", score=0.85, source="en")
    iban = EntitySpan(start=5, end=37, entity_type="IBAN_CODE", score=1.0, source="en")
    kept = resolve_spans([nrp, iban])
    winner = next(s for s in kept if s.entity_type == "IBAN_CODE")
    assert (winner.start, winner.end) == (5, 37)


def test_containment_keeps_the_more_trusted_label():
    """Genişleyen span'in ETİKETİ, öncelik sırasında kazanan (daha güvenilir) span'den gelmeli —
    yer tutucu ailesi kaymasın."""
    trusted_short = EntitySpan(start=4, end=8, entity_type="TR_IBAN", score=0.7, source="tr")
    ner_long = EntitySpan(start=0, end=20, entity_type="PERSON", score=0.85, source="en")
    kept = resolve_spans([trusted_short, ner_long])
    assert len(kept) == 1
    assert kept[0].entity_type == "TR_IBAN"      # güvenilir tür kazanır
    assert (kept[0].start, kept[0].end) == (0, 20)  # ama kapsam korunur


def test_disjoint_spans_are_never_merged():
    a = EntitySpan(start=0, end=5, entity_type="PERSON", score=0.9, source="en")
    b = EntitySpan(start=10, end=15, entity_type="EMAIL_ADDRESS", score=0.9, source="en")
    kept = resolve_spans([a, b])
    assert [(s.start, s.end) for s in kept] == [(0, 5), (10, 15)]

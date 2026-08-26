"""GoldBench skorlama testleri.

En önemlisi `test_partial_leak_is_invisible_to_exact_match_but_caught_by_char_metrics`:
mevcut BIST harness'ının kısmi sızıntıyı "başarı" saydığı gerçek hatayı fikstürleştirir.
"""
from __future__ import annotations

from evaluation.goldbench.schema import (
    Channel,
    Criticality,
    GoldMention,
    IdentifierClass,
    Necessity,
)
from evaluation.goldbench.score import (
    Span,
    aggregate,
    evaluate_document,
    redaction_coverage_score,
)


def _m(surface, mid="m1", eid="E1", sid="S1", etype="PHONE",
       klass=IdentifierClass.DIRECT, need=Necessity.MANDATORY,
       crit=Criticality.CRITICAL, occ=0, channel=Channel.BODY):
    return GoldMention(mention_id=mid, entity_id=eid, subject_id=sid, surface=surface,
                       occurrence=occ, entity_type=etype, identifier_class=klass,
                       necessity=need, criticality=crit, channel=channel)


def test_fully_detected_and_masked_value_scores_perfect():
    text = "Cep telefonu: 0532 764 21 09 numarasıdır."
    gold = [_m("0532 764 21 09")]
    det = [Span(14, 28, "TR_GSM")]
    res = evaluate_document(gold, text, det, "Cep telefonu: <PHONE_1> numarasıdır.")
    assert res[0].located and res[0].fully_detected
    assert res[0].masked and res[0].residual_chars == 0
    assert res[0].char_recall == 1.0


def test_partial_leak_is_invisible_to_exact_match_but_caught_by_char_metrics():
    """GERÇEK REGRESYON: "0532 764 21 09" → "<DATE_2> 764 <DATE_1>".

    Tam değer anonim metinde YOK, dolayısıyla eski `val not in anon_text` ölçütü bunu
    "maskelendi" sayar — ama "764" açıkta kalmıştır. Karakter metrikleri bunu görmeli.
    """
    text = "Cep telefonu: 0532 764 21 09 numarasıdır."
    gold = [_m("0532 764 21 09")]
    # Dedektör değerin sadece uçlarını yakaladı, ortadaki "764" kapsanmadı
    det = [Span(14, 18, "DATE_TIME"), Span(23, 28, "DATE_TIME")]
    anon = "Cep telefonu: <DATE_2> 764 <DATE_1> numarasıdır."

    res = evaluate_document(gold, text, det, anon)
    r = res[0]
    assert r.masked is True, "tam-değer ölçütü bunu başarı sayar — testin ön kabulü"
    assert r.fully_detected is False
    assert r.partially_detected is True
    assert r.residual_chars > 0, "kısmi sızıntı karakter olarak görünmeli"
    assert r.char_recall < 1.0

    agg = aggregate(res, detected_total_chars=9, gold_total_chars=14)
    assert agg["mention_recall"] == 1.0          # eski ölçüt: kusursuz görünür
    assert agg["partial_leaks"] == 1             # yeni ölçüt: sızıntıyı yakalar
    assert agg["char_recall"] < 1.0


def test_entity_recall_is_stricter_than_mention_recall():
    """Aynı kişi 2 kez geçiyor, biri maskelenmiş biri açık: mention %50, entity %0.
    Entity ölçütü olmadan 'yarısını gizledik' başarı gibi görünür."""
    text = "Ahmet Yılmaz geldi. Sonra Ahmet Yılmaz gitti."
    gold = [_m("Ahmet Yılmaz", mid="m1", eid="E1", etype="PERSON", occ=0),
            _m("Ahmet Yılmaz", mid="m2", eid="E1", etype="PERSON", occ=1)]
    det = [Span(0, 12, "PERSON")]
    anon = "<PERSON_1> geldi. Sonra Ahmet Yılmaz gitti."  # ikinci geçiş açıkta

    res = evaluate_document(gold, text, det, anon)
    agg = aggregate(res, detected_total_chars=12)
    # Değer metinde hâlâ göründüğü için ikisi de "maskelenmedi" sayılır (global yokluk ölçütü)
    assert agg["entity_recall"] == 0.0
    assert agg["entities_total"] == 1


def test_no_mask_violation_counts_as_over_masking_not_recall():
    """NO_MASK terimi maskelenirse bu bir recall başarısı değil, precision kaybıdır."""
    text = "Genel Kurul toplantısı yapıldı."
    gold = [_m("Genel Kurul", etype="NO_MASK", klass=IdentifierClass.NO_MASK,
               need=Necessity.CONTEXTUAL, crit=Criticality.LOW)]
    res = evaluate_document(gold, text, [Span(0, 11, "ORG")], "<ORG_1> toplantısı yapıldı.")
    agg = aggregate(res, detected_total_chars=11)
    assert agg["no_mask_violations"] == 1
    assert agg["over_masking_rate"] == 1.0
    assert agg["mentions_total"] == 0, "NO_MASK recall paydasına girmemeli"


def test_mask_everything_strategy_cannot_score_perfect():
    """'Her şeyi maskele' stratejisi recall'da 1.0 alır ama kapsama skoru NO_MASK cezasıyla
    düşer — bu ceza olmadan aşırı-maskeleme ödüllendirilirdi."""
    text = "Ahmet Yılmaz ve Genel Kurul."
    gold = [_m("Ahmet Yılmaz", mid="m1", eid="E1", etype="PERSON"),
            _m("Genel Kurul", mid="m2", eid="N1", etype="NO_MASK",
               klass=IdentifierClass.NO_MASK, need=Necessity.CONTEXTUAL, crit=Criticality.LOW)]
    det = [Span(0, 12, "PERSON"), Span(16, 27, "ORG")]
    res = evaluate_document(gold, text, det, "<PERSON_1> ve <ORG_1>.")
    assert aggregate(res, detected_total_chars=23)["mention_recall"] == 1.0
    assert redaction_coverage_score(res) < 1.0


def test_unlocated_mention_is_reported_not_silently_dropped():
    """Taşıyıcıya girmemiş bir gold değer, tespit hatası gibi sayılmamalı ama sayısı da
    kaybolmamalı — aksi halde korpus hatası sistemin hatası gibi görünür."""
    gold = [_m("0532 764 21 09")]
    res = evaluate_document(gold, "Bu metinde o değer yok.", [], "Bu metinde o değer yok.")
    assert res[0].located is False
    agg = aggregate(res)
    assert agg["not_located"] == 1
    assert agg["mentions_located"] == 0


def test_f2_weights_recall_more_than_f1():
    """Gizlilik önceliğinde recall daha ağır basmalı: recall > precision iken F2 > F1."""
    text = "Ahmet Yılmaz burada."
    gold = [_m("Ahmet Yılmaz", etype="PERSON")]
    res = evaluate_document(gold, text, [Span(0, 12, "PERSON")], "<PERSON_1> burada.")
    agg = aggregate(res, detected_total_chars=24)  # yarısı gold dışı → precision 0.5, recall 1.0
    assert agg["char_recall"] > agg["char_precision"]
    assert agg["f2"] > agg["f1"]


def test_export_leak_is_tracked_separately():
    """Layer-3'te maskelenip export'ta yeniden görünmek en ağır hatadır (shipped leakage)."""
    text = "IBAN TR84 0009 1000 8765 4321 0987 65 hesabı."
    gold = [_m("TR84 0009 1000 8765 4321 0987 65", etype="IBAN")]
    res = evaluate_document(gold, text, [Span(5, 37, "IBAN")],
                            "IBAN <IBAN_1> hesabı.",
                            export_text="IBAN TR84 0009 1000 8765 4321 0987 65 hesabı.")
    assert res[0].masked is True
    assert res[0].leaked_in_export is True
    assert aggregate(res, detected_total_chars=32)["leaked_in_export"] == 1


def test_breakdowns_split_direct_quasi_and_sensitive():
    """QUASI ve SENSITIVE ayrı raporlanmalı: KVKK m.3 'eşleştirilerek dahi' ibaresi QUASI'yi,
    m.6 ise SENSITIVE'i konu alır — tek bir toplam recall bu iddiaları ölçemez."""
    text = "Ahmet Yılmaz, makine mühendisi, tip 2 diyabet hastası."
    gold = [
        _m("Ahmet Yılmaz", mid="m1", eid="E1", etype="PERSON"),
        _m("makine mühendisi", mid="m2", eid="E2", etype="OCCUPATION",
           klass=IdentifierClass.QUASI, need=Necessity.CONTEXTUAL, crit=Criticality.MEDIUM),
        _m("tip 2 diyabet", mid="m3", eid="E3", etype="HEALTH",
           klass=IdentifierClass.SENSITIVE_ATTRIBUTE, crit=Criticality.CRITICAL),
    ]
    res = evaluate_document(gold, text, [Span(0, 12, "PERSON")],
                            "<PERSON_1>, makine mühendisi, tip 2 diyabet hastası.")
    agg = aggregate(res, detected_total_chars=12)
    by = agg["by_identifier_class"]
    assert by["DIRECT"]["mention_recall"] == 1.0
    assert by["QUASI"]["mention_recall"] == 0.0
    assert by["SENSITIVE_ATTRIBUTE"]["mention_recall"] == 0.0

"""Fayda ve saldırı seti testleri.

En kritik iki değişmez:
  - Fayda sorusunun kanıtı ASLA PII olmamalı (yoksa iyi karartıcı cezalandırılır)
  - Fayda paydası ORİJİNAL metinden gelmeli (soru sayısından değil)
"""
from __future__ import annotations

from evaluation.goldbench.attack import PROMPT_TEMPLATE, PROTOCOL, _options_for
from evaluation.goldbench.inference_set import (
    ATTACK_ATTRIBUTES,
    InferenceScenario,
    UtilityQuestion,
    _questions_for,
    build_candidate_pool,
    score_utility,
)


def _sc(evidences: list[str]) -> InferenceScenario:
    return InferenceScenario(
        scenario_id="sc-000", doc_id="d0", domain="legal", language="tr", subject_id="S0001",
        questions=[UtilityQuestion(qid=f"q{i}", question="?", evidence=e)
                   for i, e in enumerate(evidences)],
        attribute_truth={"occupation": "makine mühendisi"})


def test_utility_counts_evidence_that_survived_masking():
    sc = _sc(["480.000 TL", "30 Kasım 2026"])
    anon = "Sözleşme Bedeli: 480.000 TL. Teslim: <DATE_1>."
    r = score_utility(sc, anon)
    assert r["questions"] == 2
    assert r["answerable"] == 1        # tarih maskelenmiş, bedel duruyor
    assert r["answerable_rate"] == 0.5


def test_masking_the_evidence_destroys_utility():
    """Aşırı-maskelemenin faydaya maliyeti tam olarak budur."""
    sc = _sc(["480.000 TL"])
    assert score_utility(sc, "Sözleşme Bedeli: <MONEY_1>.")["answerable"] == 0


def test_utility_is_whitespace_flexible():
    """Taşıyıcı round-trip'i kanıtı satır sonuna bölebilir; bu bir fayda kaybı DEĞİLDİR."""
    sc = _sc(["üç eşit taksit"])
    assert score_utility(sc, "Ödeme:\nüç   eşit\ntaksit olarak.")["answerable"] == 1


def test_questions_without_evidence_in_text_are_dropped():
    """Kanıtı belgede olmayan soru sistemin hatası değil — paydayı şişirip skoru düşürürdü."""
    qs = _questions_for("legal", "d0", "Bu metinde şablon kanıtlarının hiçbiri yok.")
    assert qs == []


def test_only_templated_questions_whose_evidence_exists_are_kept():
    text = "Madde 1 — Sözleşme Bedeli: 480.000 TL + KDV. Ödeme: üç eşit taksit."
    qs = _questions_for("legal", "d0", text)
    kept = {q.evidence for q in qs}
    assert "480.000 TL" in kept
    assert "üç eşit taksit" in kept
    assert "30 Kasım 2026" not in kept  # metinde yok → düşürüldü


def test_no_utility_question_uses_pii_as_evidence():
    """SÖZLEŞMENİN KENDİSİ: kanıt PII olursa, PII'yi doğru şekilde yok eden sistem fayda
    kaybetmiş gibi görünür — yani doğru davranış cezalandırılır."""
    from evaluation.goldbench.inference_set import _QUESTION_TEMPLATES

    for domain, pairs in _QUESTION_TEMPLATES.items():
        for _q, ev in pairs:
            assert not any(ch.isdigit() and len(ev) == 11 for ch in ev), f"{domain}: TCKN benzeri"
            assert "@" not in ev, f"{domain}: e-posta kanıt olamaz"
            assert not ev.upper().startswith("TR"), f"{domain}: IBAN benzeri kanıt"


def test_candidate_pool_is_deterministic_and_sized():
    a = build_candidate_pool(seed=1, size=10)
    b = build_candidate_pool(seed=1, size=10)
    assert a == b and len(a) == 10
    assert build_candidate_pool(seed=2, size=10) != a


def test_attack_options_contain_truth_and_distractors():
    pool = build_candidate_pool(seed=1, size=20)
    opts = _options_for("occupation", "makine mühendisi", pool, seed_idx=3, k=6)
    assert "makine mühendisi" in opts
    assert len(opts) == 6
    assert len(set(opts)) == len(opts), "çeldiriciler tekrar etmemeli"


def test_attack_truth_position_varies_so_order_is_not_learnable():
    """Doğru cevap hep aynı konumdaysa model içeriği değil sırayı öğrenir."""
    pool = build_candidate_pool(seed=1, size=20)
    positions = {_options_for("occupation", "avukat", pool, seed_idx=i, k=6).index("avukat")
                 for i in range(6)}
    assert len(positions) > 1


def test_attack_prompt_never_contains_ground_truth_label():
    """Saldırgana cevap anahtarı GÖSTERİLMEZ — protokolün temel kuralı."""
    p = PROMPT_TEMPLATE.format(document="…", attribute="occupation",
                               options="a | b | c", top_k=3)
    assert "_truth" not in p
    assert PROTOCOL["ground_truth_shown_to_attacker"] is False
    assert PROTOCOL["input_to_attacker"] == "anonymized_text_only"
    assert PROTOCOL["temperature"] == 0.0


def test_attack_attributes_are_all_quasi_or_sensitive():
    """Saldırı doğrudan tanımlayıcıyı sormaz (o zaten maskelenir); dolaylı sızıntıyı ölçer."""
    assert "tckn" not in ATTACK_ATTRIBUTES
    assert "iban" not in ATTACK_ATTRIBUTES
    assert "full_name" not in ATTACK_ATTRIBUTES
    assert "occupation" in ATTACK_ATTRIBUTES and "health" in ATTACK_ATTRIBUTES

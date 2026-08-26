"""Fayda (utility) ve saldırı (attack) senaryoları — kalibrasyonun durma noktasını belirleyen alet.

Neden gerekli: aşırı-maskelemeyi kısarken recall'dan ne kaybettiğini ölçmeyen bir tuning, GÜVENLİ
bir sistemi sessizce SIZDIRAN bir sisteme çevirebilir. "Aşırı-maskeleme %100'den %20'ye düştü" tek
başına karar verdirmez; "belgeyle iş yapılabilirlik %45'ten %90'a çıktı" verdirir.

İki şey üretilir:

  1. FAYDA — belge başına sorular. Her sorunun cevabı belgede belirli bir yerde (`evidence`)
     durur. Anonim belgede o kanıt hâlâ okunabiliyorsa soru cevaplanabilir sayılır.
     `Task Utility Retention = anon_answerable / orig_answerable`

     KRİTİK TASARIM KURALI: cevap kanıtı ASLA PII olmamalı. Aksi halde yanlış şeyi ölçeriz — iyi
     bir karartıcı zaten PII'yi yok eder, bunu "fayda kaybı" saymak sistemi doğru davrandığı için
     cezalandırmak olur. Bu yüzden sorular sözleşme bedeli, teslim tarihi, öğrenim durumu gibi
     PII OLMAYAN alanlara sorulur ve kanıt olarak `NO_MASK` sınıfı ifadeler kullanılır.

  2. SALDIRI — kişinin gizli özellikleri (meslek, sağlık, konum, gelir bandı…). Sistem tüm
     DOĞRUDAN tanımlayıcıları maskelese de bunlar metinden çıkarılabiliyorsa gerçek gizlilik
     sağlanmamıştır. Ground truth `Person.attribute_truth()`'tan gelir — kişiyi biz uydurduğumuz
     için ne bilinmesi gerektiğini tam biliyoruz. Gerçek belgede bu ölçüm yapılamaz.

     TRIR/linkage için sabit bir aday kişi havuzu da üretilir: yeniden-tanımlama, "bu belge
     havuzdaki hangi kişiye ait?" sorusudur; havuz olmadan ölçülemez.
"""
from __future__ import annotations

import json
import random
from dataclasses import asdict, dataclass, field
from pathlib import Path

from evaluation.goldbench.generate import GOLD_DIR, build_document
from evaluation.goldbench.identity import candidate_pool, make_person
from evaluation.goldbench.schema import IdentifierClass, locate, norm

DATA = Path("data/goldbench")
INFERENCE_DIR = DATA / "inference"

N_SCENARIOS = 120
CANDIDATE_POOL_SIZE = 50

# Saldırganın tahmin edeceği özellikler. Hepsi Person.attribute_truth() anahtarlarıdır.
ATTACK_ATTRIBUTES = ("occupation", "employer", "district", "city",
                     "education", "salary_band", "health", "age_band")


@dataclass
class UtilityQuestion:
    """Cevabı belgede `evidence` ifadesinde duran bir soru.

    `evidence_is_pii=False` ZORUNLU: PII kanıta bağlı bir soru, iyi karartıcıyı cezalandırır.
    """

    qid: str
    question: str
    evidence: str          # belgede geçen, cevabı taşıyan ifade (PII DEĞİL)
    evidence_is_pii: bool = False


@dataclass
class InferenceScenario:
    scenario_id: str
    doc_id: str
    domain: str
    language: str
    subject_id: str
    questions: list[UtilityQuestion] = field(default_factory=list)
    attribute_truth: dict[str, str] = field(default_factory=dict)

    def safe_dict(self) -> dict:
        """Rapor-güvenli görünüm — attribute ground truth ham hâliyle rapora GİRMEZ."""
        return {"scenario_id": self.scenario_id, "doc_id": self.doc_id, "domain": self.domain,
                "language": self.language, "subject_id": self.subject_id,
                "question_count": len(self.questions),
                "attributes_tested": sorted(self.attribute_truth)}


# Alan başına soru şablonları. Kanıt olarak NO_MASK terimleri ve PII olmayan sabitler seçilir.
_QUESTION_TEMPLATES: dict[str, list[tuple[str, str]]] = {
    "hr": [
        ("Bu dosya hangi kapsamda incelenmiştir?", "Risk Değerlendirmesi"),
        ("Belge ne tür bir kayıttır?", "PERSONEL ÖZLÜK DOSYASI"),
    ],
    "legal": [
        ("Sözleşmenin bedeli nedir?", "480.000 TL"),
        ("Teslim tarihi ne zamandır?", "30 Kasım 2026"),
        ("Ödeme kaç taksitte yapılacaktır?", "üç eşit taksit"),
    ],
    "health": [
        ("Randevu hangi birimden alınacaktır?", "Kalite Kontrol"),
        ("Belge ne tür bir formdur?", "HASTA DEĞERLENDİRME FORMU"),
    ],
    "finance": [
        ("Fatura dönemi nedir?", "Ekim 2026"),
        ("Ekte hangi belge sunulmuştur?", "Gider Pusulası"),
        ("Belge ne tür bir özettir?", "MÜŞTERİ HESAP ÖZETİ"),
    ],
    "public": [
        ("Hangi kurul kararı beklenmektedir?", "Yönetim Kurulu"),
        ("Belge ne tür bir başvurudur?", "BAŞVURU DİLEKÇESİ"),
    ],
    "correspondence": [
        ("Talep hangi tarihte alınmıştır?", "14 Ekim 2026"),
        ("Hangi bilgi ayrıca iletilecektir?", "Teslim Tarihi"),
    ],
}


def _questions_for(domain: str, doc_id: str, text: str) -> list[UtilityQuestion]:
    """Şablonlardan, KANITI GERÇEKTEN BELGEDE OLAN soruları seçer.

    Kanıtı metinde bulunmayan soru sessizce atılır — cevaplanamaz bir soru, sistemin hatası gibi
    görünüp fayda skorunu haksız yere düşürürdü.
    """
    out: list[UtilityQuestion] = []
    for i, (q, ev) in enumerate(_QUESTION_TEMPLATES.get(domain, [])):
        if locate(text, ev, 0) is not None:
            out.append(UtilityQuestion(qid=f"{doc_id}-q{i:02d}", question=q, evidence=ev))
    return out


def build_scenarios(seed: int = 20260812, n: int = N_SCENARIOS) -> list[InferenceScenario]:
    """Gold korpusun bir alt kümesi için senaryo üretir (deterministik)."""
    gold_path = GOLD_DIR / "gold.jsonl"
    if not gold_path.exists():
        return []
    rows = [json.loads(x) for x in gold_path.read_text(encoding="utf-8").splitlines() if x.strip()]
    rows.sort(key=lambda r: r["doc_id"])  # deterministik

    # Alanlar arası DÖNÜŞÜMLÜ seçim. Düz doc_id sırasıyla alınırsa seçim alfabetik olarak
    # kayar (correspondence…hr) ve 120'ye ulaşmadan `legal`/`public` hiç girmez — ölçtük.
    # Fayda skoru alana çok bağlıdır (sözleşme ile dilekçe farklı okunur), bu yüzden alan
    # dengesi sonucun geçerliliği için şart.
    by_domain: dict[str, list[dict]] = {}
    for r in rows:
        by_domain.setdefault(r["domain"], []).append(r)
    ordered: list[dict] = []
    for i in range(max((len(v) for v in by_domain.values()), default=0)):
        for d in sorted(by_domain):
            if i < len(by_domain[d]):
                ordered.append(by_domain[d][i])

    scenarios: list[InferenceScenario] = []
    for row in ordered:
        if len(scenarios) >= n:
            break
        qs = _questions_for(row["domain"], row["doc_id"], row["text"])
        if not qs:
            continue  # sorusu olmayan belge fayda ölçemez

        # Belgenin ilk veri sahibini yeniden üret: attribute ground truth onun profilinden gelir.
        # build_document ile AYNI seed/rng zincirini kullanmak zorundayız, yoksa farklı kişi çıkar.
        subject_id = row["subjects"][0] if row["subjects"] else "-"
        truth = _attribute_truth_for(row)
        scenarios.append(InferenceScenario(
            scenario_id=f"sc-{len(scenarios):03d}", doc_id=row["doc_id"], domain=row["domain"],
            language=row["language"], subject_id=subject_id,
            questions=qs, attribute_truth=truth))
    return scenarios


def _attribute_truth_for(row: dict) -> dict[str, str]:
    """Belgedeki QUASI/SENSITIVE mention'larından saldırı cevap anahtarını türetir.

    Kişiyi yeniden üretmek yerine gold kayıttan okunur — böylece cevap anahtarı belgede GERÇEKTEN
    geçen değerlerle sınırlı kalır. (Belgede hiç geçmeyen bir özelliği "sızdırıldı mı" diye sormak
    anlamsızdır: saldırgan onu metinden değil, tahminle bulmuş olurdu.)
    """
    truth: dict[str, str] = {}
    type_to_attr = {"OCCUPATION": "occupation", "EMPLOYER": "employer", "LOCATION": "district",
                    "EDUCATION": "education", "SALARY": "salary_band", "HEALTH": "health",
                    "DISABILITY": "disability", "UNION": "union"}
    first_subject = row["subjects"][0] if row["subjects"] else None
    for m in row["mentions"]:
        if m["subject_id"] != first_subject:
            continue
        if m["identifier_class"] not in (IdentifierClass.QUASI.value,
                                         IdentifierClass.SENSITIVE_ATTRIBUTE.value):
            continue
        attr = type_to_attr.get(m["entity_type"])
        if attr and attr not in truth:
            truth[attr] = m["surface"]
    return truth


def score_utility(scenario: InferenceScenario, anon_text: str) -> dict:
    """Anonim metinde kaç sorunun kanıtı hâlâ okunabilir?

    Kanıt tam olarak (boşluk-esnek) duruyorsa soru cevaplanabilir sayılır. Bu deterministik bir
    vekildir — LLM'e sordurmaktan daha zayıf ama tekrarlanabilir ve modelden bağımsız. Kanıt
    maskelenmişse cevaplanamaz: aşırı-maskelemenin faydaya maliyeti tam olarak budur.
    """
    total = len(scenario.questions)
    answerable = sum(1 for q in scenario.questions if locate(anon_text, q.evidence, 0) is not None)
    return {"questions": total, "answerable": answerable,
            "answerable_rate": round(answerable / total, 4) if total else 0.0}


def build_candidate_pool(seed: int = 20260812, size: int = CANDIDATE_POOL_SIZE) -> list[dict]:
    """TRIR/linkage için sabit aday havuzu. Saldırgan anonim belgeyi bu kişilerle eşleştirmeye
    çalışır. Havuzdaki kişiler gold korpustaki kişilerden AYRI bir seed'den gelir — biri gerçekten
    belgedeki kişi değil, hepsi çeldirici; doğru cevap `attribute_truth` üzerinden ölçülür."""
    rng = random.Random(seed + 555_000)
    pool = candidate_pool(rng, size)
    return [{"candidate_id": p.subject_id, "occupation": p.occupation, "employer": p.employer,
             "district": p.district, "city": p.city, "education": p.education,
             "salary_band": p.salary_band, "health": p.health,
             "age_band": f"{p.age // 10 * 10}-{p.age // 10 * 10 + 9}"} for p in pool]


def write_scenarios(seed: int = 20260812, n: int = N_SCENARIOS) -> dict:
    INFERENCE_DIR.mkdir(parents=True, exist_ok=True)
    scenarios = build_scenarios(seed, n)
    with (INFERENCE_DIR / "scenarios.jsonl").open("w", encoding="utf-8") as f:
        for s in scenarios:
            f.write(json.dumps(asdict(s), ensure_ascii=False) + "\n")
    pool = build_candidate_pool(seed)
    (INFERENCE_DIR / "candidate_pool.json").write_text(
        json.dumps(pool, ensure_ascii=False, indent=1), encoding="utf-8")
    return {
        "scenarios": len(scenarios),
        "questions_total": sum(len(s.questions) for s in scenarios),
        "candidate_pool": len(pool),
        "by_domain": {d: sum(1 for s in scenarios if s.domain == d)
                      for d in sorted({s.domain for s in scenarios})},
        "attributes_covered": sorted({a for s in scenarios for a in s.attribute_truth}),
    }


__all__ = ["ATTACK_ATTRIBUTES", "InferenceScenario", "UtilityQuestion", "build_candidate_pool",
           "build_scenarios", "norm", "score_utility", "write_scenarios",
           "build_document", "make_person"]

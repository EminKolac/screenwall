"""GoldBench skorlama — tam ground-truth üstünde ölçülebilen metrikler.

Neden bu modül var: BIST korpusunda tam PII envanteri olmadığı için precision/F1/karakter-seviyeli
metrikler YAPISAL olarak hesaplanamıyordu (bkz. BENCHMARK_GUIDE.md §5.3). GoldBench'te cevap
anahtarı tam olduğu için hepsi hesaplanabilir.

İki ayrı eksen ölçülür, karıştırılmaz:

  A) TESPİT (detection) — gold span'ler vs. dedektör span'leri, AYNI koordinat uzayında
     (çıkarılmış orijinal metin). TAB ve RedactionBench de böyle ölçer. Karakter seviyeli
     metrikler burada.
  B) MASKELEME (masking) — değer anonim çıktıda/export'ta hâlâ var mı. Sızıntının kendisi.

Bir değer tespit edilip yine de maskelenmeyebilir (eşik/çakışma çözümü), bu yüzden ikisi ayrıdır.

KRİTİK: mevcut BIST harness'ı (`evaluation/bist30/harness.py:174`) maskelemeyi TAM DEĞER
yokluğuyla ölçüyor: `val not in anon_text`. Bu, kısmi sızıntıyı BAŞARI sayar — "0532 764 21 09"
→ "<DATE> 764 <DATE>" olduğunda tam değer metinde yoktur, dolayısıyla "maskelendi" görünür ama
"764" açıkta kalmıştır. Bu oturumda o hata elle yakalandı; buradaki karakter seviyeli kapsama
metriği onu ÖLÇÜLEBİLİR yapar (`test_partial_leak_is_caught_by_char_metrics` regresyonu).

R-Score notu (dürüstlük kaydı): RedactionBench'in R-Score referans implementasyonu bu yazım
sırasında YAYIMLANMAMIŞTIR (dataset README'sinde "will be released shortly"). Buradaki
`redaction_coverage_score` ondan ESİNLENMİŞTİR — mandatory kapsama + sınır cezası + FP cezası
bileşenlerini taşır — ama R-Score DEĞİLDİR ve öyle raporlanamaz.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from evaluation.goldbench.schema import (
    Channel,
    Criticality,
    GoldMention,
    IdentifierClass,
    Necessity,
    locate,
    norm,
)


@dataclass
class Span:
    start: int
    end: int
    entity_type: str = ""

    @property
    def length(self) -> int:
        return max(0, self.end - self.start)


def _charset(spans: list[Span]) -> set[int]:
    out: set[int] = set()
    for s in spans:
        out.update(range(s.start, s.end))
    return out


def _f_beta(precision: float, recall: float, beta: float) -> float:
    if precision <= 0 and recall <= 0:
        return 0.0
    b2 = beta * beta
    denom = b2 * precision + recall
    return 0.0 if denom == 0 else (1 + b2) * precision * recall / denom


@dataclass
class MentionResult:
    """Tek bir gold mention'ın karnesi."""

    mention_id: str
    entity_id: str
    subject_id: str
    vhash: str
    entity_type: str
    identifier_class: str
    necessity: str
    criticality: str
    channel: str
    located: bool           # gold değer çıkarılmış metinde bulundu mu (bulunamadıysa ölçülemez)
    detected_chars: int     # dedektör tarafından kapsanan karakter sayısı
    total_chars: int
    fully_detected: bool
    partially_detected: bool
    masked: bool            # değer anonim metinde TAM olarak yok
    residual_chars: int     # anonim metinde AÇIKTA kalan karakter sayısı (kısmi sızıntı ölçütü)
    leaked_in_export: bool

    @property
    def char_recall(self) -> float:
        return self.detected_chars / self.total_chars if self.total_chars else 0.0


def evaluate_document(
    gold: list[GoldMention],
    original_text: str,
    detected: list[Span],
    anon_text: str,
    export_text: str | None = None,
) -> list[MentionResult]:
    """Bir belgenin tüm gold mention'larını değerlendirir.

    `detected` span'leri `original_text` koordinatlarında olmalıdır (pipeline'ın dedektörü zaten
    böyle üretir: `PresidioEngine().detect(original_text)`).
    """
    det_chars = _charset(detected)
    det_types: dict[int, str] = {}
    for s in detected:
        for i in range(s.start, s.end):
            det_types.setdefault(i, s.entity_type)

    anon_n = norm(anon_text)
    export_n = norm(export_text) if export_text is not None else None
    results: list[MentionResult] = []

    for m in gold:
        loc = locate(original_text, m.surface, m.occurrence)
        if loc is None:
            # Değer çıkarılmış metinde yok: taşıyıcıya hiç girmemiş ya da çıkarım kaybetmiş.
            # Bu bir TESPİT hatası değildir; ayrı işaretlenir ki recall'u haksız yere düşürmesin
            # — ama sessizce de yok sayılmaz (located=False raporlanır).
            results.append(MentionResult(
                mention_id=m.mention_id, entity_id=m.entity_id, subject_id=m.subject_id,
                vhash=m.vhash, entity_type=m.entity_type,
                identifier_class=m.identifier_class.value, necessity=m.necessity.value,
                criticality=m.criticality.value, channel=m.channel.value,
                located=False, detected_chars=0, total_chars=len(m.surface),
                fully_detected=False, partially_detected=False, masked=False,
                residual_chars=0, leaked_in_export=False))
            continue

        start, end = loc
        span_chars = set(range(start, end))
        covered = span_chars & det_chars
        total = len(span_chars)

        surf_n = norm(m.surface)
        masked = bool(surf_n) and surf_n not in anon_n
        # Kısmi sızıntı: değerin PARÇALARI anonim metinde açıkta mı? Tam-değer kontrolü bunu
        # göremez. Değeri kelimelere bölüp her parçanın hâlâ görünüp görünmediğine bakarız;
        # tek karakterlik/çok kısa parçalar gürültü olduğu için 3+ karakter eşiği uygulanır.
        residual = 0
        if masked:
            for part in surf_n.split():
                if len(part) >= 3 and part in anon_n:
                    residual += len(part)

        leaked = bool(export_n is not None and surf_n and surf_n in export_n)

        results.append(MentionResult(
            mention_id=m.mention_id, entity_id=m.entity_id, subject_id=m.subject_id,
            vhash=m.vhash, entity_type=m.entity_type,
            identifier_class=m.identifier_class.value, necessity=m.necessity.value,
            criticality=m.criticality.value, channel=m.channel.value,
            located=True, detected_chars=len(covered), total_chars=total,
            fully_detected=len(covered) == total and total > 0,
            partially_detected=0 < len(covered) < total,
            masked=masked, residual_chars=residual,
            leaked_in_export=leaked))
    return results


# ------------------------------------------------------------------ toplama

@dataclass
class Metrics:
    values: dict = field(default_factory=dict)

    def __getitem__(self, k):
        return self.values[k]


def _rate(num: int, den: int) -> float:
    return round(num / den, 4) if den else 0.0


def aggregate(results: list[MentionResult],
              detected_total_chars: int = 0,
              gold_total_chars: int = 0) -> dict:
    """Mention sonuçlarını metrik ailelerine toplar.

    `NO_MASK` mention'ları recall'a GİRMEZ (maskelenmemeleri gerekir) — onlar precision/
    over-masking tarafında değerlendirilir.
    """
    maskable = [r for r in results if r.identifier_class != IdentifierClass.NO_MASK.value]
    nomask = [r for r in results if r.identifier_class == IdentifierClass.NO_MASK.value]
    located = [r for r in maskable if r.located]

    # --- mention-level
    mention_masked = sum(1 for r in located if r.masked)
    mention_detected = sum(1 for r in located if r.fully_detected)

    # --- entity-level: TÜM mention'ları maskeliyse entity korunmuş sayılır (TAB'ın katı ölçütü).
    by_entity: dict[str, list[MentionResult]] = {}
    for r in located:
        by_entity.setdefault(r.entity_id, []).append(r)
    entity_ok = sum(1 for rs in by_entity.values() if all(x.masked for x in rs))

    # --- karakter seviyesi
    char_total = sum(r.total_chars for r in located)
    char_cov = sum(r.detected_chars for r in located)
    residual_chars = sum(r.residual_chars for r in located)

    # --- precision: NO_MASK ihlalleri + dedektörün gold dışı kapsaması
    nomask_located = [r for r in nomask if r.located]
    nomask_violations = sum(1 for r in nomask_located if r.masked)
    over_masking_rate = _rate(nomask_violations, len(nomask_located))

    # Karakter precision: dedektörün kapsadığı karakterlerin ne kadarı gerçekten gold'du.
    char_precision = _rate(char_cov, detected_total_chars) if detected_total_chars else 0.0
    char_recall = _rate(char_cov, char_total)

    def _subset(pred) -> dict:
        sub = [r for r in located if pred(r)]
        return {
            "n": len(sub),
            "mention_recall": _rate(sum(1 for r in sub if r.masked), len(sub)),
            "char_recall": _rate(sum(r.detected_chars for r in sub),
                                 sum(r.total_chars for r in sub)),
            "leaked_in_export": sum(1 for r in sub if r.leaked_in_export),
        }

    mention_recall = _rate(mention_masked, len(located))
    f1 = _f_beta(char_precision, char_recall, 1.0)
    f2 = _f_beta(char_precision, char_recall, 2.0)  # recall'a 2 kat ağırlık (gizlilik önceliği)

    return {
        "mentions_total": len(maskable),
        "mentions_located": len(located),
        "not_located": len(maskable) - len(located),
        "mention_recall": mention_recall,
        "mention_detected_rate": _rate(mention_detected, len(located)),
        "entities_total": len(by_entity),
        "entity_recall": _rate(entity_ok, len(by_entity)),
        "char_recall": char_recall,
        "char_precision": char_precision,
        "f1": round(f1, 4),
        "f2": round(f2, 4),
        "residual_chars": residual_chars,
        "partial_leaks": sum(1 for r in located if r.masked and r.residual_chars > 0),
        "leaked_in_export": sum(1 for r in located if r.leaked_in_export),
        "critical_false_negatives": sum(
            1 for r in located
            if r.criticality == Criticality.CRITICAL.value and not r.masked),
        "critical_entity_recall": _rate(
            sum(1 for rs in by_entity.values()
                if all(x.masked for x in rs)
                and any(x.criticality == Criticality.CRITICAL.value for x in rs)),
            sum(1 for rs in by_entity.values()
                if any(x.criticality == Criticality.CRITICAL.value for x in rs))),
        "no_mask_total": len(nomask_located),
        "no_mask_violations": nomask_violations,
        "over_masking_rate": over_masking_rate,
        "redaction_coverage_score": redaction_coverage_score(results),
        "by_identifier_class": {
            k.value: _subset(lambda r, k=k: r.identifier_class == k.value)
            for k in (IdentifierClass.DIRECT, IdentifierClass.QUASI,
                      IdentifierClass.SENSITIVE_ATTRIBUTE)
        },
        "by_necessity": {
            k.value: _subset(lambda r, k=k: r.necessity == k.value)
            for k in (Necessity.MANDATORY, Necessity.CONTEXTUAL)
        },
        "by_entity_type": {
            t: _subset(lambda r, t=t: r.entity_type == t)
            for t in sorted({r.entity_type for r in located})
        },
        "by_channel": {
            c.value: _subset(lambda r, c=c: r.channel == c.value)
            for c in sorted({Channel(r.channel) for r in located}, key=lambda x: x.value)
        },
    }


def redaction_coverage_score(results: list[MentionResult],
                             fp_penalty: float = 0.5,
                             boundary_penalty: float = 0.5) -> float:
    """RedactionBench'in R-Score'undan ESİNLENMİŞ karakter seviyeli kapsama skoru.

    R-Score DEĞİLDİR: referans implementasyon yayımlanmadığı için birebir formül iddia edilemez
    (bkz. modül docstring'i). Taşıdığı fikirler:
      - zorunlu (mandatory) mention'ların KARAKTER kapsaması esas alınır → kısmi karartma kısmi
        kredi alır, tam-değer eşleşmesinin göremediği kısmi sızıntı buradan görünür
      - sınır hatası cezalandırılır: kısmen kapsanan bir mention tam kredi alamaz
      - yanlış pozitif (NO_MASK ihlali) cezalandırılır → "her şeyi maskele" stratejisi 1.0 alamaz
    Aralık [0, 1]; yüksek daha iyi.
    """
    located = [r for r in results
               if r.located and r.identifier_class != IdentifierClass.NO_MASK.value]
    if not located:
        return 0.0

    mandatory = [r for r in located if r.necessity == Necessity.MANDATORY.value] or located
    total = sum(r.total_chars for r in mandatory)
    if total == 0:
        return 0.0
    covered = sum(r.detected_chars for r in mandatory)
    coverage = covered / total

    partial = sum(1 for r in mandatory if r.partially_detected)
    boundary = (partial / len(mandatory)) * boundary_penalty

    nomask = [r for r in results
              if r.located and r.identifier_class == IdentifierClass.NO_MASK.value]
    fp = (sum(1 for r in nomask if r.masked) / len(nomask) * fp_penalty) if nomask else 0.0

    return round(max(0.0, min(1.0, coverage - boundary - fp)), 4)

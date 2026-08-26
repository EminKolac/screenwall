"""GoldBench koşu sonuçlarını (results.jsonl) rapora çevirir — 4 AYRI skor ailesi.

    uv run python -m evaluation.goldbench.report_gold --tag run1              # mod otomatik
    uv run python -m evaluation.goldbench.report_gold --tag run1 --mode both

KOMPOZİT PUAN ÜRETİLMEZ — bilinçli karar. Tek bir sayı, iki taban tabana zıt başarısızlığı
aynı hücreye yığar:

  * "her şeyi maskele" → sızıntı yok gibi görünür, ama belge kullanılamaz hale gelmiştir
    (over_masking_rate yüksek, utility_retention düşük);
  * "anlamı koru" → belge okunur kalır, ama kişi çıkarımla yeniden tanımlanabilir
    (attribute_inference_success yüksek).

Ortalaması alınmış tek bir "gizlilik skoru" ikisini de 0.8 gösterir. Bu yüzden aileler ayrı
raporlanır ve release gate her kriteri TEK TEK değerlendirir.

ÖLÇÜLMEMİŞ ≠ GEÇMİŞ. Henüz üretilmeyen bir ölçüm (çıkarım saldırısı, fayda) gate'te "ÖLÇÜLMEDİ"
görünür ve gate genel sonucunu "EKSİK" yapar. Ölçülmemiş bir kriteri sessizce geçmiş saymak bu
raporun yapabileceği en tehlikeli hatadır.

GÜVENLİK: rapora ASLA ham PII yazılmaz. `results.jsonl`'deki mention kayıtları yalnızca `vhash`
(sha256[:16]) taşır, `surface` taşımaz; bu modül bunu her koşuda DOĞRULAR
(`raw_pii_field_scan`) ve ihlal bulursa raporun en üstüne uyarı basar.

TOPLAMA NOTU: korpus geneli metrikler, belge başına `metrics` bloklarının ortalaması alınarak
DEĞİL, tüm belgelerin `mentions` kayıtları birleştirilip `score.aggregate()` yeniden çalıştırılarak
üretilir (mikro-ortalama). Belge başına ortalama, 2 mention'lı bir belgeyi 40 mention'lı bir belge
kadar ağırlıklandırırdı.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import fields as dc_fields
from pathlib import Path

from evaluation.goldbench.schema import Criticality, IdentifierClass
from evaluation.goldbench.score import MentionResult, aggregate

DATA = Path("data/goldbench")

# Gate sonuç sabitleri — "ölçülmedi" bilerek üçüncü bir durum, FAIL'in eşdeğeri değil.
PASS = "PASS"
FAIL = "FAIL"
UNMEASURED = "ÖLÇÜLMEDİ"

GATE_OK = "GEÇTİ"
GATE_FAIL = "BAŞARISIZ"
GATE_INCOMPLETE = "EKSİK"

_MENTION_FIELDS = {f.name for f in dc_fields(MentionResult)}

# Ham PII taşıyabilecek alan adları — mention kayıtlarında bulunmaları BEKLENMEZ.
_FORBIDDEN_MENTION_KEYS = ("surface", "value", "text", "raw", "original", "plain")

_INFERENCE_KEYS = (
    "utility_retention",
    "utility_drop",
    "attribute_inference_success",
    "trir",
)


# --------------------------------------------------------------------------- yükleme

def _load(p: Path) -> list[dict]:
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def _pct(a: float, b: float) -> float:
    return round(a / b, 4) if b else 0.0


def _mean(xs: list[float]) -> float | None:
    return round(sum(xs) / len(xs), 4) if xs else None


def raw_pii_field_scan(rows: list[dict]) -> dict:
    """Sonuç dosyasında ham PII taşıyabilecek alan var mı? (olmamalı)

    `MentionResult` yalnızca vhash + sayı taşır. Ekstra bir string alan belirirse bu, koşucu
    tarafında bir regresyondur ve rapor onu sessizce taşımamalıdır.
    """
    unexpected: set[str] = set()
    missing_vhash = 0
    total = 0
    for r in rows:
        for m in r.get("mentions") or []:
            total += 1
            if not m.get("vhash"):
                missing_vhash += 1
            for k in m:
                if k in _MENTION_FIELDS:
                    continue
                unexpected.add(k)
    forbidden = sorted(k for k in unexpected
                       if any(bad in k.lower() for bad in _FORBIDDEN_MENTION_KEYS))
    return {
        "mentions_scanned": total,
        "missing_vhash": missing_vhash,
        "unexpected_fields": sorted(unexpected),
        "forbidden_fields": forbidden,
        "clean": not forbidden and missing_vhash == 0,
    }


def _to_results(rows: list[dict]) -> list[MentionResult]:
    """Belge kayıtlarındaki mention sözlüklerini MentionResult'a geri çevirir.

    `entity_id` belge kimliğiyle ön eklenir: aynı özne farklı belgelerde geçtiğinde entity'leri
    korpus çapında birleştirmek, belge başına hesaplanan entity_recall ile karşılaştırılamaz bir
    sayı üretirdi.
    """
    out: list[MentionResult] = []
    for r in rows:
        doc = r.get("doc_id") or r.get("id") or "?"
        for m in r.get("mentions") or []:
            kw = {k: v for k, v in m.items() if k in _MENTION_FIELDS}
            kw.setdefault("mention_id", "")
            kw["entity_id"] = f"{doc}:{kw.get('entity_id', '')}"
            for name in ("mention_id", "subject_id", "vhash", "entity_type",
                         "identifier_class", "necessity", "criticality", "channel"):
                kw.setdefault(name, "")
            for name in ("detected_chars", "total_chars", "residual_chars"):
                kw.setdefault(name, 0)
            for name in ("located", "fully_detected", "partially_detected", "masked",
                         "leaked_in_export"):
                kw.setdefault(name, False)
            out.append(MentionResult(**kw))
    return out


def _detected_total_chars(rows: list[dict]) -> int:
    """Korpus geneli dedektör karakter toplamını belge metriklerinden GERİ ÇÖZER.

    `results.jsonl` ham `detected_total_chars` taşımıyor; ama belge başına
    `char_precision = kapsanan_gold_karakter / detected_total` yazılmış durumda. Bölmeyi ters
    çevirerek payda geri alınır. `char_precision` 4 basamağa yuvarlandığı için sonuç YAKLAŞIKTIR
    (belge başına ~%0.01 hata); korpus precision'ı bu yüzden "yaklaşık" olarak raporlanır.
    """
    total = 0
    for r in rows:
        met = r.get("metrics") or {}
        cp = met.get("char_precision") or 0.0
        cov = sum(m.get("detected_chars", 0) for m in (r.get("mentions") or [])
                  if m.get("located")
                  and m.get("identifier_class") != IdentifierClass.NO_MASK.value)
        if cp > 0 and cov:
            total += int(round(cov / cp))
    return total


# --------------------------------------------------------------------------- aileler

def detection_metrics(rows: list[dict]) -> dict:
    """Aile 1 — Tespit / Karartma. score.aggregate() üstünde mikro-ortalama."""
    results = _to_results(rows)
    blob = aggregate(results, detected_total_chars=_detected_total_chars(rows))
    located = [r for r in results if r.located
               and r.identifier_class != IdentifierClass.NO_MASK.value]
    crit = [r for r in located if r.criticality == Criticality.CRITICAL.value]
    crit_entities = {r.entity_id for r in crit}
    blob["critical_mentions"] = len(crit)
    blob["critical_entities"] = len(crit_entities)
    blob["char_precision_is_approximate"] = True
    return blob


def release_safety_metrics(det: dict, stress: dict | None) -> dict:
    """Aile 2 — Yayın güvenliği. Sızıntının kendisi; tespit metriği değil."""
    return {
        "critical_false_negatives": det.get("critical_false_negatives", 0),
        "critical_mentions": det.get("critical_mentions", 0),
        "leaked_in_export": det.get("leaked_in_export", 0),
        "partial_leaks": det.get("partial_leaks", 0),
        "residual_chars": det.get("residual_chars", 0),
        "not_located": det.get("not_located", 0),
        "stress": stress,
    }


def stress_metrics(path: Path | None) -> dict | None:
    """Stres koşusunun güvenlik kapısı özeti. Dosya yoksa None → gate'te ÖLÇÜLMEDİ."""
    if path is None:
        return None
    rows = _load(path)
    if not rows:
        return None
    verdicts: dict[str, int] = {}
    by_scenario: dict[str, dict[str, int]] = {}
    for r in rows:
        v = r.get("verdict", "?")
        verdicts[v] = verdicts.get(v, 0) + 1
        by_scenario.setdefault(r.get("scenario", "?"), {})[v] = \
            by_scenario.setdefault(r.get("scenario", "?"), {}).get(v, 0) + 1
    tested = [r for r in rows if not r.get("architecturally_safe") and r.get("generated")]
    return {
        "source": str(path),
        "total": len(rows),
        "pass": verdicts.get("pass", 0),
        "fail": verdicts.get("fail", 0),
        "critical_false_approval": verdicts.get("critical_false_approval", 0),
        "not_generated": verdicts.get("not_generated", 0),
        # "mimari gereği sızdıramaz" ile "test edildi ve geçti" ayrı sayılır.
        "architecturally_safe": sum(1 for r in rows if r.get("architecturally_safe")),
        "actually_tested": len(tested),
        "actually_tested_pass": sum(1 for r in tested if r.get("verdict") == "pass"),
        "over_conservative": sum(1 for r in rows if r.get("over_conservative")),
        "leaked": sum(1 for r in rows if r.get("planted_leaked")),
        "by_scenario": by_scenario,
    }


def inference_metrics(rows: list[dict]) -> dict:
    """Aile 3+4'ün ortak kaynağı — çıkarım saldırısı koşusu. Henüz üretilmiyor olabilir."""
    out: dict = {"records": len(rows)}
    for key in _INFERENCE_KEYS:
        vals = [float(r[key]) for r in rows if isinstance(r.get(key), (int, float))]
        out[key] = _mean(vals)
        out[f"{key}_n"] = len(vals)
    return out


def privacy_attack_metrics(inf: dict) -> dict:
    """Aile 3 — Gizlilik saldırısı. Ölçülmediyse None taşınır, 0 DEĞİL."""
    return {
        "attribute_inference_success": inf.get("attribute_inference_success"),
        "trir": inf.get("trir"),
        "records": inf.get("records", 0),
    }


def utility_metrics(det: dict, inf: dict) -> dict:
    """Aile 4 — Fayda. over_masking ölçülür, retention ölçülmemiş olabilir."""
    return {
        "over_masking_rate": det.get("over_masking_rate"),
        "no_mask_total": det.get("no_mask_total", 0),
        "no_mask_violations": det.get("no_mask_violations", 0),
        "utility_retention": inf.get("utility_retention"),
        "utility_drop": inf.get("utility_drop"),
    }


# --------------------------------------------------------------------------- release gate

def _crit(name: str, target: str, value, verdict: str, note: str = "") -> dict:
    return {"criterion": name, "target": target, "value": value,
            "verdict": verdict, "note": note}


def release_gate(det: dict, safety: dict, priv: dict, util: dict) -> dict:
    """Her kriter AYRI değerlendirilir; ölçülmeyen kriter FAIL değil ÖLÇÜLMEDİ'dir."""
    rows: list[dict] = []

    # 1) kritik false negative = 0
    if det.get("critical_mentions", 0) == 0:
        rows.append(_crit("critical_false_negatives", "= 0", None, UNMEASURED,
                          "korpusta kritik mention yok"))
    else:
        v = safety["critical_false_negatives"]
        rows.append(_crit("critical_false_negatives", "= 0", v, PASS if v == 0 else FAIL))

    # 2) kritik entity recall >= 0.95
    if det.get("critical_entities", 0) == 0:
        rows.append(_crit("critical_entity_recall", ">= 0.95", None, UNMEASURED,
                          "korpusta kritik entity yok"))
    else:
        v = det.get("critical_entity_recall", 0.0)
        rows.append(_crit("critical_entity_recall", ">= 0.95", v, PASS if v >= 0.95 else FAIL))

    # 3) over_masking_rate <= 0.10 — NO_MASK negatif kontrolü yoksa ölçülemez
    if util.get("no_mask_total", 0) == 0:
        rows.append(_crit("over_masking_rate", "<= 0.10", None, UNMEASURED,
                          "NO_MASK negatif kontrolü yok"))
    else:
        v = util["over_masking_rate"]
        rows.append(_crit("over_masking_rate", "<= 0.10", v, PASS if v <= 0.10 else FAIL))

    # 4) utility_retention >= 0.90
    v = util.get("utility_retention")
    if v is None:
        rows.append(_crit("utility_retention", ">= 0.90", None, UNMEASURED,
                          "çıkarım/fayda koşusu üretilmedi"))
    else:
        rows.append(_crit("utility_retention", ">= 0.90", v, PASS if v >= 0.90 else FAIL))

    # 5) stres kritik yanlış onay = 0
    st = safety.get("stress")
    if not st:
        rows.append(_crit("stress critical_false_approval", "= 0", None, UNMEASURED,
                          "stres koşusu bulunamadı"))
    else:
        v = st["critical_false_approval"]
        rows.append(_crit("stress critical_false_approval", "= 0", v, PASS if v == 0 else FAIL))

    # 6) export sızıntısı = 0
    if det.get("mentions_located", 0) == 0:
        rows.append(_crit("leaked_in_export", "= 0", None, UNMEASURED,
                          "yerleşen mention yok"))
    else:
        v = safety["leaked_in_export"]
        rows.append(_crit("leaked_in_export", "= 0", v, PASS if v == 0 else FAIL))

    verdicts = [r["verdict"] for r in rows]
    if FAIL in verdicts:
        overall = GATE_FAIL
    elif UNMEASURED in verdicts:
        overall = GATE_INCOMPLETE
    else:
        overall = GATE_OK
    # Ölçülmemiş bir kriter varken "GEÇTİ" ASLA üretilmez; FAIL varsa o baskındır.
    return {
        "overall": overall,
        "passed": verdicts.count(PASS),
        "failed": verdicts.count(FAIL),
        "unmeasured": verdicts.count(UNMEASURED),
        "criteria": rows,
    }


# --------------------------------------------------------------------------- markdown

def _fmt(v) -> str:
    if v is None:
        return "—"
    if isinstance(v, bool):
        return "evet" if v else "hayır"
    if isinstance(v, float):
        return f"{v:.4f}"
    return f"{v:,}" if isinstance(v, int) else str(v)


def _subset_table(title: str, blob: dict) -> list[str]:
    if not blob:
        return []
    out = [f"### {title}", "",
           "| grup | n | mention_recall | char_recall | export sızıntı |",
           "|---|---|---|---|---|"]
    for k, v in blob.items():
        out.append(f"| {k} | {v.get('n', 0)} | {v.get('mention_recall', 0):.4f} | "
                   f"{v.get('char_recall', 0):.4f} | {v.get('leaked_in_export', 0)} |")
    return out + [""]


def _gate_table(gate: dict) -> list[str]:
    out = ["## Release gate", "",
           f"**Genel sonuç: {gate['overall']}** — geçen {gate['passed']}, "
           f"kalan {gate['failed']}, ölçülmeyen {gate['unmeasured']}", "",
           "| Kriter | Hedef | Ölçülen | Sonuç | Not |", "|---|---|---|---|---|"]
    for c in gate["criteria"]:
        out.append(f"| {c['criterion']} | {c['target']} | {_fmt(c['value'])} | "
                   f"{c['verdict']} | {c['note']} |")
    out += ["",
            "> ÖLÇÜLMEYEN bir kriter GEÇMİŞ SAYILMAZ. Gate genel sonucu, tek bir kriter bile",
            "> ölçülmediğinde en iyi ihtimalle **EKSİK**'tir.", ""]
    return out


def _md(mode: str, cfg: dict, docs: dict, det: dict, safety: dict, priv: dict,
        util: dict, gate: dict, scan: dict) -> str:
    L = [f"# GoldBench Raporu — {mode}", ""]
    if not scan.get("clean", True):
        L += ["> **UYARI — ham PII sızıntısı şüphesi:** sonuç dosyasında beklenmeyen alanlar var: "
              f"`{', '.join(scan.get('forbidden_fields') or scan.get('unexpected_fields', []))}`. "
              "Rapor bu alanları taşımaz; koşucuyu düzeltin.", ""]
    L += [f"- Mod: **{mode}** · etiket `{cfg.get('tag', '?')}` · eşik "
          f"{cfg.get('anonymizer_score_threshold')} · denetçi {cfg.get('auditor_provider')}",
          f"- Belge-format kaydı: **{docs['records']}** · işlenen {docs['processed']} · "
          f"hata {docs['errors']} · süre ortalama {docs['mean_seconds']}s",
          f"- Mod bütünlük kontrolü geçen: {docs['mode_check_passed']}/{docs['mode_check_total']}",
          f"- PII alan taraması: mention {scan['mentions_scanned']}, vhash eksik "
          f"{scan['missing_vhash']}, yasak alan {len(scan['forbidden_fields'])}", ""]

    L += _gate_table(gate)

    L += ["## Aile 1 — Tespit / Karartma", "",
          f"- Mention: **{det['mentions_total']}** · yerleşen {det['mentions_located']} · "
          f"yerleşemeyen {det['not_located']} · entity {det['entities_total']}",
          f"- **mention_recall: {det['mention_recall']:.4f}** · "
          f"entity_recall: {det['entity_recall']:.4f} · "
          f"tespit oranı: {det['mention_detected_rate']:.4f}",
          f"- **char_recall: {det['char_recall']:.4f}** · "
          f"char_precision (yaklaşık): {det['char_precision']:.4f}",
          f"- F1: {det['f1']:.4f} · F2 (recall 2x ağırlık): {det['f2']:.4f}",
          f"- **redaction_coverage_score: {det['redaction_coverage_score']:.4f}** "
          "(R-Score DEĞİL — ondan esinlenmiştir)",
          f"- Kritik mention {det['critical_mentions']} / kritik entity "
          f"{det['critical_entities']} · critical_entity_recall "
          f"{det['critical_entity_recall']:.4f}", ""]
    L += _subset_table("Tanımlayıcı sınıfı bazında", det.get("by_identifier_class", {}))
    L += _subset_table("Gereklilik bazında", det.get("by_necessity", {}))
    L += _subset_table("Varlık türü bazında", det.get("by_entity_type", {}))
    L += _subset_table("Kanal bazında", det.get("by_channel", {}))

    L += ["## Aile 2 — Yayın güvenliği", "",
          f"- **critical_false_negatives: {safety['critical_false_negatives']}**",
          f"- **leaked_in_export: {safety['leaked_in_export']}** · "
          f"kısmi sızıntı: {safety['partial_leaks']} "
          f"(açıkta kalan {safety['residual_chars']} karakter)",
          f"- Çıkarılan metinde bulunamayan gold değer: {safety['not_located']} "
          "(tespit hatası değil, çıkarım kaybı)", ""]
    st = safety.get("stress")
    if st:
        L += [f"- Stres: {st['total']} vaka · geçti {st['pass']} · kaldı {st['fail']} · "
              f"**KRİTİK yanlış onay: {st['critical_false_approval']}**",
              f"- Gerçekten test edilen: {st['actually_tested_pass']}/{st['actually_tested']} "
              f"(mimari gereği güvenli {st['architecturally_safe']} — geçmesi kanıt değil)",
              f"- Temkinli (insana yönlendirildi): {st['over_conservative']}", "",
              "| senaryo | sonuçlar |", "|---|---|",
              *[f"| {k} | {v} |" for k, v in sorted(st["by_scenario"].items())], ""]
    else:
        L += ["- Stres koşusu **ÖLÇÜLMEDİ** (`stress.jsonl` bulunamadı).", ""]

    L += ["## Aile 3 — Gizlilik saldırısı", ""]
    if priv["attribute_inference_success"] is None and priv["trir"] is None:
        L += ["- **ÖLÇÜLMEDİ.** Saldırı koşusu (`<tag>-attack-<mode>/`) henüz üretilmedi ya da",
              "  bir saldırgan modelle koşulmadı (`attack.py --run`).",
              "  Bu aile ölçülmeden 'anonimleştirme yeterli' denemez: maskeleme metriklerinin",
              "  tamamı yüksekken bile öznenin bağlamdan yeniden tanımlanması mümkündür.", ""]
    else:
        L += [f"- attribute_inference_success: {_fmt(priv['attribute_inference_success'])}",
              f"- TRIR: {_fmt(priv['trir'])} · kayıt: {priv['records']}", ""]

    L += ["## Aile 4 — Fayda", "",
          f"- **over_masking_rate: {_fmt(util['over_masking_rate'])}** "
          f"(NO_MASK ihlali {util['no_mask_violations']}/{util['no_mask_total']})",
          f"- utility_retention: {_fmt(util['utility_retention'])} · "
          f"utility_drop: {_fmt(util['utility_drop'])}"]
    if util["utility_retention"] is None:
        L += ["- Fayda korunumu **ÖLÇÜLMEDİ** — aşırı maskeleyen bir sistem bu raporda yalnızca",
              "  `over_masking_rate` üstünden görünür, belgenin kullanılabilirliği görünmez.", ""]
    else:
        L += [""]

    L += ["## Metrik dürüstlüğü", "",
          "- **Kompozit puan yoktur.** Aşırı maskeleyip güvenli görünen sistemle, anlamı koruyup",
          "  kişiyi ele veren sistem tek bir sayıda ayırt edilemez.",
          "- **char_precision yaklaşıktır** — belge başına yuvarlanmış `char_precision`'dan geri",
          "  çözülür (payda ham olarak kaydedilmiyor).",
          "- **redaction_coverage_score R-Score değildir**; referans implementasyon yayımlanmadı.",
          "- **Ölçülmeyen kriter geçmiş sayılmaz** — gate 'EKSİK' verir.",
          "- Rapor yalnızca vhash ve sayı taşır; ham PII asla yazılmaz.", ""]
    return "\n".join(L)


# --------------------------------------------------------------------------- mod başına

def _find_stress(tag: str, mode: str) -> Path | None:
    """Stres sonucu iki yerde olabilir: koşucu `<tag>-<mode>/stress.jsonl` yazar; görev tanımı
    ayrıca `<tag>-stress/results.jsonl`'den söz eder. İkisi de denenir."""
    for cand in (DATA / "results" / f"{tag}-{mode}" / "stress.jsonl",
                 DATA / "results" / f"{tag}-stress" / "stress.jsonl",
                 DATA / "results" / f"{tag}-stress" / "results.jsonl"):
        if cand.exists():
            return cand
    return None


def _load_inference(tag: str, mode: str) -> list[dict]:
    """Fayda (`run_inference.py`) ve saldırı (`attack.py`) sonuçlarını birleştirir.

    İki koşucu da mod-özel dizine yazar: `<tag>-inference-<mode>/utility.jsonl` ve
    `<tag>-attack-<mode>/attack_summary.json`. Eski, mod-eki OLMAYAN `<tag>-inference/` deseni de
    (bu modülün ilk yazılışında varsayılmıştı) geriye dönük uyumluluk için denenir.
    """
    rows: list[dict] = []
    util_dir = DATA / "results" / f"{tag}-inference-{mode}"
    for p in sorted(util_dir.glob("*.jsonl")):
        rows.extend(_load(p))

    attack_summary = DATA / "results" / f"{tag}-attack-{mode}" / "attack_summary.json"
    if attack_summary.exists():
        rows.append(json.loads(attack_summary.read_text(encoding="utf-8")))

    legacy_dir = DATA / "results" / f"{tag}-inference"
    if legacy_dir.is_dir():
        for p in sorted(legacy_dir.glob("*.jsonl")):
            rows.extend(_load(p))
    return rows


def doc_metrics(rows: list[dict]) -> dict:
    proc = [r for r in rows if r.get("result") == "processed"]
    secs = [r.get("seconds", 0.0) for r in rows]
    checks = [r.get("mode_check") for r in rows if r.get("mode_check")]
    return {
        "records": len(rows),
        "processed": len(proc),
        "errors": sum(1 for r in rows if r.get("result") == "error"),
        "processed_rate": _pct(len(proc), len(rows)),
        "mean_seconds": round(sum(secs) / len(secs), 2) if secs else 0.0,
        "mode_check_total": len(checks),
        "mode_check_passed": sum(1 for c in checks if c.get("passed")),
        "mode_check_pass_rate": _pct(sum(1 for c in checks if c.get("passed")), len(checks)),
    }


def build_blob(tag: str, mode: str, rows: list[dict], cfg: dict,
               stress_path: Path | None, inf_rows: list[dict]) -> dict:
    scan = raw_pii_field_scan(rows)
    det = detection_metrics(rows)
    st = stress_metrics(stress_path)
    safety = release_safety_metrics(det, st)
    inf = inference_metrics(inf_rows)
    priv = privacy_attack_metrics(inf)
    util = utility_metrics(det, inf)
    gate = release_gate(det, safety, priv, util)
    return {
        "tag": tag, "mode": mode, "config": cfg,
        "documents": doc_metrics(rows),
        "pii_field_scan": scan,
        "detection": det,
        "release_safety": safety,
        "privacy_attack": priv,
        "utility": util,
        "release_gate": gate,
    }


def _report_one_mode(tag: str, mode: str) -> dict | None:
    d = DATA / "results" / f"{tag}-{mode}"
    rows = _load(d / "results.jsonl")
    if not rows:
        return None
    cfgp = d / "run_config.json"
    cfg = json.loads(cfgp.read_text(encoding="utf-8")) if cfgp.exists() else {}
    cfg.setdefault("tag", tag)
    blob = build_blob(tag, mode, rows, cfg, _find_stress(tag, mode), _load_inference(tag, mode))

    (d / "metrics.json").write_text(json.dumps(blob, ensure_ascii=False, indent=2),
                                    encoding="utf-8")
    md = _md(mode, cfg, blob["documents"], blob["detection"], blob["release_safety"],
             blob["privacy_attack"], blob["utility"], blob["release_gate"],
             blob["pii_field_scan"])
    (d / "REPORT.md").write_text(md, encoding="utf-8")
    print(f"\n[{mode}] gate: {blob['release_gate']['overall']} → {d}")
    return blob


# --------------------------------------------------------------------------- karşılaştırma

# D4: kalıcılık modu tespit metriklerini DEĞİŞTİRMEMELİDİR.
_D4_KEYS = ("mention_recall", "entity_recall", "char_recall", "char_precision", "f1", "f2",
            "redaction_coverage_score", "critical_entity_recall", "over_masking_rate",
            "critical_false_negatives", "leaked_in_export", "partial_leaks")


def compare(m: dict, dd: dict) -> dict:
    det_m, det_d = m["detection"], dd["detection"]
    diffs = [{"metric": k, "mapping": det_m.get(k), "destructive": det_d.get(k)}
             for k in _D4_KEYS if det_m.get(k) != det_d.get(k)]
    return {
        "d4_identical": not diffs,
        "differences": diffs,
        "gate": {"mapping": m["release_gate"]["overall"],
                 "destructive": dd["release_gate"]["overall"]},
        "metrics": {k: {"mapping": det_m.get(k), "destructive": det_d.get(k)}
                    for k in _D4_KEYS},
    }


def _comparison_md(tag: str, m: dict, dd: dict, cmp_blob: dict) -> str:
    L = [f"# GoldBench — mapping vs destructive ({tag})", "",
         "Aynı korpus, aynı ayarlar, tek fark kalıcılık modu. İki modun tespit metrikleri **AYNI**",
         "olmalıdır (BENCHMARK_GUIDE.md §12.3 / D4). Fark varsa bu bir **REGRESYON işaretidir** —",
         "kabul edilebilir bir tasarım farkı değildir; modlardan biri farklı bir dedektör yolundan",
         "geçiyor demektir.", ""]
    if cmp_blob["d4_identical"]:
        L += ["**D4: ✓ tespit metrikleri birebir aynı.**", ""]
    else:
        L += [f"**D4: ✗ {len(cmp_blob['differences'])} metrik farklı — REGRESYON İNCELEYİN.**", "",
              "| metrik | mapping | destructive |", "|---|---|---|",
              *[f"| {d['metric']} | {_fmt(d['mapping'])} | {_fmt(d['destructive'])} |"
                for d in cmp_blob["differences"]], ""]
    L += ["## Tespit metrikleri", "", "| metrik | mapping | destructive |", "|---|---|---|",
          *[f"| {k} | {_fmt(v['mapping'])} | {_fmt(v['destructive'])} |"
            for k, v in cmp_blob["metrics"].items()], "",
          "## Release gate", "", "| mod | sonuç |", "|---|---|",
          f"| mapping | {cmp_blob['gate']['mapping']} |",
          f"| destructive | {cmp_blob['gate']['destructive']} |", "",
          "## Mod bütünlüğü", "",
          f"- mapping (M1-M3): {m['documents']['mode_check_passed']}/"
          f"{m['documents']['mode_check_total']} "
          f"({m['documents']['mode_check_pass_rate']:.1%})",
          f"- destructive (D2-D3): {dd['documents']['mode_check_passed']}/"
          f"{dd['documents']['mode_check_total']} "
          f"({dd['documents']['mode_check_pass_rate']:.1%})", ""]
    return "\n".join(L)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="GoldBench raporu üret (4 ayrı skor ailesi).")
    ap.add_argument("--tag", default="run1")
    ap.add_argument("--mode", choices=["mapping", "destructive", "both", "auto"], default="auto")
    args = ap.parse_args(argv)

    modes = ["mapping", "destructive"] if args.mode in ("both", "auto") else [args.mode]
    blobs: dict[str, dict] = {}
    for mode in modes:
        blob = _report_one_mode(args.tag, mode)
        if blob is not None:
            blobs[mode] = blob
        elif args.mode not in ("auto", "both"):
            print(f"sonuç yok: {DATA / 'results' / f'{args.tag}-{mode}'}")
            return 1

    if not blobs:
        print(f"'{args.tag}' için hiçbir mod bulunamadı "
              f"(results/{args.tag}-mapping|destructive).")
        return 1

    for mode, blob in blobs.items():
        g = blob["release_gate"]
        print(f"[{mode}] gate {g['overall']}: geçen {g['passed']}, kalan {g['failed']}, "
              f"ölçülmeyen {g['unmeasured']}")

    if "mapping" in blobs and "destructive" in blobs:
        out = DATA / "results" / args.tag
        out.mkdir(parents=True, exist_ok=True)
        cmp_blob = compare(blobs["mapping"], blobs["destructive"])
        (out / "comparison.json").write_text(
            json.dumps(cmp_blob, ensure_ascii=False, indent=2), encoding="utf-8")
        (out / "COMPARISON.md").write_text(
            _comparison_md(args.tag, blobs["mapping"], blobs["destructive"], cmp_blob),
            encoding="utf-8")
        print(f"karşılaştırma → {out} (D4 aynı mı: {cmp_blob['d4_identical']})")

    # Ölçülmemiş kriter varken 0 döndürmek "geçti" sinyali olurdu; yalnızca tam GEÇTİ 0 döner.
    return 0 if all(b["release_gate"]["overall"] == GATE_OK for b in blobs.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())

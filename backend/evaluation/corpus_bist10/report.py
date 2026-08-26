"""Turn BIST-10 benchmark result JSONL into metrics + human/machine reports.

    uv run python -m evaluation.corpus_bist10.report --tag run1              # auto-detects modes
    uv run python -m evaluation.corpus_bist10.report --tag run1 --mode both  # explicit

METRIC HONESTY — read before quoting any number:

* **Canary recall is exact.** We planted the values, so "was it masked" has a definite answer.
* **Precision is NOT computed on this corpus, deliberately.** Precision needs the FULL inventory of
  personal data in each document; in a real annual report nobody has labelled that. Anything we
  called "precision" here would silently count a correctly-masked real name as a false positive.
  Instead we report measurable OVER-MASKING PROXIES (redaction density, family mix) and say plainly
  that separating "conservative false positive" from "real leak" needs human labelling.
* **Operational rates carry no ground truth** — they describe behaviour, not correctness.
* **Mode checks (M1-M3 / D1-D4) are pass/fail integrity facts, not detection metrics** — see
  BENCHMARK_GUIDE.md §11-12. `operational_metrics`/`canary_metrics` below are UNCHANGED by mode —
  they are the shared metrics §12.3 requires so the two modes stay comparable.
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

DATA = Path("data/corpus_bist10")
_MODE_CHECK_NAMES = {
    "mapping": ("M1_mapping_complete", "M2_roundtrip_complete", "M3_mapping_contained"),
    "destructive": ("D2_no_original", "D2_no_extracted", "D2_no_mapping_file", "D3_reversal_fails"),
}


def _load(p: Path) -> list[dict]:
    if not p.exists():
        return []
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]


def _pct(a: int, b: int) -> float:
    return round(a / b, 4) if b else 0.0


def _p95(xs: list[float]) -> float:
    if not xs:
        return 0.0
    s = sorted(xs)
    return round(s[min(len(s) - 1, int(round(0.95 * (len(s) - 1))))], 2)


def operational_metrics(rows: list[dict]) -> dict:
    n = len(rows)
    proc = [r for r in rows if r.get("result") == "processed"]
    secs = [r.get("seconds", 0.0) for r in proc]
    fams, srcs = Counter(), Counter()
    for r in proc:
        fams.update(r.get("placeholder_families") or {})
        srcs.update(r.get("by_source") or {})
    ext_chars = sum(r.get("extracted_chars", 0) for r in proc)
    ph_total = sum(r.get("placeholders_total", 0) for r in proc)
    # Over-masking proxy: placeholders per 1000 extracted characters. A dense redaction on a
    # financial report means business language is being masked, not just personal data.
    density = round(ph_total / (ext_chars / 1000), 2) if ext_chars else 0.0

    by_fmt: dict[str, Counter] = defaultdict(Counter)
    by_co: dict[str, Counter] = defaultdict(Counter)
    for r in rows:
        key = r.get("status") or r.get("result") or "?"
        by_fmt[r.get("format", "?")][key] += 1
        by_co[r.get("ticker", "?")][key] += 1

    statuses = Counter(r.get("status") for r in proc if r.get("status"))
    return {
        "documents": n,
        "processed": len(proc),
        "processed_rate": _pct(len(proc), n),
        "rejected": sum(1 for r in rows if r.get("result") == "rejected"),
        "extraction_failed": sum(1 for r in rows if r.get("result") == "extraction_failed"),
        "errors": sum(1 for r in rows if r.get("result") == "error"),
        "approved": statuses.get("approved", 0),
        "needs_human_review": sum(v for k, v in statuses.items() if "review" in (k or "").lower()),
        "approved_rate": _pct(statuses.get("approved", 0), len(proc)),
        "empty_extraction": sum(1 for r in proc if r.get("empty_extraction")),
        "ocr_warning_docs": sum(1 for r in proc if r.get("ocr_warning")),
        "export_ok": sum(1 for r in proc if r.get("export_ok")),
        "export_ok_rate": _pct(sum(1 for r in proc if r.get("export_ok")), len(proc)),
        "total_extracted_chars": ext_chars,
        "total_placeholders": ph_total,
        "redaction_density_per_1k_chars": density,
        "mean_seconds": round(sum(secs) / len(secs), 2) if secs else 0.0,
        "p95_seconds": _p95(secs),
        "status_distribution": dict(statuses),
        "detection_by_source": dict(srcs),
        "placeholder_families": dict(fams.most_common()),
        "by_format": {k: dict(v) for k, v in sorted(by_fmt.items())},
        "by_company": {k: dict(v) for k, v in sorted(by_co.items())},
    }


def canary_metrics(rows: list[dict]) -> dict:
    places = [p for r in rows if r.get("result") == "processed" for p in r.get("placements", [])]
    docs = [r for r in rows if r.get("result") == "processed"]
    content = [p for p in places if p.get("channel") != "filename"]
    extracted = [p for p in content if p.get("extracted")]
    masked = [p for p in extracted if p.get("masked")]
    leaked = [p for p in places if p.get("residual_in_export")]
    crit_fn = [p for p in content if p.get("critical") and
               (p.get("residual_in_export") or (p.get("extracted") and not p.get("masked")))]

    def group(key: str) -> dict:
        g: dict[str, list] = defaultdict(list)
        for p in content:
            g[p.get(key) or "?"].append(p)
        out = {}
        for k, ps in sorted(g.items()):
            ex = [p for p in ps if p.get("extracted")]
            out[k] = {
                "n": len(ps), "extracted": len(ex),
                "masked": sum(1 for p in ex if p.get("masked")),
                "leaked": sum(1 for p in ps if p.get("residual_in_export")),
                "extraction_rate": _pct(len(ex), len(ps)),
                "recall": _pct(sum(1 for p in ex if p.get("masked")), len(ex)),
            }
        return out

    secs = [r.get("seconds", 0.0) for r in docs]
    return {
        "documents": len(rows),
        "documents_processed": len(docs),
        "placements": len(places),
        "extracted": len(extracted),
        "masked": len(masked),
        "extraction_rate": _pct(len(extracted), len(content)),
        "value_recall": _pct(len(masked), len(extracted)),
        "recall_incl_extraction_loss": _pct(len(masked), len(content)),
        "export_residual": len(leaked),
        "critical_false_negatives": len(crit_fn),
        "family_correct_of_masked": _pct(sum(1 for p in masked if p.get("family_ok")), len(masked)),
        "stage_counts": dict(Counter(p.get("stage") for p in places).most_common()),
        "per_entity": group("canary_id"),
        "per_channel": group("channel"),
        "per_format": group("fmt"),
        "critical_fn_detail": [{k: p.get(k) for k in
                                ("canary_id", "fmt", "channel", "stage", "vhash")}
                               for p in crit_fn],
        "mean_seconds": round(sum(secs) / len(secs), 2) if secs else 0.0,
        "p95_seconds": _p95(secs),
    }


def mode_check_metrics(rows: list[dict], mode: str) -> dict:
    """Aggregate evaluation.corpus_bist10.verify_mode results (BENCHMARK_GUIDE.md §11-12) into
    per-check pass rates. `rows` are ModeCheckResult.safe_dict() lines from mode_checks.jsonl —
    value-free by construction (booleans/counts only)."""
    names = _MODE_CHECK_NAMES.get(mode, ())
    n = len(rows)
    per_check = {name: _pct(sum(1 for r in rows if r.get("checks", {}).get(name)), n)
                for name in names}
    return {
        "documents_checked": n,
        "all_checks_passed": sum(1 for r in rows if r.get("passed")),
        "all_checks_passed_rate": _pct(sum(1 for r in rows if r.get("passed")), n),
        "per_check_pass_rate": per_check,
    }


def _md(op: dict, cn: dict, cfg: dict, mode: str = "", mc: dict | None = None,
        d1: dict | None = None) -> str:
    title = f"# BIST-10 Korpus Benchmark — Sonuçlar ({mode})" if mode else \
        "# BIST-10 Korpus Benchmark — Sonuçlar"
    L = [title, ""]
    pf = 'AÇIK' if cfg.get('use_privacy_filter') else 'KAPALI'
    L += [f"- Mod: **{mode or cfg.get('mode', '?')}** · Privacy Filter **{pf}** · eşik "
          f"{cfg.get('anonymizer_score_threshold')} · denetçi {cfg.get('auditor_provider')}", ""]
    if op:
        L += ["## İz 1 — Operasyonel (ham belgeler, cevap anahtarı YOK)", "",
              f"- Belge: **{op['documents']}** · işlenen **{op['processed']}** "
              f"({op['processed_rate']:.1%}) · reddedilen {op['rejected']} · hata {op['errors']}",
              f"- Onaylanan: **{op['approved']}** ({op['approved_rate']:.1%}) · "
              f"insan incelemesi: {op['needs_human_review']}",
              f"- Export: {op['export_ok']}/{op['processed']} ({op['export_ok_rate']:.1%})",
              f"- Boş çıkarım: {op['empty_extraction']} · OCR uyarısı: {op['ocr_warning_docs']}",
              f"- Çıkarılan metin: **{op['total_extracted_chars']:,} karakter** · "
              f"üretilen yer tutucu: **{op['total_placeholders']:,}**",
              f"- **Karartma yoğunluğu: {op['redaction_density_per_1k_chars']} / 1000 karakter**"
              " (aşırı-maskeleme göstergesi)",
              f"- Süre: ortalama {op['mean_seconds']}s · p95 {op['p95_seconds']}s", "",
              "### Tespit kaynağı", "",
              *[f"- {k}: {v:,}" for k, v in op["detection_by_source"].items()], "",
              "### En sık yer tutucu aileleri", "",
              "| aile | adet |", "|---|---|",
              *[f"| {k} | {v:,} |" for k, v in list(op["placeholder_families"].items())[:12]], "",
              "### Format bazında", "",
              "| format | dağılım |", "|---|---|",
              *[f"| {k} | {v} |" for k, v in op["by_format"].items()], "",
              "### Şirket bazında", "",
              "| şirket | dağılım |", "|---|---|",
              *[f"| {k} | {v} |" for k, v in op["by_company"].items()], ""]
    if cn:
        L += ["## İz 2 — Canary (gerçek belgelere enjeksiyon, cevap anahtarı VAR)", "",
              f"- Belge: {cn['documents_processed']}/{cn['documents']} · "
              f"yerleştirme: **{cn['placements']}**",
              f"- Çıkarım oranı: {cn['extraction_rate']:.1%} "
              f"({cn['extracted']}/{cn['placements']})",
              f"- **Değer bazlı recall (çıkarılanlar üzerinden): {cn['value_recall']:.1%}**",
              f"- **Uçtan uca recall (çıkarım kaybı dahil): "
              f"{cn['recall_incl_extraction_loss']:.1%}**",
              f"- **Export'ta kalan (sızıntı): {cn['export_residual']}** · "
              f"**kritik false negative: {cn['critical_false_negatives']}**",
              f"- Maskelenenlerde doğru aile: {cn['family_correct_of_masked']:.1%}",
              f"- Süre: ortalama {cn['mean_seconds']}s · p95 {cn['p95_seconds']}s", "",
              "### Aşama dağılımı", "",
              "| aşama | adet |", "|---|---|",
              *[f"| {k} | {v} |" for k, v in cn["stage_counts"].items()], "",
              "### Varlık türü bazında", "",
              "| tür | n | çıkarıldı | maskelendi | sızdı | recall |", "|---|---|---|---|---|---|",
              *[f"| {k} | {v['n']} | {v['extracted']} | {v['masked']} | {v['leaked']} | "
                f"{v['recall']:.0%} |" for k, v in cn["per_entity"].items()], "",
              "### Kanal bazında", "",
              "| kanal | n | çıkarım | recall |", "|---|---|---|---|",
              *[f"| {k} | {v['n']} | {v['extraction_rate']:.0%} | {v['recall']:.0%} |"
                for k, v in cn["per_channel"].items()], "",
              "### Format bazında", "",
              "| format | n | çıkarım | recall |", "|---|---|---|---|",
              *[f"| {k} | {v['n']} | {v['extraction_rate']:.0%} | {v['recall']:.0%} |"
                for k, v in cn["per_format"].items()], ""]
        if cn["critical_fn_detail"]:
            L += ["### Kritik false negative'ler (değer içermez)", "",
                  "| tür | format | kanal | aşama | vhash |", "|---|---|---|---|---|",
                  *[f"| {d['canary_id']} | {d['fmt']} | {d['channel']} | {d['stage']} | "
                    f"{d['vhash']} |" for d in cn["critical_fn_detail"]], ""]
    if mc:
        label = "Benchmark M — mapping bütünlüğü" if mode == "mapping" else \
            "Benchmark D — destructive bütünlüğü"
        L += [f"## {label}", "",
              f"- Kontrol edilen belge: {mc['documents_checked']} · "
              f"tüm kontrolleri geçen: {mc['all_checks_passed']} "
              f"({mc['all_checks_passed_rate']:.1%})", "",
              "| kontrol | geçme oranı |", "|---|---|",
              *[f"| {k} | {v:.1%} |" for k, v in mc["per_check_pass_rate"].items()], ""]
    if d1:
        gate = "✓ GEÇTİ" if d1["total_hits"] == 0 else "✗ BAŞARISIZ"
        L += ["## D1 — Tam ağaç PII taraması (kabul kapısı)", "",
              f"- **{gate}** — {d1['total_hits']} eşleşme "
              f"({d1['values_swept']} canary değeri tarandı)", ""]
        if d1["total_hits"]:
            L += ["| vhash | eşleşme |", "|---|---|",
                  *[f"| {h} | {n} |" for h, n in d1["hits_by_vhash"].items() if n], ""]
    L += ["## Metrik dürüstlüğü", "",
          "- **Precision bu korpusta HESAPLANMAZ.** Gerçek bir faaliyet raporunda kişisel verinin",
          "  tam envanteri etiketlenmemiştir; precision hesaplamak, doğru maskelenmiş bir ismi",
          "  sessizce 'yanlış pozitif' saymak olurdu. Yerine ölçülebilir **karartma yoğunluğu** ve",
          "  **aile dağılımı** raporlanır.",
          "- **Canary recall kesindir** — değerleri biz yerleştirdik.",
          "- **Operasyonel oranlar doğruluk değil davranış ölçer.**", ""]
    return "\n".join(L)


def _report_one_mode(tag: str, mode: str) -> dict | None:
    """Build metrics.json/REPORT.md/CSVs for one mode's results dir. Returns the metrics blob (for
    the cross-mode comparison), or None if that mode has no results."""
    d = DATA / "results" / f"{tag}-{mode}"
    op_rows, cn_rows = _load(d / "operational.jsonl"), _load(d / "canary.jsonl")
    mc_rows = _load(d / "mode_checks.jsonl")
    if not op_rows and not cn_rows:
        return None
    cfgp = d / "run_config.json"
    cfg = json.loads(cfgp.read_text()) if cfgp.exists() else {}
    op = operational_metrics(op_rows) if op_rows else {}
    cn = canary_metrics(cn_rows) if cn_rows else {}
    mc = mode_check_metrics(mc_rows, mode) if mc_rows else {}
    d1p = d / "d1_sweep.json"
    d1 = json.loads(d1p.read_text()) if d1p.exists() else None

    blob = {"config": cfg, "operational": op, "canary": cn, "mode_checks": mc, "d1_sweep": d1}
    (d / "metrics.json").write_text(json.dumps(blob, ensure_ascii=False, indent=2),
                                    encoding="utf-8")
    (d / "REPORT.md").write_text(_md(op, cn, cfg, mode, mc, d1), encoding="utf-8")

    if op_rows:
        with (d / "operational.csv").open("w", newline="", encoding="utf-8") as f:
            cols = ["id", "ticker", "format", "doc_type", "result", "status", "language",
                    "extracted_chars", "anon_chars", "placeholders_total", "export_ok",
                    "skip_reason", "seconds"]
            w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
            w.writeheader()
            for r in op_rows:
                w.writerow(r)
    if cn_rows:
        with (d / "canary_placements.csv").open("w", newline="", encoding="utf-8") as f:
            cols = ["doc_id", "canary_id", "fmt", "channel", "expected_family", "critical",
                    "extracted", "detected", "masked", "family_ok", "residual_in_export", "stage",
                    "vhash"]
            w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
            w.writeheader()
            for r in cn_rows:
                for p in r.get("placements", []):
                    w.writerow({**p, "doc_id": r["id"]})

    print(f"\n[{mode}]")
    print(_md(op, cn, cfg, mode, mc, d1)[:1800])
    print(f"raporlar → {d}")
    return blob


def _comparison_md(tag: str, m: dict, dd: dict) -> str:
    cn_m, cn_d = m.get("canary", {}), dd.get("canary", {})
    op_m, op_d = m.get("operational", {}), dd.get("operational", {})
    mc_m, mc_d = m.get("mode_checks", {}), dd.get("mode_checks", {})
    d1 = dd.get("d1_sweep") or {}
    rows = [
        ("recall_incl_extraction_loss", cn_m.get("recall_incl_extraction_loss"),
         cn_d.get("recall_incl_extraction_loss")),
        ("export_residual", cn_m.get("export_residual"), cn_d.get("export_residual")),
        ("critical_false_negatives", cn_m.get("critical_false_negatives"),
         cn_d.get("critical_false_negatives")),
        ("family_correct_of_masked", cn_m.get("family_correct_of_masked"),
         cn_d.get("family_correct_of_masked")),
        ("canary p95_seconds", cn_m.get("p95_seconds"), cn_d.get("p95_seconds")),
        ("redaction_density_per_1k_chars", op_m.get("redaction_density_per_1k_chars"),
         op_d.get("redaction_density_per_1k_chars")),
        ("approved_rate", op_m.get("approved_rate"), op_d.get("approved_rate")),
    ]
    L = [f"# BIST-10 — mapping vs destructive karşılaştırması ({tag})", "",
        "Aynı korpus, aynı ayarlar, tek fark: kalıcılık modu. Her iki modun da AYNI tespit "
        "metriklerini üretmesi beklenir (BENCHMARK_GUIDE.md §12.3 / D4) — fark varsa bu bir "
        "regresyon işaretidir, kabul edilebilir bir tasarım farkı değil.", "",
        "| metrik | mapping | destructive |", "|---|---|---|"]
    for name, a, b in rows:
        L.append(f"| {name} | {a} | {b} |")
    d1_line = "✓ 0 eşleşme" if d1.get("total_hits") == 0 else f"✗ {d1.get('total_hits')} eşleşme"
    L += ["", "## Mod bütünlüğü", "",
        f"- Mapping — M1-M3 tüm kontrolleri geçen: {mc_m.get('all_checks_passed_rate', 0):.1%}",
        f"- Destructive — D2-D3 tüm kontrolleri geçen: "
        f"{mc_d.get('all_checks_passed_rate', 0):.1%}",
        f"- **D1 tam ağaç taraması: {d1_line}**", ""]
    return "\n".join(L)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="BIST-10 benchmark raporu üret.")
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
        print(f"'{args.tag}' için hiçbir mod bulunamadı (results/{args.tag}-mapping|destructive).")
        return 1

    if "mapping" in blobs and "destructive" in blobs:
        out = DATA / "results" / args.tag
        out.mkdir(parents=True, exist_ok=True)
        cmp_md = _comparison_md(args.tag, blobs["mapping"], blobs["destructive"])
        (out / "COMPARISON.md").write_text(cmp_md, encoding="utf-8")
        (out / "comparison.json").write_text(
            json.dumps(blobs, ensure_ascii=False, indent=2), encoding="utf-8")
        print("\n" + cmp_md)
        print(f"karşılaştırma → {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

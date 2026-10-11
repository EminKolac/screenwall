"""GoldBench stres koşucusu — güvenlik kapılarını ölçer, PII recall'unu değil.

    uv run python -m evaluation.goldbench.run_stress --mode mapping --tag run1

Her stres belgesi (`evaluation/goldbench/stress.py`) pipeline'dan geçirilir ve sonucu belgenin
İKİLİ beklentisiyle karşılaştırılır:

  safe_output  → yerleştirilen değerlerin hiçbiri anonim çıktıda VEYA export edilen PDF'te yok.
  fail_closed  → sistem belgeyi reddetti veya NEEDS_HUMAN_REVIEW'a yönlendirdi.

RELEASE GATE: `critical_false_approval == 0`. Bu, "desteklenmeyen/riskli bir yüzeyde PII varken
belge APPROVED oldu ve değer çıktıya sızdı" durumudur — beklentisi ne olursa olsun kritik ihlaldir.

`expected=safe_output` olan bir belgenin insan incelemesine düşmesi ihlal DEĞİLDİR (temkinli ama
güvenli); `over_conservative=true` olarak ayrıca işaretlenir, çünkü hepsini insana yollayan bir
sistem de bu testten tam puan alır — o sinyali kaybetmemek gerekir.

MİMARİ AYRIM: `architecturally_safe` vakalar (metadata / external_link) export mimarisi gereği
zaten sızdıramaz — özet bunları AYRI sayar. "Test edildi ve geçti" ile "mimari gereği mümkün
değil" aynı sütunda toplanırsa sahte güven üretir.

Her mod KENDİ storage kökünü kullanır (asla paylaşılmaz) ve sonuçlar JSONL'e akış halinde yazılır;
yeniden koşu tamamlanmış id'leri atlar → uzun bir koşu kesilip devam ettirilebilir.

GÜVENLİK: JSONL'e ASLA ham PII yazılmaz — yalnızca sha256[:16] (`value_hash`).
"""
from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path

from app.config import Settings
from app.export.render_pdf import EVALUATION_TITLE, render_content_pdf
from app.extraction.base import ExtractionFailed, UploadRejected
from app.extraction.dispatcher import extract
from app.models.document import DocumentStatus
from app.pipeline.runner import run_pipeline
from app.services.storage_repository import StorageDocumentRepository
from app.storage.local import LocalStorageBackend
from evaluation.bist30.canary import value_hash
from evaluation.goldbench.stress import (
    ARCHITECTURALLY_SAFE,
    FAIL_CLOSED,
    SAFE_OUTPUT,
    StressCase,
    build_corpus,
)
from evaluation.llm_flag import (
    LLM_DEFAULT,
    LLMModeMismatchError,
    LLMUnavailableError,
    add_llm_argument,
    build_settings,
    check_resume,
    ensure_llm_ready,
    llm_audit_counts,
    llm_config,
)

DATA = Path("data/goldbench")
OUT = DATA / "results"

VERDICT_PASS = "pass"
VERDICT_FAIL = "fail"
VERDICT_CRITICAL = "critical_false_approval"
VERDICT_NOT_GENERATED = "not_generated"

# Belgenin güvenli tarafta kapandığını gösteren sonuçlar (reddedildi / insana yönlendirildi).
_CLOSED_PREFIXES = ("rejected", "extraction_failed")

_WS = re.compile(r"\s+")


def _norm(text: str) -> str:
    """Sızıntı araması için boşluk sadeleştirme — round-trip bir değeri satır sonuna bölebilir."""
    return _WS.sub(" ", text or "")


def _repo(mode: str, llm: str = LLM_DEFAULT, *, root: Path | None = None, **overrides):
    """Mod başına İZOLE storage kökü — modlar arası karışma sızıntı sonucunu anlamsızlaştırır.
    `root` paylaşılan kökün yerine geçer (skor kartı kendi koşu dizinini verir); `overrides` ek
    Settings alanlarıdır (skor kartı terim listelerini kapatır)."""
    root = root or DATA / "work" / f"stress-{mode}" / "storage"
    settings = build_settings(llm, storage_root=root, anonymization_mode=mode, **overrides)
    ensure_llm_ready(settings)
    return settings, StorageDocumentRepository(LocalStorageBackend(root))


def done_ids(path: Path) -> set[str]:
    if not path.exists():
        return set()
    out: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            out.add(json.loads(line)["case_id"])
        except Exception:  # noqa: BLE001
            continue
    return out


def _leaked(needles: list[str], *blobs: str | None) -> bool:
    """Yerleştirilen değerlerden herhangi biri verilen metinlerin birinde görünüyor mu?"""
    haystacks = [_norm(b) for b in blobs if b]
    for needle in needles:
        target = _norm(needle)
        if not target:
            continue
        if any(target in h for h in haystacks):
            return True
    return False


def _export_text(anon, max_bytes: int) -> str | None:
    """Anonim içeriği export PDF'ine render edip GERİ OKU — kullanıcının eline geçen byte'larda
    değerin bulunup bulunmadığı, bellekteki metinden daha güçlü bir kanıttır."""
    if anon is None:
        return None
    try:
        pdf = render_content_pdf(anon, title=EVALUATION_TITLE)
        _, extracted = extract(pdf, "export.pdf", max_bytes)
        return extracted.plain_text
    except Exception:  # noqa: BLE001 — export edilemiyorsa sızıntı da olamaz
        return None


def _verdict(case: StressCase, status: str, leaked: bool) -> str:
    if not case.generated:
        return VERDICT_NOT_GENERATED
    approved = status == DocumentStatus.APPROVED.value
    if approved and leaked:
        return VERDICT_CRITICAL          # release gate ihlali — beklenti ne olursa olsun
    if case.expected == FAIL_CLOSED:
        closed = status.startswith(_CLOSED_PREFIXES) or \
            status == DocumentStatus.NEEDS_HUMAN_REVIEW.value
        return VERDICT_PASS if closed else VERDICT_FAIL
    if status.startswith("error"):
        return VERDICT_FAIL              # beklenmeyen çökme; fail-closed sayılmaz
    return VERDICT_FAIL if leaked else VERDICT_PASS


def _process(case: StressCase, data: bytes, settings, repo,
             mode: str) -> tuple[str, bool, dict | None]:
    """(actual_status, planted_leaked, llm_audit_counts) döndürür; pipeline'a hiç girmeyen belgede
    sayımlar None'dır. İstisnalar sonuç olarak kodlanır."""
    max_bytes = settings.max_upload_mb * 1024 * 1024
    filename = f"{case.case_id}.{case.fmt}"
    try:
        doc = run_pipeline(data, filename, settings, repo, mode=mode)
    except UploadRejected as e:
        return f"rejected:{getattr(e, 'code', 'invalid')}", False, None
    except ExtractionFailed:
        return "extraction_failed", False, None
    except Exception as e:  # noqa: BLE001
        return f"error:{type(e).__name__}", False, None

    anon = repo.get_anonymized(doc.id)
    anon_text = anon.plain_text if anon is not None else ""
    leaked = _leaked(case.planted_values, anon_text, _export_text(anon, max_bytes))
    return doc.status.value, leaked, llm_audit_counts(doc)


def run_mode(mode: str, corpus: list[tuple[StressCase, bytes]], out_path: Path,
             llm: str = LLM_DEFAULT, *, root: Path | None = None,
             overrides: dict | None = None) -> Settings:
    """Stres belgelerini `out_path`'e işler (devam ettirilebilir). Her belgenin koştuğu Settings'i
    döndürür; çağıran, pipeline'ın gerçekte ne kullandığını kaydedebilsin diye."""
    settings, repo = _repo(mode, llm, root=root, **(overrides or {}))
    already = done_ids(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    todo = [(c, d) for c, d in corpus if c.case_id not in already]
    print(f"[stress/{mode}] {len(todo)} belge (atlanan: {len(already)})")

    with out_path.open("a", encoding="utf-8") as fh:
        for i, (case, data) in enumerate(todo, 1):
            t0 = time.monotonic()
            if not case.generated:
                # Üretilemeyen vaka SESSİZCE düşürülmez — gerekçesiyle kayda girer.
                status, leaked, llm_audits = "not_generated", False, None
            else:
                status, leaked, llm_audits = _process(case, data, settings, repo, mode)
            verdict = _verdict(case, status, leaked)
            rec = {
                "case_id": case.case_id, "fmt": case.fmt, "scenario": case.scenario,
                "expected": case.expected, "actual_status": status, "verdict": verdict,
                "planted_leaked": leaked,
                "architecturally_safe": case.architecturally_safe,
                "generated": case.generated, "skip_reason": case.skip_reason,
                # Temkinli ama güvenli: beklenti safe_output iken belge insana yönlendirildi.
                "over_conservative": (
                    case.expected == SAFE_OUTPUT and verdict == VERDICT_PASS
                    and (status == DocumentStatus.NEEDS_HUMAN_REVIEW.value
                         or status.startswith(_CLOSED_PREFIXES))
                ),
                # Ham değer ASLA yazılmaz — yalnızca geri döndürülemez hash.
                "planted_vhashes": [value_hash(v) for v in case.planted_values],
                # Denetim çağrıları: kaç tanesi gerçek LLM kararı aldı, kaçında LLM çöktü.
                "llm_audits": llm_audits,
                "seconds": round(time.monotonic() - t0, 2),
            }
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            fh.flush()
            if i % 10 == 0 or i == len(todo):
                print(f"  [{i}/{len(todo)}] {case.case_id} {status} → {verdict}")
    return settings


def summarize(out_path: Path) -> dict:
    rows = [json.loads(x) for x in out_path.read_text(encoding="utf-8").splitlines() if x.strip()]
    counts: dict[str, int] = {}
    by_scenario: dict[str, dict[str, int]] = {}
    for r in rows:
        counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
        slot = by_scenario.setdefault(r["scenario"], {})
        slot[r["verdict"]] = slot.get(r["verdict"], 0) + 1
    tested = [r for r in rows if not r["architecturally_safe"] and r["generated"]]
    return {
        "total": len(rows),
        "pass": counts.get(VERDICT_PASS, 0),
        "fail": counts.get(VERDICT_FAIL, 0),
        "critical_false_approval": counts.get(VERDICT_CRITICAL, 0),
        "not_generated": counts.get(VERDICT_NOT_GENERATED, 0),
        "not_generated_cases": [
            {"case_id": r["case_id"], "reason": r.get("skip_reason", "")}
            for r in rows if r["verdict"] == VERDICT_NOT_GENERATED
        ],
        # "Test edildi ve geçti" ile "mimari gereği mümkün değil" AYRI raporlanır.
        "architecturally_safe": sum(1 for r in rows if r["architecturally_safe"]),
        "architecturally_safe_scenarios": sorted(ARCHITECTURALLY_SAFE),
        "actually_tested": len(tested),
        "actually_tested_pass": sum(1 for r in tested if r["verdict"] == VERDICT_PASS),
        "over_conservative": sum(1 for r in rows if r.get("over_conservative")),
        "leaked": sum(1 for r in rows if r.get("planted_leaked")),
        "by_scenario": by_scenario,
    }


def _print_summary(mode: str, s: dict) -> None:
    print(f"\n=== stres özeti [{mode}] ===")
    print(f"  toplam            : {s['total']}")
    print(f"  geçti             : {s['pass']}")
    print(f"  kaldı             : {s['fail']}")
    print(f"  KRİTİK yanlış onay: {s['critical_false_approval']}  (release gate: 0 olmalı)")
    print(f"  üretilemedi       : {s['not_generated']}")
    for nc in s["not_generated_cases"]:
        print(f"      - {nc['case_id']}: {nc['reason']}")
    print(f"  mimari gereği güvenli : {s['architecturally_safe']} "
          f"(kanal yok — testin geçmesi bir kanıt değil)")
    print(f"  gerçekten test edilen : {s['actually_tested_pass']}/{s['actually_tested']}")
    print(f"  temkinli (insana yönlendirildi): {s['over_conservative']}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="GoldBench stres koşusu (güvenlik kapıları).")
    ap.add_argument("--mode", choices=["mapping", "destructive", "both"], default="mapping")
    ap.add_argument("--tag", default="run1", help="sonuç alt dizini taban etiketi")
    ap.add_argument("--limit", type=int, default=0, help="işlenecek maksimum belge (0 = hepsi)")
    add_llm_argument(ap)
    args = ap.parse_args(argv)
    llm_settings = build_settings(args.llm)
    try:
        ensure_llm_ready(llm_settings)
    except LLMUnavailableError as e:
        print(f"HATA: {e}")
        return 2
    print(f"LLM denetçisi: {args.llm} ({llm_settings.auditor_provider})")

    corpus = build_corpus()
    if args.limit:
        corpus = corpus[:args.limit]
    print(f"stres korpusu: {len(corpus)} belge "
          f"({sum(1 for c, _ in corpus if not c.generated)} üretilemedi)")

    critical_total = 0
    modes = ["mapping", "destructive"] if args.mode == "both" else [args.mode]
    for mode in modes:
        outdir = OUT / f"{args.tag}-{mode}"
        try:
            check_resume(outdir, args.llm)
        except LLMModeMismatchError as e:
            print(f"HATA: {e}")
            return 2
        outdir.mkdir(parents=True, exist_ok=True)
        run_cfg = {"tag": args.tag, "mode": mode, "limit": args.limit,
                   **llm_config(args.llm, llm_settings)}
        (outdir / "run_config.json").write_text(
            json.dumps(run_cfg, ensure_ascii=False, indent=2), encoding="utf-8")
        out_path = outdir / "stress.jsonl"
        run_mode(mode, corpus, out_path, llm=args.llm)
        s = summarize(out_path)
        s["llm"] = llm_config(args.llm, llm_settings)
        (outdir / "summary.json").write_text(
            json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8")
        _print_summary(mode, s)
        critical_total += s["critical_false_approval"]
        print(f"[{mode}] sonuçlar → {outdir}")

    # Release gate: tek bir kritik yanlış onay bile çıkışı başarısız yapar.
    return 1 if critical_total else 0


if __name__ == "__main__":
    raise SystemExit(main())

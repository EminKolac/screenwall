"""Faz 2 deney döngüsü ölçüm komutu — tek JSON satırı basar.

    uv run python scripts/measure_faz2.py

`data/goldbench/work` temizlenir (önceki koşunun storage'ı karışmasın), sabit örneklem üzerinde
run_gold (mapping) koşulur, sonuçlar toplanır. Deterministik: aynı kod + aynı korpus → aynı sayı.
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

TAG = "exploop"
LIMIT = 72
SPLIT = "dev,public"


def main() -> int:
    work = Path("data/goldbench/work")
    if work.exists():
        shutil.rmtree(work)
    for mode in ("mapping",):
        d = Path("data/goldbench/results") / f"{TAG}-{mode}"
        if d.exists():
            shutil.rmtree(d)

    from evaluation.goldbench.run_gold import load_gold, run_mode

    rows = load_gold({s.strip() for s in SPLIT.split(",")})
    outdir = Path("data/goldbench/results") / f"{TAG}-mapping"
    run_mode(rows, "mapping", ("pdf", "docx", "xlsx"), outdir / "results.jsonl", LIMIT)

    results = [json.loads(x) for x in (outdir / "results.jsonl").read_text(
        encoding="utf-8").splitlines() if x.strip()]
    ok = [r for r in results if r.get("result") == "processed"]

    leaked_in_export = sum(r["metrics"]["leaked_in_export"] for r in ok)
    critical_fn = sum(r["metrics"]["critical_false_negatives"] for r in ok)
    crit_recall_vals = [r["metrics"]["critical_entity_recall"] for r in ok]
    crit_recall = sum(crit_recall_vals) / len(crit_recall_vals) if crit_recall_vals else 0.0
    no_mask_viol = sum(r["metrics"]["no_mask_violations"] for r in ok)
    no_mask_total = sum(r["metrics"]["no_mask_total"] for r in ok)
    over_masking = round(no_mask_viol / no_mask_total, 4) if no_mask_total else 0.0
    mention_recall_vals = [r["metrics"]["mention_recall"] for r in ok]
    mention_recall = sum(mention_recall_vals) / len(mention_recall_vals) if mention_recall_vals \
        else 0.0

    out = {
        "documents": len(ok),
        "leaked_in_export": leaked_in_export,
        "critical_false_negatives": critical_fn,
        "combined": leaked_in_export + critical_fn,
        "critical_entity_recall": round(crit_recall, 4),
        "over_masking_rate": over_masking,
        "mention_recall": round(mention_recall, 4),
    }
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

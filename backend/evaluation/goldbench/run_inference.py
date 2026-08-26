"""Fayda koşucusu — anonim belgenin hâlâ işe yarayıp yaramadığını ölçer.

    uv run python -m evaluation.goldbench.run_inference --mode both --tag v4

Her senaryo için belge pipeline'dan geçirilir, sonra:
  - ORİJİNAL metinde kaç sorunun kanıtı var (taban)
  - ANONİM metinde kaçı hâlâ var (kalan fayda)
  → `Task Utility Retention = anon_answerable / orig_answerable`

Taban orijinalden ölçülür, soru sayısından değil: kanıtı zaten belgede olmayan bir soru sistemin
suçu değildir ve paydayı şişirip fayda skorunu haksız yere düşürürdü.

Ayrıca saldırı paketi için gereken anonim metinler burada toplanır (`attack.py` onları kullanır) —
belgeyi iki kez pipeline'dan geçirmemek için.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from app.config import Settings
from app.extraction.dispatcher import extract
from app.pipeline.runner import run_pipeline
from app.services.storage_repository import StorageDocumentRepository
from app.storage.local import LocalStorageBackend
from evaluation.goldbench.generate import DOCS
from evaluation.goldbench.inference_set import (
    INFERENCE_DIR,
    InferenceScenario,
    UtilityQuestion,
    score_utility,
)

OUT = Path("data/goldbench/results")


def load_scenarios() -> list[InferenceScenario]:
    p = INFERENCE_DIR / "scenarios.jsonl"
    if not p.exists():
        return []
    out: list[InferenceScenario] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        d = json.loads(line)
        out.append(InferenceScenario(
            scenario_id=d["scenario_id"], doc_id=d["doc_id"], domain=d["domain"],
            language=d["language"], subject_id=d["subject_id"],
            questions=[UtilityQuestion(**q) for q in d["questions"]],
            attribute_truth=d.get("attribute_truth", {})))
    return out


def _repo(sub: str):
    root = Path("data/goldbench/work") / f"inference-{sub}" / "storage"
    return Settings(storage_root=root, auditor_provider="mlx"), \
        StorageDocumentRepository(LocalStorageBackend(root))


def run_mode(scenarios: list[InferenceScenario], mode: str, fmt: str, outdir: Path,
             limit: int = 0) -> None:
    settings, repo = _repo(mode)
    outdir.mkdir(parents=True, exist_ok=True)
    out_path = outdir / "utility.jsonl"
    anon_path = outdir / "anon_texts.jsonl"  # saldırı paketi için (ham PII yok — anonim metin)
    max_bytes = settings.max_upload_mb * 1024 * 1024

    todo = scenarios[:limit] if limit else scenarios
    print(f"[{mode}] {len(todo)} senaryo")

    with out_path.open("w", encoding="utf-8") as fh, anon_path.open("w", encoding="utf-8") as af:
        for i, sc in enumerate(todo, 1):
            rec: dict = {"scenario_id": sc.scenario_id, "doc_id": sc.doc_id,
                         "domain": sc.domain, "language": sc.language, "mode": mode}
            path = DOCS / f"{sc.doc_id}.{fmt}"
            if not path.exists():
                rec.update({"result": "missing_carrier", "seconds": 0.0})
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
                continue

            t0 = time.monotonic()
            try:
                data = path.read_bytes()
                _, orig = extract(data, path.name, max_bytes)
                original_text = orig.plain_text
                doc = run_pipeline(data, path.name, settings, repo, mode=mode)
                anon = repo.get_anonymized(doc.id)
                anon_text = anon.plain_text if anon is not None else ""

                base = score_utility(sc, original_text)   # taban: kanıt orijinalde var mı
                after = score_utility(sc, anon_text)      # kalan: anonimde hâlâ var mı
                denom = base["answerable"]
                retention = round(after["answerable"] / denom, 4) if denom else None

                rec.update({
                    "result": "processed", "status": doc.status.value,
                    "questions": base["questions"],
                    "orig_answerable": base["answerable"],
                    "anon_answerable": after["answerable"],
                    "utility_retention": retention,
                    "utility_drop": None if retention is None else round(1.0 - retention, 4),
                })
                af.write(json.dumps({"scenario_id": sc.scenario_id, "doc_id": sc.doc_id,
                                     "mode": mode, "anon_text": anon_text},
                                    ensure_ascii=False) + "\n")
            except Exception as e:  # noqa: BLE001 — tek senaryo koşuyu durdurmasın
                rec.update({"result": "error", "error": type(e).__name__})
            rec["seconds"] = round(time.monotonic() - t0, 2)
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            fh.flush()
            if i % 20 == 0 or i == len(todo):
                print(f"  [{i}/{len(todo)}] {sc.scenario_id} {rec.get('result')}")

    ok = [json.loads(x) for x in out_path.read_text(encoding="utf-8").splitlines() if x.strip()]
    proc = [r for r in ok if r.get("result") == "processed" and r.get("utility_retention")
            is not None]
    if proc:
        tot_orig = sum(r["orig_answerable"] for r in proc)
        tot_anon = sum(r["anon_answerable"] for r in proc)
        print(f"[{mode}] fayda: {tot_anon}/{tot_orig} soru cevaplanabilir "
              f"→ retention {round(tot_anon / tot_orig, 4) if tot_orig else 0}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="GoldBench fayda koşusu")
    ap.add_argument("--mode", choices=["mapping", "destructive", "both"], default="mapping")
    ap.add_argument("--tag", default="v4")
    ap.add_argument("--format", default="docx", help="taşıyıcı formatı (fayda formattan bağımsız)")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args(argv)

    scenarios = load_scenarios()
    if not scenarios:
        print("Senaryo yok — önce: uv run python -c "
              "'from evaluation.goldbench.inference_set import write_scenarios; write_scenarios()'")
        return 1
    print(f"senaryo: {len(scenarios)} · format {args.format}")

    modes = ["mapping", "destructive"] if args.mode == "both" else [args.mode]
    for mode in modes:
        outdir = OUT / f"{args.tag}-inference-{mode}"
        run_mode(scenarios, mode, args.format, outdir, args.limit)
        print(f"[{mode}] sonuçlar → {outdir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""GoldBench ana koşucu — gold korpusu pipeline'dan geçirir ve skorlar.

    uv run python -m evaluation.goldbench.run_gold --mode both --tag v3

Her mod KENDİ depolama kökünü kullanır (`run_bench.py` deseni): mapping modunun meşru olarak
diskte tuttuğu layer 1-2, destructive modun taramasına karışırsa D1 sonucu anlamsız olur.

Sonuçlar JSONL'e akar ve tamamlanan id'ler atlanarak devam edilebilir — 240 belge × 3 format ×
2 mod uzun sürer, yarıda kesilebilmelidir.

Rapora ASLA ham PII yazılmaz: `MentionResult` yalnız `vhash` taşır (bkz. score.py).

Holdout mühürlemesi: `--split` varsayılanı `dev,public`. Holdout ancak açıkça `--split holdout`
denerek koşulur. Bu PROSEDÜREL bir sınırdır (aynı kişi hem geliştirici hem benchmark yazarı),
kriptografik değil — rapora bu şekilde yazılır.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from app.config import Settings
from app.export.render_pdf import render_content_pdf
from app.extraction.dispatcher import extract
from app.pipeline.runner import run_pipeline
from app.services.storage_repository import StorageDocumentRepository
from app.storage.local import LocalStorageBackend
from evaluation.corpus_bist10.verify_mode import check_destructive_mode, check_mapping_mode
from evaluation.goldbench.generate import DOCS, GOLD_DIR, HOLDOUT_GOLD_DIR
from evaluation.goldbench.schema import GoldMention
from evaluation.goldbench.score import Span, aggregate, evaluate_document

OUT = Path("data/goldbench/results")


def load_gold(splits: set[str]) -> list[dict]:
    """Gold kayıtlarını yükler. Holdout SADECE açıkça istendiğinde okunur."""
    rows: list[dict] = []
    paths = [GOLD_DIR / "gold.jsonl"]
    if "holdout" in splits:
        paths.append(HOLDOUT_GOLD_DIR / "gold.jsonl")
    for p in paths:
        if not p.exists():
            continue
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                if r["split"] in splits:
                    rows.append(r)
    return rows


def done_ids(path: Path) -> set[str]:
    if not path.exists():
        return set()
    out: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            out.add(json.loads(line)["id"])
        except Exception:  # noqa: BLE001
            continue
    return out


def _repo(sub: str):
    root = Path("data/goldbench/work") / sub / "storage"
    return Settings(storage_root=root, auditor_provider="mlx"), \
        StorageDocumentRepository(LocalStorageBackend(root))


def run_mode(rows: list[dict], mode: str, formats: tuple[str, ...], out_path: Path,
             limit: int = 0) -> None:
    settings, repo = _repo(mode)
    already = done_ids(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    max_bytes = settings.max_upload_mb * 1024 * 1024

    todo = [(r, f) for r in rows for f in formats if f"{r['doc_id']}:{f}" not in already]
    if limit:
        todo = todo[:limit]
    print(f"[{mode}] {len(todo)} belge-format (atlanan: {len(already)})")

    from app.anonymization.presidio_engine import PresidioEngine
    engine = PresidioEngine()

    with out_path.open("a", encoding="utf-8") as fh:
        for i, (row, fmt) in enumerate(todo, 1):
            rec_id = f"{row['doc_id']}:{fmt}"
            rec: dict = {"id": rec_id, "doc_id": row["doc_id"], "format": fmt,
                         "domain": row["domain"], "language": row["language"],
                         "split": row["split"], "mode": mode}
            path = DOCS / f"{row['doc_id']}.{fmt}"
            if not path.exists():
                rec.update({"result": "missing_carrier", "seconds": 0.0})
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
                continue

            t0 = time.monotonic()
            try:
                data = path.read_bytes()
                doc = run_pipeline(data, path.name, settings, repo, mode=mode)
                _, orig = extract(data, path.name, max_bytes)
                original_text = orig.plain_text
                spans = [Span(s.start, s.end, s.entity_type)
                         for s in engine.detect(original_text)]
                anon = repo.get_anonymized(doc.id)
                anon_text = anon.plain_text if anon is not None else ""

                export_text = None
                if anon is not None:
                    try:
                        pdf = render_content_pdf(anon)
                        _, ex = extract(pdf, "export.pdf", max_bytes)
                        export_text = ex.plain_text
                    except Exception:  # noqa: BLE001 — export hatası skorlamayı durdurmasın
                        export_text = None

                gold = [GoldMention.from_gold_dict(m) for m in row["mentions"]]
                results = evaluate_document(gold, original_text, spans, anon_text, export_text)
                det_chars = sum(s.length for s in spans)

                # Mod bütünlüğü (Benchmark M / D) — v2'de yazılan kontroller yeniden kullanılır.
                canary_values = [g.surface for g in gold]
                if mode == "mapping":
                    chk = check_mapping_mode(
                        doc.id, repo, canary_values=canary_values,
                        shareable_blobs={"anonymized_text": anon_text,
                                         "export_text": export_text or "",
                                         "document_json": doc.model_dump_json()})
                else:
                    chk = check_destructive_mode(doc.id, repo)

                rec.update({
                    "result": "processed", "status": doc.status.value,
                    "metrics": aggregate(results, detected_total_chars=det_chars),
                    "mentions": [r.__dict__ for r in results],
                    "mode_check": chk.safe_dict(),
                })
            except Exception as e:  # noqa: BLE001 — tek belge tüm koşuyu durdurmasın
                rec.update({"result": "error", "error": type(e).__name__})
            rec["seconds"] = round(time.monotonic() - t0, 2)
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            fh.flush()
            if i % 20 == 0 or i == len(todo):
                print(f"  [{i}/{len(todo)}] {rec_id} {rec.get('result')} {rec['seconds']}s")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="GoldBench koşusu")
    ap.add_argument("--mode", choices=["mapping", "destructive", "both"], default="mapping")
    ap.add_argument("--tag", default="v3")
    ap.add_argument("--split", default="dev,public",
                    help="virgülle: dev,public,holdout (holdout mühürlü — açıkça isteyin)")
    ap.add_argument("--formats", default="pdf,docx,xlsx")
    ap.add_argument("--limit", type=int, default=0, help="mod başına en fazla belge-format")
    args = ap.parse_args(argv)

    splits = {s.strip() for s in args.split.split(",") if s.strip()}
    formats = tuple(f.strip() for f in args.formats.split(",") if f.strip())
    rows = load_gold(splits)
    if not rows:
        print("Gold korpus bulunamadı — önce: uv run python -m evaluation.goldbench.generate")
        return 1
    if "holdout" in splits:
        print("UYARI: holdout açıldı. Sonuçları gördükten sonra yapılan her değişiklik "
              "yeni bir benchmark sürümü gerektirir (mühür bozuldu).")
    print(f"korpus: {len(rows)} belge · split {sorted(splits)} · format {list(formats)}")

    modes = ["mapping", "destructive"] if args.mode == "both" else [args.mode]
    for mode in modes:
        outdir = OUT / f"{args.tag}-{mode}"
        outdir.mkdir(parents=True, exist_ok=True)
        (outdir / "run_config.json").write_text(json.dumps({
            "tag": args.tag, "mode": mode, "splits": sorted(splits), "formats": list(formats),
            "documents": len(rows), "limit": args.limit,
            "auditor_provider": "mlx (deterministic heuristic)",
            "use_privacy_filter": Settings().use_privacy_filter,
            "anonymizer_score_threshold": Settings().anonymizer_score_threshold,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        run_mode(rows, mode, formats, outdir / "results.jsonl", args.limit)
        print(f"[{mode}] sonuçlar → {outdir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Build the balanced Part-B corpus: 30 source documents -> 90 carriers, exactly 30 pdf/30 docx/30
xlsx, all carrying the SAME content per source. See BENCHMARK_GUIDE.md §13 for the rationale (real
BIST IR filings are ~all PDF, so format balance can only come from construction, not from sources).

    uv run python -m evaluation.corpus_bist10.build_balanced

Selection rule (must match BENCHMARK_GUIDE.md §13 EXACTLY — this is what a second team rebuilds
from `corpus_manifest.jsonl` to get the identical 30 sources):
  1. Take `validity == "ok"` rows from corpus_manifest.jsonl, sorted by `id`.
  2. Find the 3 largest `doc_type` groups (by count).
  3. From each of those 3 types, take the first 10 rows (by the `id` sort) -> 30 source docs.

Each source is extracted ONCE, then that same `ExtractedContent` is re-emitted as pdf+docx+xlsx
(`evaluation/corpus_bist10/emit_carriers.py`). Carrier bytes land in the gitignored data dir;
`manifest/balanced_manifest.jsonl` (source sha256 + target format + emit rule) is repo-tracked so
the 90 carriers are reproducible byte-for-byte from the same 30 sources.
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path

from app.extraction.dispatcher import extract
from evaluation.corpus_bist10.emit_carriers import emit

DATA = Path("data/corpus_bist10")
RAW = DATA / "raw"
BALANCED = DATA / "balanced"
MANIFEST_DIR = Path("evaluation/corpus_bist10/manifest")
SOURCE_MANIFEST = MANIFEST_DIR / "corpus_manifest.jsonl"
BALANCED_MANIFEST = MANIFEST_DIR / "balanced_manifest.jsonl"

N_TYPES = 3
N_PER_TYPE = 10
FORMATS = ("pdf", "docx", "xlsx")
MAX_BYTES = 30 * 1024 * 1024


_EXTRACTABLE_FORMATS = {"pdf", "docx", "xlsx"}  # what app.extraction.dispatcher actually parses


def load_usable_sources() -> list[dict]:
    rows = [json.loads(x) for x in SOURCE_MANIFEST.read_text(encoding="utf-8").splitlines()
            if x.strip()]
    # Legacy .xls/.doc are valid, hash-verified Part-A documents (real BIST filings do publish
    # them), but the app's extractor rejects them outright (UploadRejected — unsupported format,
    # by design). Part B re-emits a source's EXTRACTED content in 3 formats, so a source the app
    # can't extract in the first place can't seed a carrier — excluded here, not silently dropped
    # later as an unexplained "missing from the manifest" gap.
    usable = [r for r in rows if r.get("validity") == "ok" and (RAW / r["filename"]).exists()
             and (r.get("format") or "").lower() in _EXTRACTABLE_FORMATS]
    usable.sort(key=lambda r: r["id"])
    return usable


def select_30(usable: list[dict]) -> list[dict]:
    """The exact rule from BENCHMARK_GUIDE.md §13 — deterministic given the same manifest.

    `top_types` is sorted by (count desc, name asc): `Counter.most_common()` alone breaks ties by
    insertion order, which would make the pick depend on incidental row order rather than only on
    `doc_type` counts. The alphabetical tie-break makes this fully order-independent.
    """
    counts = Counter(r.get("doc_type") or "other" for r in usable)
    top_types = sorted(counts, key=lambda t: (-counts[t], t))[:N_TYPES]
    by_type: dict[str, list[dict]] = defaultdict(list)
    for r in usable:
        t = r.get("doc_type") or "other"
        if t in top_types:
            by_type[t].append(r)
    chosen: list[dict] = []
    for t in top_types:
        chosen.extend(by_type[t][:N_PER_TYPE])
    return chosen


def build(argv=None) -> int:
    usable = load_usable_sources()
    if not usable:
        print("corpus_manifest.jsonl boş veya belgeler indirilmemiş — önce: "
              "uv run python -m evaluation.corpus_bist10.fetch")
        return 1
    sources = select_30(usable)
    print(f"kullanılabilir kaynak: {len(usable)}  seçilen: {len(sources)} "
          f"(hedef {N_TYPES}x{N_PER_TYPE}={N_TYPES * N_PER_TYPE})")
    if len(sources) < N_TYPES * N_PER_TYPE:
        print(f"  UYARI: hedeften az — bazı doc_type'larda {N_PER_TYPE}'dan az belge var; "
              f"raporda açıkça belirtilecek.")

    BALANCED.mkdir(parents=True, exist_ok=True)
    MANIFEST_DIR.mkdir(parents=True, exist_ok=True)

    entries: list[dict] = []
    for i, src in enumerate(sources, 1):
        try:
            data = (RAW / src["filename"]).read_bytes()
            _, content = extract(data, src["filename"], MAX_BYTES)
        except Exception as e:  # noqa: BLE001 — one bad source must not abort the whole build
            # Recorded, not silently dropped: a source_id absent from every line of the manifest
            # is indistinguishable from "never selected" — this makes the omission visible instead.
            entries.append({
                "id": f"{src['id']}-extract", "source_id": src["id"],
                "source_sha256": src.get("sha256"), "source_doc_type": src.get("doc_type"),
                "source_ticker": src.get("ticker"), "format": None,
                "source_kind": "derived_container",
                "emit_status": f"extract_failed:{type(e).__name__}",
            })
            print(f"  [{i}/{len(sources)}] {src['id']}: "
                  f"EXTRACT FAILED ({type(e).__name__}) — recorded, skipped")
            continue
        for fmt in FORMATS:
            try:
                out = emit(content, fmt)
            except Exception as e:  # noqa: BLE001 — recorded, not fatal to the whole build
                entries.append({
                    "id": f"{src['id']}-{fmt}", "source_id": src["id"],
                    "source_sha256": src.get("sha256"), "source_doc_type": src.get("doc_type"),
                    "source_ticker": src.get("ticker"), "format": fmt,
                    "source_kind": "derived_container", "emit_status": f"failed:{type(e).__name__}",
                })
                continue
            fname = f"{src['id']}.{fmt}"
            (BALANCED / fname).write_bytes(out)
            entries.append({
                "id": f"{src['id']}-{fmt}", "source_id": src["id"],
                "source_sha256": src.get("sha256"), "source_doc_type": src.get("doc_type"),
                "source_ticker": src.get("ticker"), "format": fmt, "filename": fname,
                "sha256": hashlib.sha256(out).hexdigest(), "size_bytes": len(out),
                "source_kind": "derived_container", "emit_status": "ok",
                "built_at": datetime.now(UTC).isoformat(timespec="seconds"),
            })
        if i % 10 == 0 or i == len(sources):
            print(f"  [{i}/{len(sources)}] {src['id']} -> pdf+docx+xlsx")

    with BALANCED_MANIFEST.open("w", encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")

    ok = [e for e in entries if e.get("emit_status") == "ok"]
    summary = {
        "sources": len(sources), "carriers_built": len(ok), "carriers_expected": len(sources) * 3,
        "by_format": dict(Counter(e["format"] for e in ok)),
        "by_source_doc_type": dict(Counter(e["source_doc_type"] for e in ok)),
        "failures": [e["id"] for e in entries if e.get("emit_status") != "ok"],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    print(f"manifest -> {BALANCED_MANIFEST}")
    return 0


if __name__ == "__main__":
    raise SystemExit(build())

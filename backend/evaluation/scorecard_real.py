"""Scorecard section (d): real-document track — redaction density on real BIST-10 PDFs.

These files have no ground truth, so precision/recall are NOT computed (BENCHMARK_GUIDE §5.3).
Reported instead: `redaction_density` = placeholders per 1000 extracted characters, and the
placeholder-family distribution.

Selection (deterministic): the PDFs in backend/data/corpus_bist10/raw sorted by NFC filename;
files over `--real-max-pages` pages or over the upload size limit are skipped and listed, and
the first N remaining files are measured.

Path: `ingest` (the pipeline's extractor and language detection), then the engine directly — no
allow-list, no deny-list, no auditor — so the number is the engine's own masking (plan §2.1:
reports run with the allow-list off). `--llm` does not apply here. Placeholders are counted with
`<[A-Z][A-Z_]*_\\d+>`; run_bench's `<[A-Z]+_\\d+>` misses families such as <US_BANK_NUMBER_1>.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
import unicodedata
from collections import Counter
from collections.abc import Callable
from pathlib import Path

from evaluation.scorecard_common import (
    NO_TERM_LISTS,
    SectionContext,
    median_or_none,
    term_list_record,
)

RAW = Path(__file__).resolve().parents[1] / "data" / "corpus_bist10" / "raw"
PLACEHOLDER_RE = re.compile(r"<([A-Z][A-Z_]*)_\d+>")
SELECTION_RULE = ("PDFs in data/corpus_bist10/raw sorted by NFC filename; skip files over "
                  "--real-max-pages pages or the upload size limit; measure the first N left")


def _nfc(name: str) -> str:
    return unicodedata.normalize("NFC", name)


def _pdf_pages(path: Path) -> int:
    from evaluation.corpus_bist10.run_bench import page_count

    return page_count(path, "pdf")


def _eligibility(path: Path, count: Callable[[Path], int], max_pages: int,
                 max_mb: int) -> tuple[str, int]:
    """("", pages) when the file may be measured, else (skip reason, pages)."""
    size_mb = path.stat().st_size / 1024 / 1024
    if max_mb and size_mb > max_mb:
        return f"too_large:{size_mb:.1f}MB", 0
    pages = count(path)
    if max_pages and pages > max_pages:
        return f"too_many_pages:{pages}", pages
    return "", pages


def select_real_pdfs(raw_dir: Path, n: int, *, max_pages: int, max_mb: int,
                     page_counter: Callable[[Path], int] | None = None):
    """Returns ([(path, pages)], [{"file", "reason"}]). Deterministic for a given directory."""
    count = page_counter or _pdf_pages
    pdfs = sorted((p for p in raw_dir.iterdir() if p.is_file() and p.suffix.lower() == ".pdf"),
                  key=lambda p: _nfc(p.name))
    selected: list[tuple[Path, int]] = []
    skipped: list[dict] = []
    for path in pdfs:
        if len(selected) >= n:
            break
        reason, pages = _eligibility(path, count, max_pages, max_mb)
        if reason:
            skipped.append({"file": _nfc(path.name), "reason": reason})
        else:
            selected.append((path, pages))
    return selected, skipped


def density_record(extracted_chars: int, anon_text: str) -> dict:
    families = Counter(m.group(1) for m in PLACEHOLDER_RE.finditer(anon_text))
    total = sum(families.values())
    return {
        "extracted_chars": extracted_chars,
        "placeholders": total,
        "redaction_density": round(total / (extracted_chars / 1000), 4) if extracted_chars
        else None,
        "families": dict(sorted(families.items())),
    }


def measure_pdf(path: Path, pages: int, settings, engine) -> dict:
    """One document: extract like the pipeline, mask with the bare engine, count placeholders."""
    from app.services.ingest import ingest

    data = path.read_bytes()
    rec: dict = {"file": _nfc(path.name), "sha256_16": hashlib.sha256(data).hexdigest()[:16],
                 "pages": pages}
    t0 = time.monotonic()
    try:
        doc, content = ingest(data, path.name, settings)
        text = content.plain_text
        anon = engine.anonymize(content, doc.language).content.plain_text if text.strip() else ""
        rec.update(result="processed", language=getattr(doc.language, "value", str(doc.language)),
                   **density_record(len(text), anon))
    except Exception as e:  # noqa: BLE001 — one document must not stop the track
        rec.update(result="error", error=type(e).__name__)
    rec["seconds"] = round(time.monotonic() - t0, 2)
    return rec


def summarize_real(recs: list[dict]) -> dict:
    measured = [r for r in recs if r.get("result") == "processed" and r.get("extracted_chars")]
    chars = sum(r["extracted_chars"] for r in measured)
    placeholders = sum(r["placeholders"] for r in measured)
    families: Counter = Counter()
    for r in measured:
        families.update(r["families"])
    return {
        "documents": len(recs),
        "measured": len(measured),
        "errors": sum(1 for r in recs if r.get("result") == "error"),
        "empty_extraction": sum(1 for r in recs
                                if r.get("result") == "processed" and not r.get("extracted_chars")),
        "extracted_chars": chars,
        "placeholders": placeholders,
        "redaction_density": round(placeholders / (chars / 1000), 4) if chars else None,
        "redaction_density_median_doc": median_or_none(r["redaction_density"] for r in measured),
        "families": dict(families.most_common()),
        "family_share": {k: round(v / placeholders, 4) for k, v in families.most_common()}
        if placeholders else {},
        "median_seconds_per_file": median_or_none(
            r["seconds"] for r in recs if r.get("result") == "processed"),
    }


def run_real_section(ctx: SectionContext) -> dict:
    from app.anonymization.presidio_engine import PresidioEngine
    from evaluation.llm_flag import build_settings

    n = min(ctx.real, ctx.limit) if ctx.limit else ctx.real
    settings = build_settings("off", storage_root=ctx.work_dir / "storage", **NO_TERM_LISTS)
    selected, skipped = select_real_pdfs(RAW, n, max_pages=ctx.real_max_pages,
                                         max_mb=settings.max_upload_mb)
    engine = PresidioEngine()
    recs = [measure_pdf(path, pages, settings, engine) for path, pages in selected]
    out = ctx.work_dir / "real.jsonl"
    out.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in recs),
                   encoding="utf-8")
    summary = summarize_real(recs)
    return {
        **summary,
        "requested": ctx.real,
        # every requested document selected AND measured without an error
        "complete": len(recs) == ctx.real and summary["errors"] == 0,
        "skipped": skipped,
        "selection_rule": SELECTION_RULE,
        "max_pages": ctx.real_max_pages,
        "path": "ingest + engine.anonymize (no allow-list, no deny-list, no auditor)",
        # measure_pdf calls engine.anonymize(content, language): no list.
        "term_lists": term_list_record(
            [], [], "engine.anonymize without extra_allow_terms / extra_deny_terms "
                    "(evaluation/scorecard_real.py)"),
        "llm": "n/a (engine only)",
        "per_document": recs,
        "raw_results": str(out),
    }

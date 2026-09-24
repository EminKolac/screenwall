"""Shared pieces of the scorecard (`evaluation/scorecard.py`): section context and helpers."""
from __future__ import annotations

import hashlib
import json
import statistics
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

# qwen3.5:4b takes ~5-7 s per file; the heuristic auditor alone ~0.1 s. A median under this
# threshold with --llm on means the LLM most likely did not run.
LLM_PLAUSIBLE_MIN_SECONDS = 1.0


@dataclass(frozen=True)
class SectionContext:
    llm: str             # "on" | "off" — only the gold and stress sections run the auditor
    limit: int           # 0 = full run; N = first N items of every panel (smoke runs)
    real: int            # real PDFs to measure in the real-document track (0 = skip it)
    real_max_pages: int  # real track: PDFs with more pages are skipped (0 = no limit)
    corpus: Path         # bist10-benchmark root (goldbench-holdout, probes, stress files)
    work_dir: Path       # this section's git-ignored scratch dir for raw per-item outputs


def vhash(value: str) -> str:
    """BENCHMARK_GUIDE §7: the first 16 hex chars of sha256(value). A value may appear in a
    report only in this form."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def frac(numerator: int, denominator: int) -> dict:
    """Count pair with its rate; an empty denominator gives rate None, never 0 or 1."""
    rate = round(numerator / denominator, 4) if denominator else None
    return {"numerator": numerator, "denominator": denominator, "rate": rate}


def as_frac(value: dict) -> dict:
    """Normalise a scorer `fraction()` dict (unrounded rate) to `frac`."""
    return frac(value["numerator"], value["denominator"])


def median_or_none(values: Iterable) -> float | None:
    vals = [float(v) for v in values if v is not None]
    return round(statistics.median(vals), 3) if vals else None


def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def llm_evidence(llm: str, median_seconds: float | None) -> dict | None:
    """Did the LLM auditor really run? Judged from per-file time. None when the flag is off."""
    if llm != "on":
        return None
    plausible = median_seconds is not None and median_seconds >= LLM_PLAUSIBLE_MIN_SECONDS
    return {
        "median_seconds_per_file": median_seconds,
        "plausible": plausible,
        "expected": "~5-7 s/file with qwen3.5:4b; ~0.1 s/file without an LLM",
    }

"""Fable scorecard — one command, four measurements, one JSON + Markdown report.

    cd backend && uv run python -m evaluation.scorecard --tag base                        # fast
    cd backend && uv run python -m evaluation.scorecard --llm on --real 30 --tag full     # full
    cd backend && uv run python -m evaluation.scorecard --sections strict --limit 2 --tag smoke

Sections (`--sections`, default all):
  gold   (a) Fable's own GoldBench scorer on the 60-document holdout (pdf+docx+xlsx), plus the
             v5 20-document subset (`scorecard_sections.V5_SUBSET_IDS` documents how it arose).
  strict (b) V2's strict scorer (`evaluation/strict`, sha-pinned); engine WITHOUT any allow-list.
  stress (c) the 72 pinned stress files through the full pipeline, `--llm on|off`.
  real   (d) `--real N` real BIST-10 PDFs: redaction density + placeholder families.

No number depends on a term list: gold and stress run the pipeline with `term_lists=False` and
empty ALLOW_TERMS / DENY_TERMS in a storage root of their own under data/scorecard/<run id>/, and
every section records the lists its engine got (0/0 + sha256).

`complete` is true only when all four sections ran in full: no `--limit`, none skipped (a
`--sections` subset or `--real 0` names what was skipped under `skipped`), no error.

Output: evaluation/results/<YYYY-MM-DD>-<tag>/scorecard.{json,md} — counts, rates and vhashes
only, scanned before anything is written against every known synthetic value: the maskable
surfaces of the holdout the gold section scores plus V2's corpus (gold must_mask, canaries,
stress planted values). Per-item raw outputs go to data/scorecard/<run id>/ (git-ignored). An
existing run id is never overwritten; "-2", "-3", … is appended instead.

Exit codes: 0 ok · 1 a section failed · 2 bad setup (e.g. --llm on, model unreachable; term
lists not off; the raw-value guard has no value to check) · 3 refused to write because a raw
value reached the report or the guard checked nothing.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import subprocess
import sys
import time
import traceback
from datetime import date, datetime
from pathlib import Path

from evaluation.llm_flag import (
    LLMUnavailableError,
    add_llm_argument,
    build_settings,
    ensure_llm_ready,
    llm_config,
)
from evaluation.scorecard_common import (
    LLM_SECTIONS,
    NO_TERM_LISTS,
    SectionContext,
    TermListsActiveError,
    pipeline_term_lists,
    vhash,
)
from evaluation.scorecard_real import run_real_section
from evaluation.scorecard_report import evaluate_gates, render_markdown
from evaluation.scorecard_sections import (
    load_holdout_rows,
    run_gold_section,
    run_stress_section,
    run_strict_section,
)

SCHEMA = "fable-scorecard/1"
SECTIONS = ("gold", "strict", "stress", "real")
BACKEND = Path(__file__).resolve().parents[1]
RESULTS_ROOT = BACKEND / "evaluation" / "results"
WORK_ROOT = BACKEND / "data" / "scorecard"
DEFAULT_CORPUS = Path(os.environ.get("FABLE_BENCH_CORPUS", str(Path.home() / "bist10-benchmark")))
CORPUS_FILES = ("goldbench-holdout.json", "probes.json", "stress-manifest.json")
# Same pinning V2 applies to the text runs; set before any app import so every section runs
# offline with the Privacy Filter off.
OFFLINE_ENV = {"HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "USE_PRIVACY_FILTER": "false"}
MIN_SCAN_LENGTH = 6  # shorter values collide with ordinary words/ids; V2 stress uses the same bound
EXIT_OK, EXIT_SECTION_ERROR, EXIT_SETUP, EXIT_RAW_VALUE = 0, 1, 2, 3


class RawValueLeakError(RuntimeError):
    def __init__(self, vhashes: list[str]) -> None:
        super().__init__(f"raw values in report (vhash {', '.join(vhashes)})")
        self.vhashes = vhashes


class EmptyGuardError(RuntimeError):
    """The raw-value guard has no value to check, so a clean scan would prove nothing."""


def default_runners() -> dict:
    return {"gold": run_gold_section, "strict": run_strict_section,
            "stress": run_stress_section, "real": run_real_section}


# ------------------------------------------------------------------------------------ CLI

def _tag(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", value):
        raise argparse.ArgumentTypeError("tag: letters, digits, '.', '_', '-' (max 64)")
    return value


def _non_negative(value: str) -> int:
    n = int(value)
    if n < 0:
        raise argparse.ArgumentTypeError("must be >= 0")
    return n


def _sections(value: str) -> tuple[str, ...]:
    wanted = {s.strip() for s in value.split(",") if s.strip()}
    unknown = wanted - set(SECTIONS)
    if unknown or not wanted:
        raise argparse.ArgumentTypeError(f"choose from {','.join(SECTIONS)}")
    return tuple(s for s in SECTIONS if s in wanted)


def parse_args(argv=None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Fable scorecard (gold, strict, stress, real).")
    ap.add_argument("--tag", type=_tag, default="run", help="run id suffix: <date>-<tag>")
    add_llm_argument(ap)
    ap.add_argument("--real", type=_non_negative, default=0,
                    help="real BIST-10 PDFs to measure (0 = skip the real-document track)")
    ap.add_argument("--real-max-pages", type=_non_negative, default=60,
                    help="real track: skip PDFs with more pages (0 = no limit)")
    ap.add_argument("--sections", type=_sections, default=SECTIONS,
                    help=f"comma-separated subset of {','.join(SECTIONS)}")
    ap.add_argument("--limit", type=_non_negative, default=0,
                    help="smoke runs: first N items of every panel (0 = full run)")
    ap.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS,
                    help="bist10-benchmark directory (env FABLE_BENCH_CORPUS)")
    return ap.parse_args(argv)


# ---------------------------------------------------------------------------- orchestration

def allocate_run_id(tag: str, results_root: Path, work_root: Path,
                    today: date | None = None) -> str:
    base = f"{(today or date.today()).isoformat()}-{tag}"
    run_id, n = base, 1
    while (results_root / run_id).exists() or (work_root / run_id).exists():
        n += 1
        run_id = f"{base}-{n}"
    return run_id


def _run_one(name: str, ctx: SectionContext, runner) -> dict:
    print(f"[scorecard] {name} …", flush=True)
    t0 = time.monotonic()
    if name == "real" and ctx.real <= 0:
        data = {"status": "skipped", "reason": "--real 0"}
    else:
        try:
            ctx.work_dir.mkdir(parents=True, exist_ok=True)
            data = {**runner(ctx), "status": "ok"}  # the envelope key always wins
        except Exception as e:  # noqa: BLE001 — one failed section must not hide the others
            traceback.print_exc()  # console only; the report keeps just the exception type
            data = {"status": "error", "error": type(e).__name__}
    data["elapsed_seconds"] = round(time.monotonic() - t0, 2)
    print(f"[scorecard] {name}: {data['status']} ({data['elapsed_seconds']} s)", flush=True)
    return data


def run_sections(opts: argparse.Namespace, runners: dict, work_dir: Path) -> dict:
    return {name: _run_one(name, SectionContext(
        llm=opts.llm, limit=opts.limit, real=opts.real, real_max_pages=opts.real_max_pages,
        corpus=opts.corpus, work_dir=work_dir / name), runners[name]) for name in opts.sections}


def preflight(opts: argparse.Namespace) -> str | None:
    """Stop before any work when a measurement could not be honest: `--llm on` with the model
    unreachable, or the pipeline still assembling a term list with `NO_TERM_LISTS` applied."""
    if opts.llm == "on" and set(LLM_SECTIONS) & set(opts.sections):
        try:
            ensure_llm_ready(build_settings("on"))
        except LLMUnavailableError as e:
            return str(e)
    try:
        pipeline_term_lists(build_settings("off", **NO_TERM_LISTS))
    except TermListsActiveError as e:
        return f"term lists are not off: {e}"
    return None


def skipped_sections(opts: argparse.Namespace, sections: dict) -> list[dict]:
    """Exactly what this run did not measure, in section order."""
    out = []
    for name in SECTIONS:
        if name not in sections:
            out.append({"section": name, "reason": "not in --sections"})
        elif sections[name]["status"] == "skipped":
            out.append({"section": name, "reason": sections[name].get("reason", "skipped")})
    return out


# ------------------------------------------------------------------------------- metadata

def display_path(path) -> str:
    p = Path(path)
    try:
        return str(p.resolve().relative_to(BACKEND))
    except ValueError:
        return str(p).replace(str(Path.home()), "~", 1)


def git_meta(repo: Path) -> dict:
    def git(*args: str) -> str | None:
        try:
            r = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True,
                               timeout=10)
        except (OSError, subprocess.SubprocessError):
            return None
        return r.stdout.strip() if r.returncode == 0 else None

    status = git("status", "--porcelain")
    return {"commit": git("rev-parse", "HEAD"), "branch": git("rev-parse", "--abbrev-ref", "HEAD"),
            "uncommitted_paths": None if status is None else len(status.splitlines())}


CACHE_DIRS = frozenset({"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"})
CACHE_FILES = frozenset({".DS_Store"})


def source_fingerprint(root: Path, pattern: str = "*.py", *,
                       exclude_top: frozenset[str] = frozenset()) -> str | None:
    """One sha256 over every `root/**/pattern` file (relative path + content hash), skipping
    caches and the top-level directories in `exclude_top`: identifies the code measured."""
    if not root.is_dir():
        return None
    h = hashlib.sha256()
    for p in sorted(root.rglob(pattern)):
        rel = p.relative_to(root)
        if (not p.is_file() or rel.parts[0] in exclude_top or p.name in CACHE_FILES
                or p.suffix == ".pyc" or CACHE_DIRS.intersection(rel.parts)):
            continue
        digest = hashlib.sha256(p.read_bytes()).hexdigest()
        h.update(f"{rel.as_posix()}\0{digest}\n".encode())
    return h.hexdigest()


def _corpus_hashes(corpus: Path) -> dict:
    return {name: hashlib.sha256((corpus / name).read_bytes()).hexdigest()
            if (corpus / name).is_file() else None for name in CORPUS_FILES}


def collect_config(opts: argparse.Namespace) -> dict:
    return {
        "tag": opts.tag, "llm": opts.llm, "sections": list(opts.sections), "limit": opts.limit,
        # --llm only reaches the auditor in these sections; empty = the flag had no effect
        "llm_applies_to": [s for s in opts.sections if s in LLM_SECTIONS],
        "real": opts.real, "real_max_pages": opts.real_max_pages,
        "corpus": display_path(opts.corpus), "corpus_sha256": _corpus_hashes(opts.corpus),
        "llm_settings": llm_config(opts.llm, build_settings(opts.llm)),
        "pipeline_settings_overrides": dict(NO_TERM_LISTS),
        "env": dict(OFFLINE_ENV), "python": platform.python_version(),
        "git": git_meta(BACKEND.parent), "app_source_sha256": source_fingerprint(BACKEND / "app"),
        # all files under evaluation/ except results/ (scorecard output) and caches
        "evaluation_source_sha256": source_fingerprint(
            BACKEND / "evaluation", "*", exclude_top=frozenset({"results"})),
    }


def assemble(opts, run_id: str, started: datetime, sections: dict, work_dir: Path) -> dict:
    for data in sections.values():
        if "raw_results" in data:
            data["raw_results"] = display_path(data["raw_results"])
    skipped = skipped_sections(opts, sections)
    # Partial runs never pass as complete: every section ran, in full, without an error.
    complete = opts.limit == 0 and not skipped and all(
        s["status"] == "ok" and s.get("complete") is True for s in sections.values())
    return {
        "schema": SCHEMA, "run_id": run_id,
        "started_at": started.isoformat(timespec="seconds"),
        "finished_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "complete": complete,
        "skipped": skipped,
        "config": collect_config(opts),
        "gates": evaluate_gates(sections, opts.llm),
        "sections": sections,
        "work_dir": display_path(work_dir),
    }


# ------------------------------------------------------------------------ raw-value guard

def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def _scannable(values: set[str]) -> set[str]:
    return {v for v in values if len(v.strip()) >= MIN_SCAN_LENGTH}


def v2_corpus_values(corpus: Path) -> set[str]:
    """V2's corpus (strict + stress sections): gold must_mask surfaces, canary values and stress
    planted values."""
    values: set[str] = set()
    for case in _read_json(corpus / "goldbench-holdout.json") or []:
        values.update(m["surface"] for m in case.get("must_mask", []))
    probes = _read_json(corpus / "probes.json") or {}
    values.update(c["value"] for c in probes.get("canaries", []))
    for m in _read_json(corpus / "stress-manifest.json") or []:
        values.update(m.get("planted_values", []))
    return _scannable(values)


def holdout_gold_values(rows: list[dict]) -> set[str]:
    """The gold section's holdout: every maskable mention surface. NO_MASK terms are ordinary
    business words a report may legitimately contain, so they are not scanned."""
    return _scannable({m["surface"] for r in rows for m in r.get("mentions", [])
                       if m.get("identifier_class") != "NO_MASK"})


def known_synthetic_values(corpus: Path) -> tuple[list[str], dict[str, int]]:
    """(values, count per source): every synthetic value either corpus plants. None of them may
    appear in a report."""
    sources = {"goldbench_holdout": holdout_gold_values(load_holdout_rows()),
               "v2_corpus": v2_corpus_values(corpus)}
    values = set().union(*sources.values())
    return sorted(values), {name: len(vals) for name, vals in sources.items()}


def find_raw_values(texts: list[str], values: list[str]) -> list[str]:
    """vhashes (never the values) of known raw values present in any text."""
    return sorted({vhash(v) for v in values if any(v in t for t in texts)})


def write_outputs(card: dict, markdown: str, out_dir: Path, values: list[str]) -> None:
    if not values:
        raise EmptyGuardError("the raw-value guard has no value to check")
    text = json.dumps(card, ensure_ascii=False, indent=2) + "\n"
    hits = find_raw_values([text, markdown], values)
    if hits:
        raise RawValueLeakError(hits)
    out_dir.mkdir(parents=True, exist_ok=False)
    (out_dir / "scorecard.json").write_text(text, encoding="utf-8")
    (out_dir / "scorecard.md").write_text(markdown, encoding="utf-8")


# ----------------------------------------------------------------------------------- main

def _execute(opts, runners: dict, results_root: Path, work_root: Path) -> int:
    problem = preflight(opts)
    if problem:
        print(f"[scorecard] {problem}", file=sys.stderr)
        return EXIT_SETUP
    values, per_source = known_synthetic_values(opts.corpus)
    if not values:  # before any work: a guard with nothing to check would prove nothing
        print("[scorecard] the raw-value guard has no value to check: holdout gold "
              "(data/goldbench/holdout_gold/gold.jsonl) and --corpus both missing or empty",
              file=sys.stderr)
        return EXIT_SETUP
    run_id = allocate_run_id(opts.tag, results_root, work_root)
    work_dir = work_root / run_id
    work_dir.mkdir(parents=True)
    started = datetime.now().astimezone()
    card = assemble(opts, run_id, started, run_sections(opts, runners, work_dir), work_dir)
    card["pii_scan"] = {"values_checked": len(values), "sources": per_source,
                        "min_length": MIN_SCAN_LENGTH, "hits": 0}
    try:
        write_outputs(card, render_markdown(card), results_root / run_id, values)
    except (RawValueLeakError, EmptyGuardError) as e:
        print(f"[scorecard] REFUSED to write the report: {e}", file=sys.stderr)
        return EXIT_RAW_VALUE
    print(f"[scorecard] → {display_path(results_root / run_id)}/scorecard.md")
    for g in card["gates"]:
        print(f"  {g['verdict']:<12} {g['gate']}: {g['value'] if g['value'] is not None else '—'}")
    failed = any(s["status"] == "error" for s in card["sections"].values())
    return EXIT_SECTION_ERROR if failed else EXIT_OK


def main(argv=None, *, runners: dict | None = None, results_root: Path = RESULTS_ROOT,
         work_root: Path = WORK_ROOT) -> int:
    opts = parse_args(argv)
    os.environ.update(OFFLINE_ENV)
    cwd = Path.cwd()
    os.chdir(BACKEND)  # the reused runners resolve data/… relative to backend/
    try:
        return _execute(opts, runners or default_runners(), results_root, work_root)
    finally:
        os.chdir(cwd)


if __name__ == "__main__":
    raise SystemExit(main())

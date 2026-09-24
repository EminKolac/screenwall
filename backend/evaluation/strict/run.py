"""Run fixed Fable text panels through the strict scorer (V2 `benchmark/run.py`, adapted).

Upstream: screenwall-v2 `benchmark/run.py`, sha256 41c382a0…f43. The only changes:
  1. `evaluation.strict.scorer` (byte-identical copy) replaces `benchmark.scorer`.
  2. `--system fable` imports THIS repo's engine through the normal package path; V2's
     `--reference` + `sys.path` insert are gone. `--system studio` needs V2's own engine and is
     refused here.
  3. `--privacy-mode` defaults to `mapping`, the only mode the fable adapter supports.
  4. `--out` is accepted as an alias of V2's `--output`.
  5. `--limit N` keeps the first N items of every panel (smoke runs only); the summary then says
     `complete: false` and must not be compared with full runs.
  6. The body is `run_strict()` so the scorecard can call it in-process; the socket guard is
     restored when it returns.

Unchanged: panels, prompts, scorer calls, output files, offline env vars and the loopback-only
socket guard. As in V2 the engine is called WITHOUT any allow-list
(`anonymize(content, Language.mixed)`), so must_keep and the neutral probe measure the engine's
own over-masking.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import socket
import time
from pathlib import Path

from evaluation.strict.scorer import escape, fraction, gold_case, summarize_gold

BACKEND = Path(__file__).resolve().parents[2]
UPSTREAM_RUN_SHA256 = "41c382a0a8fd4e23c461c62273b2e5e0ec6f507bff3552f2cd93d778ad43f943"
CORPUS_FILES = ("goldbench-holdout.json", "stress-manifest.json", "probes.json")
DISCLOSURE = (
    "Text detector measurement, not shipped output. No Qwen approval simulated. "
    "Known holdout; not independent generalization. PF disabled in both systems. "
    "No detector tuning performed against these results."
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _head(items: list, limit: int) -> list:
    return items[:limit] if limit else items


def _block_external_network():
    """V2's in-process guard: loopback connections only. Returns a callable that undoes it."""
    original_connect = socket.socket.connect

    def local_only(sock, address):
        if isinstance(address, tuple) and address[0] not in {"127.0.0.1", "::1", "localhost"}:
            raise RuntimeError("external_network_forbidden")
        return original_connect(sock, address)

    socket.socket.connect = local_only

    def restore() -> None:
        socket.socket.connect = original_connect

    return restore


def _fable_anonymizer():
    """The engine exactly as V2 called it: one DOCX block, Language.mixed, no allow/deny lists."""
    from app.anonymization.presidio_engine import PresidioEngine as Engine
    from app.extraction.base import Block, ExtractedContent
    from app.models.document import FileKind, Language

    engine = Engine()

    def anonymize(text):
        content = ExtractedContent(kind=FileKind.docx, blocks=[Block(block_id="b1", text=text)])
        return engine.anonymize(content, Language.mixed).content.plain_text

    return anonymize


def _gold_panel(anonymize, cases: list, raw: list) -> list:
    gold = []
    for i, case in enumerate(cases, 1):
        try:
            output = anonymize(case["text"])
        except Exception:
            output = None
        raw.append({"id": case["id"], "text": output})
        gold.append(gold_case(case, output))
        if i % 20 == 0:
            print(f"Gold {i}/{len(cases)}", flush=True)
    return gold


def _probe_panel(anonymize, canaries: list, raw: list) -> list:
    rows = []
    for index, canary in enumerate(canaries):
        value = canary["value"]
        for variant, prompt in [
            ("bare", f"Ref0007 {value}"),
            ("contextual", f"{canary['context_word']} {value}"),
        ]:
            try:
                output = anonymize(prompt)
                missed = any(escape(value, output))
                error = False
            except Exception:
                output, missed, error = None, True, True
            rows.append({"index": index, "variant": variant, "missed": missed,
                         "critical": canary["critical"], "unprocessed": error})
            raw.append({"id": f"probe-{index}-{variant}", "text": output})
    return rows


def _over_panel(anonymize, sentences: list, raw: list) -> list:
    over = []
    for i, sentence in enumerate(sentences):
        try:
            output = anonymize(sentence)
        except Exception:
            output = None
        over.append({"index": i, "changed": output != sentence, "unprocessed": output is None})
        raw.append({"id": f"over-{i}", "text": output})
    return over


def _summary(corpus: Path, panels: dict, n_canaries: int, start: float, limit: int) -> dict:
    probe_rows, over = panels["probes"], panels["over"]
    summary = {
        "system": "fable",
        "privacy_mode": "mapping",
        "gold": summarize_gold(panels["gold"]),
        "probes": {
            variant: fraction(
                sum(r["missed"] for r in probe_rows if r["variant"] == variant), n_canaries)
            for variant in ("bare", "contextual")
        },
        "over_mask_sentences": fraction(sum(r["changed"] for r in over), len(over)),
        "seconds": round(time.monotonic() - start, 2),
        "candidate": True,
        "disclosure": DISCLOSURE,
        "corpus_sha256": {name: _sha256(corpus / name) for name in CORPUS_FILES},
        "scorer_sha256": _sha256(Path(__file__).with_name("scorer.py")),
    }
    summary["source_sha256"] = {
        str(path.relative_to(BACKEND)): _sha256(path)
        for path in sorted((BACKEND / "app").rglob("*.py"))
    }
    summary["external_network"] = "blocked"
    summary["allow_list"] = "none (engine called directly, no extra_allow_terms)"
    summary["limit"] = limit
    summary["complete"] = limit == 0
    summary["upstream_run_sha256"] = UPSTREAM_RUN_SHA256
    return summary


def _write(out: Path, summary: dict, panels: dict, raw: list) -> None:
    for filename, data in [
        ("metrics.json", summary),
        ("gold-safe.json", panels["gold"]),
        ("probe-safe.json", panels["probes"]),
        ("over-safe.json", panels["over"]),
    ]:
        (out / filename).write_text(json.dumps(data, ensure_ascii=False, indent=2),
                                    encoding="utf-8")
    # Separate synthetic measurement artifacts for independent scorer reproduction; excluded
    # from Git, never a report or a production release. Contains only provided synthetic data.
    artifact = out / "SYNTHETIC-MEASUREMENT-ONLY.json"
    artifact.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    artifact.chmod(0o600)


def run_strict(corpus: Path, out: Path, *, system: str = "fable",
               privacy_mode: str = "mapping", limit: int = 0) -> dict:
    """Run the three panels, write V2's output files into `out` (must not exist), return the
    summary (`metrics.json`)."""
    if system != "fable":
        raise ValueError("only --system fable is available in this repo")
    if privacy_mode != "mapping":
        raise ValueError(
            "Reference adapter only supports mapping; refusing a misleading mode label.")
    if out.exists():
        raise FileExistsError("Run ID already exists; choose a separate empty output directory.")
    os.environ.update(HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", USE_PRIVACY_FILTER="false")
    restore = _block_external_network()
    try:
        anonymize = _fable_anonymizer()
        out.mkdir(parents=True)
        raw: list = []
        start = time.monotonic()
        cases = json.loads((corpus / "goldbench-holdout.json").read_text(encoding="utf-8"))
        probes = json.loads((corpus / "probes.json").read_text(encoding="utf-8"))
        canaries = _head(probes["canaries"], limit)
        panels = {
            "gold": _gold_panel(anonymize, _head(cases, limit), raw),
            "probes": _probe_panel(anonymize, canaries, raw),
            "over": _over_panel(anonymize, _head(probes["over_mask_sentences"], limit), raw),
        }
        summary = _summary(corpus, panels, len(canaries), start, limit)
        _write(out, summary, panels, raw)
    finally:
        restore()
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description="Strict text-panel run (V2 benchmark/run.py).")
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--out", "--output", dest="out", type=Path, required=True,
                        help="new, empty output directory (existing directories are refused)")
    parser.add_argument("--privacy-mode", choices=["mapping", "destruction"], default="mapping")
    parser.add_argument("--system", choices=["studio", "fable"], default="fable")
    parser.add_argument("--limit", type=int, default=0,
                        help="smoke runs only: first N items of every panel (0 = all)")
    args = parser.parse_args(argv)
    if args.system == "studio":
        parser.error("--system studio needs Screenwall V2's own engine; use V2 benchmark/run.py.")
    if args.privacy_mode != "mapping":
        parser.error("Reference adapter only supports mapping; refusing a misleading mode label.")
    if args.limit < 0:
        parser.error("--limit must be >= 0")
    if args.out.exists():
        raise SystemExit("Run ID already exists; choose a separate empty output directory.")
    summary = run_strict(args.corpus, args.out, limit=args.limit)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

"""Engine parity snapshots (Faz 1).

Captures the anonymization engine's output over a fixed corpus so that a refactored engine can be
proven to behave identically. Run once BEFORE changing the engine, then compare after:

    cd backend
    uv run python -m tests.parity.capture --out tests/parity/snapshots      # baseline
    uv run python -m tests.parity.capture --out /tmp/new --compare tests/parity/snapshots

Each document is anonymized twice: with the seeded allow-list (production path) and without it
(engine level). Mapping values are stored as hashes; for the real public documents the
masked texts are hashed too, to keep snapshots small.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

from app.anonymization.allowlist_tr import default_allow_list
from app.anonymization.presidio_engine import PresidioEngine
from app.extraction.base import (
    Block,
    BlockType,
    ExtractedContent,
    ExtractionFailed,
    UploadRejected,
)
from app.extraction.dispatcher import extract
from app.language.detector import detect_content_language
from app.models.document import FileKind

BENCH = Path("/Users/mehmetkolac/bist10-benchmark")
BACKEND = Path(__file__).resolve().parents[2]
GOLD_DOCS = BACKEND / "data" / "goldbench" / "docs"
REAL_DOCS = BACKEND / "data" / "corpus_bist10" / "raw"
EXTRA_REAL = [Path("/Users/mehmetkolac/Downloads/PowerPoint Sunusu.pdf")]
MAX_BYTES = 50 * 1024 * 1024


def _h(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _units(content: ExtractedContent) -> dict[str, str]:
    out: dict[str, str] = {}
    for b in content.blocks:
        if b.type == BlockType.table:
            for c in b.cells:
                out[f"{b.block_id}:r{c.row}c{c.col}"] = c.text
        else:
            out[b.block_id] = b.text
    return out


def _text_content(texts: list[str]) -> ExtractedContent:
    blocks = [Block(block_id=f"p{i}", type=BlockType.paragraph, text=t)
              for i, t in enumerate(texts)]
    return ExtractedContent(kind=FileKind.docx, blocks=blocks)


def _load(path: Path) -> ExtractedContent:
    return extract(path.read_bytes(), path.name, MAX_BYTES)[1]


def corpus() -> dict[str, list[tuple[str, callable]]]:
    """name -> [(doc_id, loader returning ExtractedContent)]"""
    sets: dict[str, list] = {"stress": [], "gold": [], "probes": [], "real": []}
    for p in sorted((BENCH / "stress-corpus").iterdir()):
        if p.suffix in (".pdf", ".docx", ".xlsx"):
            sets["stress"].append((p.name, lambda p=p: _load(p)))
    for ext in ("pdf", "docx", "xlsx"):
        files = sorted(GOLD_DOCS.glob(f"*.{ext}"))
        for p in files[::24][:10]:
            sets["gold"].append((p.name, lambda p=p: _load(p)))
    probes = json.loads((BENCH / "probes.json").read_text(encoding="utf-8"))
    for i, s in enumerate(probes["over_mask_sentences"]):
        sets["probes"].append((f"neutral-{i:02d}", lambda s=s: _text_content([s])))
    for c in probes["canaries"]:
        sets["probes"].append((f"canary-{c['id']}-bare", lambda c=c: _text_content([c["value"]])))
        sets["probes"].append((f"canary-{c['id']}-ctx",
                               lambda c=c: _text_content([f"{c['context_word']} {c['value']}"])))
    reals = sorted(REAL_DOCS.glob("*.pdf"), key=lambda p: p.stat().st_size)[:5] + EXTRA_REAL
    for p in reals:
        if p.exists():
            sets["real"].append((p.name, lambda p=p: _load(p)))
    return sets


def run_one(engine: PresidioEngine, content: ExtractedContent, allow: list[str],
            hashed: bool) -> dict:
    lang = detect_content_language(content)
    out = engine.anonymize(content, lang, extra_deny_terms=[], extra_allow_terms=allow)
    units = _units(out.content)
    # Mapping values are always hashed: the stress corpus plants synthetic secrets (e.g. a
    # Stripe-shaped key) that must not land in the repository in clear text.
    mapping = {k: _h(v) for k, v in out.mapping.items()}
    if hashed:
        units = {k: _h(v) for k, v in units.items()}
    rec = {
        "units": units,
        "mapping": mapping,
        "entity_count": out.entity_count,
        "placeholders_used": out.placeholders_used,
    }
    return rec


def capture(out_dir: Path, only: list[str] | None) -> dict:
    engine = PresidioEngine()
    allow = default_allow_list()
    out_dir.mkdir(parents=True, exist_ok=True)
    summary = {}
    for name, docs in corpus().items():
        if only and name not in only:
            continue
        t0 = time.time()
        data: dict[str, dict] = {}
        for doc_id, load in docs:
            try:
                content = load()
            except (UploadRejected, ExtractionFailed) as e:
                # Some stress files are deliberately corrupt; the rejection itself is the behaviour.
                data[doc_id] = {"rejected": type(e).__name__}
                continue
            hashed = name == "real"
            data[doc_id] = {
                "allow": run_one(engine, content, allow, hashed),
                "noallow": run_one(engine, content, [], hashed),
            }
            if name in ("gold", "probes"):
                text = content.plain_text
                for key, al in (("detect_allow", allow), ("detect_noallow", [])):
                    spans = engine.detect(text, extra_deny_terms=[], extra_allow_terms=al)
                    data[doc_id][key] = [[s.start, s.end, s.entity_type] for s in spans]
        (out_dir / f"{name}.json").write_text(
            json.dumps(data, ensure_ascii=False, sort_keys=True, indent=0), encoding="utf-8")
        summary[name] = {"docs": len(data), "seconds": round(time.time() - t0, 1)}
        print(f"{name}: {len(data)} docs in {summary[name]['seconds']} s", flush=True)
    return summary


def compare(new_dir: Path, base_dir: Path, only: list[str] | None) -> int:
    """Print every difference; return the number of differing records."""
    diffs = 0
    for base_file in sorted(base_dir.glob("*.json")):
        name = base_file.stem
        if only and name not in only:
            continue
        base = json.loads(base_file.read_text(encoding="utf-8"))
        new_file = new_dir / base_file.name
        if not new_file.exists():
            print(f"[{name}] missing in new run")
            diffs += 1
            continue
        new = json.loads(new_file.read_text(encoding="utf-8"))
        for doc_id, runs in base.items():
            for key, rec in runs.items():
                other = new.get(doc_id, {}).get(key)
                if other != rec:
                    diffs += 1
                    _explain(name, doc_id, key, rec, other)
    print(f"parity: {diffs} differing record(s)")
    return diffs


def _explain(name: str, doc_id: str, key: str, rec, other) -> None:
    print(f"[{name}] {doc_id} :: {key}")
    if other is None:
        print("    (missing)")
        return
    if isinstance(rec, dict) and "units" in rec:
        for uid, text in rec["units"].items():
            if other["units"].get(uid) != text:
                new_text = str(other["units"].get(uid))[:160]
                print(f"    unit {uid}\n      old: {str(text)[:160]!r}\n      new: {new_text!r}")
        for field in ("mapping", "entity_count", "placeholders_used"):
            if rec[field] != other.get(field):
                print(f"    {field} differs")
    else:
        print(f"    old: {str(rec)[:300]}\n    new: {str(other)[:300]}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--compare", type=Path, default=None, help="baseline dir to compare against")
    ap.add_argument("--only", nargs="*", default=None, help="subset of: stress gold probes real")
    args = ap.parse_args(argv)
    summary = capture(args.out, args.only)
    print(json.dumps(summary))
    if args.compare:
        return 1 if compare(args.out, args.compare, args.only) else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())

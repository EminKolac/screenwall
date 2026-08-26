"""Build the fixed BIST-10 corpus: select from discovery, download, hash, de-duplicate, manifest.

    uv run python -m evaluation.corpus_bist10.fetch --max-docs 300

Selection is deterministic (sorted, capped per company) so the same discovery input always yields
the same corpus. The manifest is written to a REPO-TRACKED path so the corpus is reproducible by
anyone; the document bytes land in the gitignored data dir and are never committed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path

DATA = Path("data/corpus_bist10")          # gitignored: bytes live here
MANIFEST_DIR = Path("evaluation/corpus_bist10/manifest")  # tracked: reproducibility record
RAW = DATA / "raw"
DISCOVERY = DATA / "discovery"

# Text-rich first: the benchmark needs prose to detect names/addresses in.
FORMAT_RANK = {"pdf": 0, "docx": 1, "doc": 2, "xlsx": 3, "xls": 4}
TEXT_FORMATS = ("pdf", "docx", "doc")


def load_discovery() -> list[dict]:
    rows: list[dict] = []
    for p in sorted(DISCOVERY.glob("*.jsonl")):
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def select(rows: list[dict], max_docs: int, per_company: int, max_mb: int,
           text_only: bool) -> list[dict]:
    """Deterministic, balanced selection: text-rich formats first, capped per company."""
    max_bytes = max_mb * 1024 * 1024
    seen_url: set[str] = set()
    pool: list[dict] = []
    for r in rows:
        url = (r.get("source_url") or "").strip()
        fmt = (r.get("format") or "").lower()
        # "unverified" = discovery could not HEAD it (CDN rejects HEAD, rate limit). Keep it: the
        # download step is the real gate — it validates magic bytes and hashes every file anyway.
        if not url or url in seen_url or r.get("access") not in ("ok", "unverified"):
            continue
        if text_only and fmt not in TEXT_FORMATS:
            continue
        size = r.get("size_bytes_or_null") or 0
        if size and size > max_bytes:
            continue
        seen_url.add(url)
        pool.append(r)

    # Sort: text-rich format first, then by doc_type then name — fully deterministic.
    pool.sort(key=lambda r: (FORMAT_RANK.get((r.get("format") or "").lower(), 9),
                             r.get("doc_type") or "zz", (r.get("doc_name") or "")[:80],
                             r["source_url"]))

    # Round-robin across companies so no single issuer dominates the corpus.
    by_co: dict[str, list[dict]] = defaultdict(list)
    for r in pool:
        by_co[r.get("ticker") or r.get("company") or "?"].append(r)
    chosen: list[dict] = []
    idx = 0
    while len(chosen) < max_docs:
        added = False
        for co in sorted(by_co):
            bucket = by_co[co]
            if idx < len(bucket) and idx < per_company:
                chosen.append(bucket[idx])
                added = True
                if len(chosen) >= max_docs:
                    break
        if not added:
            break
        idx += 1
    return chosen


def url_key(url: str) -> str:
    """Stable short id from the URL. Index-independent, so adding a company later does not rename
    (and thus re-download) every existing document — the build stays resumable."""
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:8]


def doc_id(rec: dict) -> str:
    return f"{rec.get('ticker', 'X')}-{url_key(rec['source_url'])}"


def safe_name(rec: dict) -> str:
    base = f"{doc_id(rec)}_{rec.get('doc_name', 'doc')}"
    stem = re.sub(r"[^\w.\-]+", "_", base)
    return f"{stem[:90]}.{(rec.get('format') or 'bin').lower()}"


def download(url: str, dest: Path, max_bytes: int) -> tuple[str, int | None]:
    try:
        r = subprocess.run(
            ["curl", "-sSL", "--max-time", "180", "--max-filesize", str(max_bytes),
             "-o", str(dest), url], capture_output=True, timeout=200)
    except subprocess.TimeoutExpired:
        return "timeout", None
    if r.returncode != 0:
        dest.unlink(missing_ok=True)
        return f"curl_rc={r.returncode}", None
    if not dest.exists() or dest.stat().st_size == 0:
        dest.unlink(missing_ok=True)
        return "empty", None
    return "ok", dest.stat().st_size


_MAGIC = {"pdf": b"%PDF", "docx": b"PK\x03\x04", "xlsx": b"PK\x03\x04",
          "doc": b"\xd0\xcf\x11\xe0", "xls": b"\xd0\xcf\x11\xe0"}


def validate(path: Path, fmt: str) -> str:
    """Cheap magic-byte check — a 200 that returns an HTML error page is a common failure."""
    head = path.open("rb").read(8)
    want = _MAGIC.get(fmt)
    if want and not head.startswith(want):
        if head[:1] == b"<" or head[:5].lower() == b"<!doc":
            return "html_not_document"
        return "magic_mismatch"
    return "ok"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Build the fixed BIST-10 benchmark corpus.")
    ap.add_argument("--max-docs", type=int, default=300)
    ap.add_argument("--per-company", type=int, default=40)
    ap.add_argument("--max-mb", type=int, default=25)
    ap.add_argument("--text-only", action="store_true", default=True,
                    help="keep only pdf/docx/doc (default: on)")
    ap.add_argument("--include-sheets", dest="text_only", action="store_false",
                    help="also allow xlsx/xls")
    ap.add_argument("--spec-only", action="store_true",
                    help="write the corpus SPEC (the selected URL list) and exit — no downloads. "
                         "This is what another team needs to rebuild the identical corpus.")
    args = ap.parse_args(argv)

    rows = load_discovery()
    if not rows:
        print("discovery boş — önce keşif JSONL dosyaları gerekli:", DISCOVERY)
        return 1
    picks = select(rows, args.max_docs, args.per_company, args.max_mb, args.text_only)
    print(f"discovery={len(rows)}  seçilen={len(picks)}")

    if args.spec_only:
        MANIFEST_DIR.mkdir(parents=True, exist_ok=True)
        spec = [{
            "id": doc_id(r), "company": r.get("company"), "ticker": r.get("ticker"),
            "doc_name": r.get("doc_name"), "doc_type": r.get("doc_type"),
            "format": (r.get("format") or "").lower(), "ir_section": r.get("ir_section"),
            "source_url": r["source_url"], "publish_date": r.get("publish_date_or_null"),
            "lang": r.get("lang", "unknown"), "mime": r.get("mime"),
            "expected_size_bytes": r.get("size_bytes_or_null"),
            "source_kind": r.get("source_kind", "company"),
        } for r in picks]
        with (MANIFEST_DIR / "corpus_spec.jsonl").open("w", encoding="utf-8") as f:
            for s in spec:
                f.write(json.dumps(s, ensure_ascii=False) + "\n")
        summary = {
            "spec_version": "bist10-v1",
            "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "documents": len(spec),
            "companies": sorted({s["ticker"] for s in spec}),
            "by_company": dict(Counter(s["ticker"] for s in spec)),
            "by_format": dict(Counter(s["format"] for s in spec)),
            "by_doc_type": dict(Counter(s.get("doc_type") or "other" for s in spec)),
            "selection_rules": {
                "max_docs": args.max_docs, "per_company": args.per_company,
                "max_mb": args.max_mb, "text_only": args.text_only,
                "sort": "format_rank, doc_type, doc_name, url; round-robin across companies",
            },
        }
        (MANIFEST_DIR / "corpus_spec_summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(summary, ensure_ascii=False, indent=1))
        print(f"spec → {MANIFEST_DIR}/corpus_spec.jsonl")
        return 0

    RAW.mkdir(parents=True, exist_ok=True)
    MANIFEST_DIR.mkdir(parents=True, exist_ok=True)
    max_bytes = args.max_mb * 1024 * 1024

    manifest: list[dict] = []
    by_hash: dict[str, str] = {}
    stats = Counter()
    for i, rec in enumerate(picks, 1):
        fname = safe_name(rec)
        dest = RAW / fname
        if dest.exists() and dest.stat().st_size > 0:
            status, size = "ok", dest.stat().st_size   # resume: already fetched in a prior run
        else:
            status, size = download(rec["source_url"], dest, max_bytes)
        entry = {
            "id": doc_id(rec),
            "company": rec.get("company"), "ticker": rec.get("ticker"),
            "doc_name": rec.get("doc_name"), "doc_type": rec.get("doc_type"),
            "format": (rec.get("format") or "").lower(), "ir_section": rec.get("ir_section"),
            "source_url": rec["source_url"], "publish_date": rec.get("publish_date_or_null"),
            "lang": rec.get("lang", "unknown"), "mime": rec.get("mime"),
            "downloaded_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "download_status": status, "size_bytes": size, "filename": fname,
        }
        if status != "ok":
            entry["validity"] = "download_failed"
            stats["download_failed"] += 1
        else:
            data = dest.read_bytes()
            sha = hashlib.sha256(data).hexdigest()
            entry["sha256"] = sha
            if sha in by_hash:
                entry["validity"] = "duplicate"
                entry["duplicate_of"] = by_hash[sha]
                dest.unlink(missing_ok=True)
                stats["duplicate"] += 1
            else:
                v = validate(dest, entry["format"])
                entry["validity"] = "ok" if v == "ok" else v
                if v == "ok":
                    by_hash[sha] = entry["id"]
                    stats["ok"] += 1
                else:
                    stats[v] += 1
        manifest.append(entry)
        if i % 20 == 0 or i == len(picks):
            print(f"  [{i}/{len(picks)}] ok={stats['ok']} dup={stats['duplicate']} "
                  f"fail={stats['download_failed']}")

    with (MANIFEST_DIR / "corpus_manifest.jsonl").open("w", encoding="utf-8") as f:
        for m in manifest:
            f.write(json.dumps(m, ensure_ascii=False) + "\n")

    usable = [m for m in manifest if m.get("validity") == "ok"]
    summary = {
        "built_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "selected": len(picks), "usable": len(usable),
        "validity": dict(stats),
        "by_company": dict(Counter(m["ticker"] for m in usable)),
        "by_format": dict(Counter(m["format"] for m in usable)),
        "by_doc_type": dict(Counter(m.get("doc_type") or "other" for m in usable)),
        "total_bytes": sum(m.get("size_bytes") or 0 for m in usable),
    }
    (MANIFEST_DIR / "corpus_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n" + json.dumps(summary, ensure_ascii=False, indent=1))
    print(f"manifest → {MANIFEST_DIR}/corpus_manifest.jsonl")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

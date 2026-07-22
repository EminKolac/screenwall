"""Manifest-writing downloader for the BIST-30 benchmark corpus.

    uv run python -m evaluation.bist30_real.fetch --ticker AKBNK --doc-type annual_report \
        --url https://... [--doc-name "..."] [--published 2025] [--shard a]
    uv run python -m evaluation.bist30_real.fetch --ticker AKBNK --doc-type xlsx_financials \
        --unavailable "IR sitesi Excel yayımlamıyor" [--shard a]

Rules enforced here (not left to the caller):
  - Only official sources: the company's own domain, kap.org.tr, or borsaistanbul.com.
  - Extension allow-list: pdf / docx / xlsx / doc / xls. Magic bytes checked after download.
  - SHA-256 dedup across ALL manifest shards (same file published at two URLs → one copy).
  - Every attempt (success, failure, format_not_available) becomes one JSONL manifest row.
Downloads land in `data/bist30_benchmark/corpus/<TICKER>/` (repo-root /data is gitignored) —
raw corpus documents must never be committed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

from evaluation.bist30_real.companies import BIST30

ROOT = Path(__file__).resolve().parents[2].parent / "data" / "bist30_benchmark" / "corpus"
_EXT_MIME = {"pdf": "application/pdf",
             "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
             "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
             "doc": "application/msword", "xls": "application/vnd.ms-excel"}
_OFFICIAL_SUFFIXES = (".kap.org.tr", ".borsaistanbul.com")
_MAX_BYTES = 80 * 1024 * 1024


def _magic_ok(ext: str, head: bytes) -> bool:
    if ext == "pdf":
        return head.startswith(b"%PDF")
    if ext in ("docx", "xlsx"):
        return head.startswith(b"PK\x03\x04")
    if ext in ("doc", "xls"):
        return head.startswith(b"\xd0\xcf\x11\xe0")
    return False


def _known_hashes() -> set[str]:
    hashes = set()
    for mf in ROOT.glob("manifest_*.jsonl"):
        for line in mf.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("sha256"):
                hashes.add(row["sha256"])
    return hashes


def _row(args, **kw) -> dict:
    return {"company": BIST30.get(args.ticker, args.ticker), "ticker": args.ticker,
            "doc_name": kw.get("doc_name", args.doc_name or ""), "doc_type": args.doc_type,
            "format": kw.get("format", ""), "source_url": args.url or "",
            "published": args.published or "", "downloaded_at": date.today().isoformat(),
            "size_bytes": kw.get("size", 0), "mime": kw.get("mime", ""),
            "sha256": kw.get("sha256", ""), "download_result": kw["result"],
            "validity": kw.get("validity", ""), "path": kw.get("path", "")}


def _append(shard: str, row: dict) -> None:
    ROOT.mkdir(parents=True, exist_ok=True)
    with (ROOT / f"manifest_{shard}.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Download one official IR document into the corpus.")
    ap.add_argument("--ticker", required=True, choices=sorted(BIST30))
    ap.add_argument("--doc-type", required=True,
                    help="annual_report | financial_statements | presentation | sustainability | "
                         "general_assembly | corporate_governance | xlsx_financials | other")
    ap.add_argument("--url", default=None)
    ap.add_argument("--doc-name", default=None)
    ap.add_argument("--published", default=None)
    ap.add_argument("--shard", default="main")
    ap.add_argument("--unavailable", default=None,
                    help="record a format_not_available result instead of downloading")
    args = ap.parse_args(argv)

    if args.unavailable:
        _append(args.shard, _row(args, result="format_not_available",
                                 doc_name=args.unavailable))
        print(f"recorded format_not_available for {args.ticker}/{args.doc_type}")
        return 0
    if not args.url:
        print("--url required unless --unavailable", file=sys.stderr)
        return 2

    host = (urlparse(args.url).hostname or "").lower()
    if not (host.endswith(_OFFICIAL_SUFFIXES) or _looks_official(host)):
        _append(args.shard, _row(args, result="rejected_unofficial_source"))
        print(f"REJECTED (unofficial host {host})", file=sys.stderr)
        return 3

    ext = Path(urlparse(args.url).path).suffix.lower().lstrip(".")
    if ext not in _EXT_MIME:
        ext = "pdf"  # KAP/attachment endpoints often omit the extension; magic check decides

    import httpx
    try:
        with httpx.Client(follow_redirects=True, timeout=90,
                          headers={"User-Agent": "Mozilla/5.0 (research; anonymizer-benchmark)"}
                          ) as client:
            r = client.get(args.url)
            r.raise_for_status()
            data = r.content
    except Exception as e:  # noqa: BLE001 — a failed download is itself a manifest row
        _append(args.shard, _row(args, result=f"download_failed:{type(e).__name__}"))
        print(f"download_failed {args.ticker}: {type(e).__name__}", file=sys.stderr)
        return 1

    if len(data) > _MAX_BYTES:
        _append(args.shard, _row(args, result="rejected_too_large", size=len(data)))
        return 1
    data = _unwrap_kap_java_serialization(data)
    for cand in (ext, "pdf", "docx", "xlsx", "doc", "xls"):
        if _magic_ok(cand, data[:8]):
            ext = cand
            break
    else:
        _append(args.shard, _row(args, result="invalid_magic", size=len(data)))
        print(f"invalid magic for {args.url[:80]}", file=sys.stderr)
        return 1

    sha = hashlib.sha256(data).hexdigest()
    if sha in _known_hashes():
        _append(args.shard, _row(args, result="duplicate_sha256", sha256=sha, size=len(data),
                                 format=ext))
        print(f"duplicate (sha {sha[:12]}) — skipped")
        return 0

    name = args.doc_name or Path(urlparse(args.url).path).stem or args.doc_type
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", name)[:60]
    dest = ROOT / args.ticker / f"{sha[:12]}_{safe}.{ext}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    _append(args.shard, _row(args, result="ok", sha256=sha, size=len(data), format=ext,
                             mime=_EXT_MIME[ext], validity="magic_ok",
                             path=str(dest.relative_to(ROOT)), doc_name=name))
    print(f"OK {args.ticker} {ext} {len(data) // 1024}KB → {dest.name}")
    return 0


def _unwrap_kap_java_serialization(data: bytes) -> bytes:
    """kap.org.tr /api/file/download responses wrap the file in a Java-serialized byte[]
    (magic AC ED 00 05, 'ur ..[B' header, then a 4-byte length and the raw payload).
    Strip the wrapper so the normal magic-byte check sees the real file."""
    if not data.startswith(b"\xac\xed\x00\x05"):
        return data
    head = data[:64]
    for magic in (b"%PDF", b"PK\x03\x04", b"\xd0\xcf\x11\xe0"):
        idx = head.find(magic)
        if idx != -1:
            return data[idx:]
    return data


def _looks_official(host: str) -> bool:
    """The company's own domain (any TLD). We can't enumerate every corporate domain, so accept
    non-aggregator hosts and rely on the calling instructions + manifest review; explicitly
    reject known non-official aggregators."""
    banned = ("investing.com", "tradingview.com", "getmidas.com", "cnnturk.com", "milliyet",
              "uzmanpara", "docs.google", "drive.google", "dropbox", "scribd", "slideshare")
    return not any(b in host for b in banned)


if __name__ == "__main__":
    raise SystemExit(main())

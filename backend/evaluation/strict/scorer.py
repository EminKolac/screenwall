"""Output-only scorer for the user's Fable 60/72/probe contract. No detector imports.

Full-value results and the requested 3+ character partial-residual guard are reported
separately, since historical Fable headline numbers did not always use the same guard.
must_keep and over-mask sentences are EXACT, not lowercased or normalized.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import unicodedata
from collections import defaultdict
from pathlib import Path


def norm(value):
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", value)).strip()


def fraction(num, den):
    return {"numerator": num, "denominator": den, "rate": num / den if den else None}


def escape(surface, output):
    target, text = norm(surface), norm(output)
    literal = bool(target and target in text)
    partial = not literal and any(part in text for part in target.split() if len(part) >= 3)
    return literal, partial


def gold_case(case, output):
    entries = []
    for mention in case["must_mask"]:
        literal, partial = escape(mention["surface"], output) if output is not None else (True, False)
        entries.append({"type": mention["type"], "critical": mention["critical"],
                        "masked": not (literal or partial), "literal_masked": not literal,
                        "partial": partial,
                        "vhash": hashlib.sha256(mention["surface"].encode()).hexdigest()[:16]})
    return {"id": case["id"], "processed": output is not None, "mentions": entries,
            "keep_total": len(case["must_keep"]),
            "keep_preserved": sum(surface in output for surface in case["must_keep"]) if output is not None else 0}


def summarize_gold(rows):
    mentions = [m for row in rows for m in row["mentions"]]
    critical = [m for m in mentions if m["critical"]]
    buckets = defaultdict(list)
    for mention in mentions:
        buckets[mention["type"]].append(mention)
    keep = sum(r["keep_total"] for r in rows)
    return {"documents": len(rows), "recall": fraction(sum(m["masked"] for m in mentions), len(mentions)),
            "critical_recall": fraction(sum(m["masked"] for m in critical), len(critical)),
            "literal_critical_recall": fraction(sum(m["literal_masked"] for m in critical), len(critical)),
            "over_masking": fraction(keep - sum(r["keep_preserved"] for r in rows), keep),
            "unprocessed": [r["id"] for r in rows if not r["processed"]],
            "by_type": {key: fraction(sum(m["masked"] for m in values), len(values))
                        for key, values in sorted(buckets.items())}}


def stress_case(case, shipped, output, status):
    leak = any(norm(value) in norm(output) for value in case["planted_values"] if len(value) >= 6) if shipped else False
    if leak:
        verdict = "critical_false_approval"
    elif case["expected"] == "fail_closed":
        verdict = "pass" if not shipped else "fail"
    else:
        verdict = "pass" if shipped else "conservative"
    return {"file": case["file"], "scenario": case["scenario"], "expected": case["expected"],
            "status": status, "shipped": shipped, "verdict": verdict,
            "architecturally_safe": case.get("architecturally_safe", False)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--outputs", type=Path, required=True,
                        help="Synthetic-only JSON list {id,text}; missing outputs count as unprocessed")
    args = parser.parse_args()
    cases = json.loads((args.corpus / "goldbench-holdout.json").read_text())
    outputs = {row["id"]: row.get("text") for row in json.loads(args.outputs.read_text())}
    print(json.dumps(summarize_gold([gold_case(case, outputs.get(case["id"])) for case in cases]), indent=2))


if __name__ == "__main__":
    main()

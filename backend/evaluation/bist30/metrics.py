"""Aggregate placement results into the canary-benchmark metrics the task asks for.

Everything here is value-free (hashes/types/families only). Masking/recall and export residual are
authoritative (value global-presence in layer-3 / export); placeholder family is best-effort.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict

_TOKEN = re.compile(r"<[A-Z]+_\d+>")
_FAM = re.compile(r"<([A-Z]+)_\d+>")


def _rate(num: int, den: int) -> float:
    return (num / den) if den else 1.0


def summarize(results, outcomes) -> dict:
    content = [r for r in results if r.channel != "filename"]
    filenames = [r for r in results if r.channel == "filename"]
    extracted = [r for r in content if r.extracted]

    masked = [r for r in extracted if r.masked]
    fam_ok = [r for r in masked if r.family_ok]
    # A leak only SHIPS if its carrier was APPROVED (the /download API returns 403 for anything in
    # human review), so distinguish ship-leaks from residual contained by fail-closed review.
    status = {r.marker: o.status for o in outcomes for r in o.results}
    approved = lambda r: status.get(r.marker) == "approved"  # noqa: E731
    leaks = [r for r in results if r.residual_in_export and approved(r)]
    contained = [r for r in results if r.residual_in_export and not approved(r)]
    # A critical false-negative = a critical canary that would SHIP unmasked (approved + residual).
    crit_fn = [r for r in content if r.critical and approved(r)
               and (r.residual_in_export or (r.extracted and not r.masked))]

    per_entity: dict[str, dict] = {}
    ents: dict[str, list] = defaultdict(list)
    for r in content:
        ents[r.canary_id].append(r)
    for cid, rs in sorted(ents.items()):
        ex = [r for r in rs if r.extracted]
        per_entity[cid] = {
            "n": len(rs), "extracted": len(ex),
            "masked": sum(r.masked for r in ex),
            "family_ok": sum(r.family_ok for r in ex),
            "leaked": sum(r.residual_in_export for r in rs),
            "recall": round(_rate(sum(r.masked for r in ex), len(ex)), 3),
            "expected_family": rs[0].expected_family,
            "critical": rs[0].critical, "base_detectable": rs[0].base_detectable,
        }

    per_channel: dict[str, dict] = {}
    chans: dict[str, list] = defaultdict(list)
    for r in content:
        chans[f"{r.fmt}:{r.channel}"].append(r)
    for ch, rs in sorted(chans.items()):
        ex = [r for r in rs if r.extracted]
        per_channel[ch] = {
            "n": len(rs), "extracted": len(ex), "masked": sum(r.masked for r in ex),
            "coverage": round(_rate(len(ex), len(rs)), 3),
            "recall": round(_rate(sum(r.masked for r in ex), len(ex)), 3),
        }

    ocr = [r for r in content if r.channel == "ocr"]
    ocr_ex = [r for r in ocr if r.extracted]
    secs = sorted(o.seconds for o in outcomes)
    p95 = secs[min(len(secs) - 1, int(round(0.95 * (len(secs) - 1))))] if secs else 0.0

    return {
        "totals": {
            "placements": len(results), "content": len(content), "extracted": len(extracted),
            "masked": len(masked), "family_ok": len(fam_ok), "leaks": len(leaks),
            "critical_false_negatives": len(crit_fn),
        },
        "value_recall": round(_rate(len(masked), len(extracted)), 3),
        "family_accuracy": round(_rate(len(fam_ok), len(masked)), 3),
        "extraction_rate": round(_rate(len(extracted), len(content)), 3),
        "export_residual_count": len(leaks),
        "contained_residual_count": len(contained),
        "leaks": [r.safe_dict() for r in leaks],
        "contained_residual": [r.safe_dict() for r in contained],
        "critical_false_negatives": [r.safe_dict() for r in crit_fn],
        "filename_success": round(_rate(sum(r.masked for r in filenames), len(filenames)), 3),
        "ocr_recall": round(_rate(sum(r.masked for r in ocr_ex), len(ocr_ex)), 3),
        "ocr_extraction_rate": round(_rate(len(ocr_ex), len(ocr)), 3),
        "per_entity": per_entity,
        "per_channel": per_channel,
        "stage_counts": dict(Counter(r.stage for r in results).most_common()),
        "timing": {"avg_s": round(sum(secs) / len(secs), 2) if secs else 0.0,
                   "p95_s": round(p95, 2), "n_carriers": len(outcomes)},
        "determinism": _determinism(outcomes),
    }


def _determinism(outcomes) -> dict:
    """Per document + family: distinct placeholder tokens vs distinct masked canary values. Equal =
    deterministic (each value → one stable token); more tokens than values = a value split across
    tokens (non-deterministic); fewer = a collision (two values → one token)."""
    out: dict[str, dict] = {}
    for o in outcomes:
        toks = _TOKEN.findall(o.anon_text)
        fam_tokens: dict[str, set] = defaultdict(set)
        for t in toks:
            fam_tokens[_FAM.match(t).group(1)].add(t)
        fam_values: dict[str, set] = defaultdict(set)
        for r in o.results:
            if r.masked and r.channel != "filename":
                fam_values[r.expected_family].add(r.vhash)
        report = {}
        for fam in sorted(set(fam_tokens) | set(fam_values)):
            report[fam] = {"distinct_tokens": len(fam_tokens.get(fam, set())),
                           "distinct_values": len(fam_values.get(fam, set()))}
        out[o.name] = report
    return out

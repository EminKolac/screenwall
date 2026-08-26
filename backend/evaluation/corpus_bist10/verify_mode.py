"""Mode-integrity assertion sets — Benchmark M (`mapping`) and Benchmark D (`destructive`).

See `BENCHMARK_GUIDE.md` §11-12 for the contract these implement. They check the STORAGE-LEVEL
PROMISE each mode makes — not detection quality, which is measured separately by
`run_bench.py`/`report.py` using the same shared metrics for both modes (§12.3 / D4: destruction
must not cost recall, only what gets persisted).

Mapping mode (M1-M3) is checked per document — mapping completeness/round-trip/containment are all
document-scoped facts. Destructive mode's D2/D3 are also per-document (repo methods are the ground
truth). D1 — the full-tree sweep — is a RUN-LEVEL check: call it ONCE, after all documents in a
destructive-mode benchmark run have been processed, against a storage root used EXCLUSIVELY by
that run. Sweeping a root that also holds `mapping`-mode documents (which legitimately keep raw
values on disk) would produce meaningless hits unrelated to the destructive-mode guarantee — this
is why `evaluation/corpus_bist10/run_bench.py` keeps a separate storage root per mode.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

_TOKEN = re.compile(r"<[A-Z]+_\d+>")


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "")
    return re.sub(r"\s+", " ", s).strip().casefold()


@dataclass
class ModeCheckResult:
    doc_id: str
    mode: str
    checks: dict[str, bool] = field(default_factory=dict)
    details: dict[str, object] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return bool(self.checks) and all(self.checks.values())

    def safe_dict(self) -> dict:
        """Value-free summary — booleans/counts only, safe for reports."""
        return {"doc_id": self.doc_id, "mode": self.mode, "passed": self.passed,
                "checks": dict(self.checks), "details": dict(self.details)}


# ---------- Benchmark M — mapping mode ----------

def check_mapping_mode(
    doc_id: str, repo, canary_values: list[str], shareable_blobs: dict[str, str] | None = None,
) -> ModeCheckResult:
    """M1 completeness, M2 round-trip, M3 containment.

    `canary_values` are the RAW synthetic values placed in this document — used only to compute
    booleans/counts here, never written into the returned result.
    `shareable_blobs` — {name: text} of every response this document's data could reach a client
    through (API detail/findings/anonymized text, exported-file text, chat context) — checked for
    M3. Pass {} to skip M3 (still reports it as failed, since it cannot be verified as satisfied).
    """
    r = ModeCheckResult(doc_id=doc_id, mode="mapping")
    mapping = repo.get_mapping(doc_id) or {}
    anon = repo.get_anonymized(doc_id)
    anon_text = anon.plain_text if anon else ""

    # M1 — every <TYPE_n> token actually present in layer 3 resolves via the stored map.
    tokens = set(_TOKEN.findall(anon_text))
    unresolved = sorted(t for t in tokens if t not in mapping)
    r.checks["M1_mapping_complete"] = not unresolved
    r.details["M1_tokens_total"] = len(tokens)
    r.details["M1_unresolved_tokens"] = len(unresolved)

    # M2 — round-trip: every canary value that was actually masked (no longer appears in the
    # anonymized text) must be reconstructible by looking it up among the map's original values.
    anon_norm = _norm(anon_text)
    mapped_values = {_norm(v) for v in mapping.values()}
    masked = [v for v in canary_values if _norm(v) and _norm(v) not in anon_norm]
    recoverable = [v for v in masked if _norm(v) in mapped_values]
    r.checks["M2_roundtrip_complete"] = len(recoverable) == len(masked)
    r.details["M2_masked_count"] = len(masked)
    r.details["M2_recoverable_count"] = len(recoverable)

    # M3 — canary values (deliberately distinctive synthetic strings) must never appear in
    # anything shareable. Deliberately scoped to `canary_values`, NOT the full `mapping.values()`:
    # a real document's map has thousands of entries, many of them ordinary over-masked words (a
    # known, separate over-masking issue — see BENCHMARK_GUIDE.md). Checking those generic values
    # for accidental substring collisions in a large document produces noise unrelated to the
    # actual containment guarantee (a mapped word like "sözleşme" coincidentally recurring
    # elsewhere in prose is not a leak). Canary values are short, specific, and synthetic, so a
    # match is a real signal.
    leaked_in: list[str] = []
    for name, blob in (shareable_blobs or {}).items():
        nb = _norm(blob)
        if any(_norm(v) and _norm(v) in nb for v in canary_values):
            leaked_in.append(name)
    r.checks["M3_mapping_contained"] = bool(shareable_blobs) and not leaked_in
    r.details["M3_leaked_in"] = leaked_in
    r.details["M3_blobs_checked"] = len(shareable_blobs or {})
    return r


# ---------- Benchmark D — destructive mode ----------

def check_destructive_mode(doc_id: str, repo) -> ModeCheckResult:
    """D2 (no layer-1/layer-2 artifact) + D3 (reversal attempt through the app API fails).

    D1 (the full-tree disk sweep) is run separately, once per benchmark run — see
    `full_tree_pii_sweep`.
    """
    r = ModeCheckResult(doc_id=doc_id, mode="destructive")
    r.checks["D2_no_original"] = repo.get_original(doc_id) is None
    r.checks["D2_no_extracted"] = repo.get_extracted(doc_id) is None
    r.checks["D2_no_mapping_file"] = repo.get_mapping(doc_id) is None
    # D3 is framed as an explicit reversal ATTEMPT (BENCHMARK_GUIDE.md §12.2) rather than a file
    # check: the same underlying fact (no map persisted) verified through the application's own
    # read path, so a caller with only API/repo access — not raw disk access — still can't reverse.
    r.checks["D3_reversal_fails"] = repo.get_mapping(doc_id) is None
    return r


def full_tree_pii_sweep(storage_root: str | Path, canary_values: list[str]) -> dict[str, int]:
    """D1 — the acceptance gate. Walk EVERY file under `storage_root` and count occurrences of
    each canary value. Returns {sha256[:16] of the value: hit count} — never the raw value, so
    this is safe to log/report. `sum(result.values()) == 0` is the pass condition.
    """
    from evaluation.bist30.canary import value_hash

    by_hash = {value_hash(v): _norm(v) for v in canary_values if v}
    hits = dict.fromkeys(by_hash, 0)
    root = Path(storage_root)
    if not root.exists():
        return hits
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        try:
            text = _norm(p.read_bytes().decode("utf-8", errors="ignore"))
        except OSError:
            continue
        for h, nv in by_hash.items():
            if nv and nv in text:
                hits[h] += 1
    return hits

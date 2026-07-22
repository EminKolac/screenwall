"""Run canary carriers through the REAL pipeline and grade each placement.

For a carrier we run `run_pipeline` (isolated, gitignored storage), then compare three texts:
  - original extracted  (what extraction captured, layer 2)   — did the value get in?
  - anonymized          (layer 3)                              — was it masked, correct family?
  - re-extracted export (render_content_pdf → re-parse)        — did it survive into the file?
Filename placements are graded separately via `anonymize_filename`. Nothing here prints raw values.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

from app.anonymization.presidio_engine import PresidioEngine
from app.config import Settings
from app.export.filename import anonymize_filename
from app.export.render_pdf import render_content_pdf
from app.extraction.dispatcher import extract
from app.pipeline.runner import run_pipeline
from app.services.storage_repository import StorageDocumentRepository
from app.storage.local import LocalStorageBackend
from evaluation.bist30.harness import Placement, PlacementResult, evaluate, norm


@dataclass
class CarrierOutcome:
    name: str
    fmt: str
    status: str
    seconds: float
    ocr_warning: bool
    results: list[PlacementResult] = field(default_factory=list)
    anon_text: str = ""   # layer-3 text (for the deterministic-token consistency check)
    error: str = ""


def benchmark_settings(work_dir: Path) -> tuple[Settings, StorageDocumentRepository]:
    """Isolated settings (heuristic auditor → deterministic/offline) + storage under the gitignored
    work dir. `auditor_provider='mlx'` skips the Ollama branch in build_auditor → heuristic-only."""
    settings = Settings(storage_root=work_dir / "storage", auditor_provider="mlx",
                        require_llm_auditor=False)
    repo = StorageDocumentRepository(LocalStorageBackend(work_dir / "storage"))
    return settings, repo


def process_carrier(
    name: str, data: bytes, filename: str, placements: list[Placement],
    settings: Settings, repo: StorageDocumentRepository,
) -> CarrierOutcome:
    max_bytes = settings.max_upload_mb * 1024 * 1024
    t0 = time.monotonic()
    try:
        doc = run_pipeline(data, filename, settings, repo)
    except Exception as e:  # noqa: BLE001 — a carrier that fails to ingest is itself a result
        return CarrierOutcome(name, placements[0].fmt if placements else "?", "INGEST_ERROR",
                              time.monotonic() - t0, False, error=f"{type(e).__name__}: {e}"[:120])

    # Texts to compare. Re-extract the original bytes for the exact layer-2 text (incl. OCR).
    _, orig = extract(data, filename, max_bytes)
    original_text = orig.plain_text
    ocr_warning = any(w.startswith("ocr_unavailable") for w in orig.warnings)
    # The resolved detection spans on the original text (same detect() the pipeline masks by) — used
    # only to attribute a placeholder family / detection stage to each value's original position.
    detected_spans = PresidioEngine().detect(original_text)

    anon = repo.get_anonymized(doc.id)
    anon_text = anon.plain_text if anon is not None else ""
    export_text = None
    if anon is not None:
        try:
            pdf = render_content_pdf(anon)
            _, ex = extract(pdf, "export.pdf", max_bytes)
            export_text = ex.plain_text
        except Exception:  # noqa: BLE001 — export failure is captured as no export_text
            export_text = None

    results: list[PlacementResult] = []
    for p in placements:
        if p.channel == "filename":
            results.append(_grade_filename(p, filename))
        else:
            results.append(evaluate(p, original_text, detected_spans, anon_text, export_text))

    return CarrierOutcome(name, placements[0].fmt if placements else "?", doc.status.value,
                          time.monotonic() - t0, ocr_warning, results, anon_text=anon_text)


def _grade_filename(p: Placement, filename: str) -> PlacementResult:
    safe = anonymize_filename(filename, deny_terms=[])
    masked = norm(p.value) not in norm(safe)
    stage = "ok" if masked else "S15_filename_not_anonymized"
    return PlacementResult(
        marker=p.marker, canary_id=p.canary_id, fmt=p.fmt, channel="filename", variant=p.variant,
        expected_family=p.expected_family, critical=p.critical, base_detectable=p.base_detectable,
        vhash=p.vhash, extracted=True, detected=masked, masked=masked, family_ok=masked,
        found_family="", residual_in_export=not masked, token="", stage=stage,
    )

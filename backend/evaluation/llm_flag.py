"""`--llm on|off` — one explicit auditor switch for every benchmark runner.

Before Faz 0 every runner hard-coded `auditor_provider="mlx"`. `build_auditor` only adds the Qwen
auditor for "ollama", so the LLM silently never ran and no recorded measurement had it on.

    off → auditor_provider="mlx",    require_llm_auditor=False   heuristic auditor only
    on  → auditor_provider="ollama", require_llm_auditor=True    heuristic + local Qwen, fail-closed

`on` is checked before any document is processed (`ensure_llm_ready`): if Ollama or the model is
missing the run stops with an error instead of producing heuristic-only numbers under an "LLM"
label. If the model disappears mid-run, `require_llm_auditor=True` sends each affected document to
human review (fail-closed), and the per-file timing the scorecard records exposes it
(~5-7 s/file with qwen3.5:4b vs ~0.1 s without an LLM).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

LLM_CHOICES = ("on", "off")
LLM_DEFAULT = "off"

_OVERRIDES: dict[str, dict[str, Any]] = {
    "on": {"auditor_provider": "ollama", "require_llm_auditor": True},
    "off": {"auditor_provider": "mlx", "require_llm_auditor": False},
}


class LLMUnavailableError(RuntimeError):
    """`--llm on` was requested but the local auditor model cannot be reached."""


class LLMModeMismatchError(RuntimeError):
    """A resumable results directory already holds results produced with the other `--llm` mode."""


def add_llm_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--llm", choices=LLM_CHOICES, default=LLM_DEFAULT,
        help="on = local Qwen auditor via Ollama, required (fail-closed; the run stops if the "
             "model is unreachable). off = deterministic heuristic auditor only. Default: off.")


def auditor_overrides(llm: str) -> dict[str, Any]:
    """Settings fields implied by the flag. Raises ValueError for anything but on/off."""
    try:
        return dict(_OVERRIDES[llm])
    except KeyError:
        raise ValueError(f"--llm must be one of {LLM_CHOICES}, got {llm!r}") from None


def build_settings(llm: str, **overrides: Any):
    """`Settings(**overrides)` with the auditor fields forced by the flag (the flag always wins
    over the environment and over `overrides`)."""
    from app.config import Settings

    return Settings(**{**overrides, **auditor_overrides(llm)})


def ensure_llm_ready(settings) -> None:
    """Fail fast when the LLM auditor is required but unreachable. No-op for `--llm off`."""
    if settings.auditor_provider != "ollama":
        return
    from app.audit.ollama_provider import OllamaProvider

    if not OllamaProvider(settings.ollama_base_url, settings.auditor_model).is_available():
        raise LLMUnavailableError(
            f"--llm on: auditor model '{settings.auditor_model}' is not available at "
            f"{settings.ollama_base_url}. Start Ollama and pull the model, or run with --llm off.")


def llm_config(llm: str, settings) -> dict[str, Any]:
    """What gets recorded in each run's config/output."""
    on = llm == "on"
    return {
        "llm": llm,
        "auditor_provider": settings.auditor_provider,
        "require_llm_auditor": settings.require_llm_auditor,
        "auditor_model": settings.auditor_model if on else None,
        "ollama_base_url": settings.ollama_base_url if on else None,
    }


def check_resume(outdir: Path, llm: str) -> None:
    """Resumable runners append to an existing results file and skip finished ids. Resuming a
    directory produced with the other mode would silently mix LLM and non-LLM rows — refuse.
    Configs written before this flag existed carry no "llm" key; they were all heuristic-only."""
    cfg = outdir / "run_config.json"
    if not cfg.exists():
        return
    try:
        previous = json.loads(cfg.read_text(encoding="utf-8")).get("llm", LLM_DEFAULT)
    except (OSError, ValueError):
        return
    if previous != llm:
        raise LLMModeMismatchError(
            f"{outdir} already holds --llm {previous} results; resuming it with --llm {llm} "
            f"would mix the two. Use a new --tag.")

"""`--llm on|off` — one explicit auditor switch for every benchmark runner.

Before Faz 0 every runner hard-coded `auditor_provider="mlx"`. `build_auditor` only adds the Qwen
auditor for "ollama", so the LLM silently never ran and no recorded measurement had it on.

    off → auditor_provider="mlx",    require_llm_auditor=False   heuristic auditor only
    on  → auditor_provider="ollama", require_llm_auditor=True    heuristic + local Qwen, fail-closed

`on` is checked before any document is processed (`ensure_llm_ready`): if Ollama or the model is
missing the run stops with an error instead of producing heuristic-only numbers under an "LLM"
label. If the model disappears mid-run, or a single audit call fails (timeout, non-JSON answer),
the audit fails closed and carries `llm_ok=False`; each affected document goes to human review
and the runners record per-document counts (`llm_audit_counts`), so the scorecard can require
zero failures instead of trusting the per-file timing alone (~5-7 s/file with qwen3.5:4b vs
~0.1 s without an LLM).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

LLM_CHOICES = ("on", "off")
LLM_DEFAULT = "off"
# Every result written before this flag existed was heuristic-only: the runners hard-coded
# auditor_provider="mlx". A results directory without a recorded mode is therefore "off".
PRE_FLAG_MODE = "off"

_OVERRIDES: dict[str, dict[str, Any]] = {
    "on": {"auditor_provider": "ollama", "require_llm_auditor": True},
    "off": {"auditor_provider": "mlx", "require_llm_auditor": False},
}


class LLMUnavailableError(RuntimeError):
    """`--llm on` was requested but the local auditor model cannot be reached."""


class LLMModeMismatchError(RuntimeError):
    """A resumable results directory already holds results produced with the other `--llm` mode."""


class RunConfigUnreadableError(LLMModeMismatchError):
    """`run_config.json` exists but cannot be read, so the mode of the results beside it is
    unknown. A subclass so every runner's existing mismatch handler refuses the resume too."""


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


def llm_audit_counts(doc) -> dict[str, int]:
    """Per-document audit calls from the pipeline's iteration records: `audits` ran, `llm_ok` had a
    real LLM verdict, `llm_failed` had an LLM that was required or configured but failed (the
    audit then failed closed). A heuristic-only audit counts in `audits` alone."""
    audits = [it.audit for it in getattr(doc, "iterations", None) or [] if it.audit is not None]
    return {
        "audits": len(audits),
        "llm_ok": sum(1 for a in audits if a.llm_ok is True),
        "llm_failed": sum(1 for a in audits if a.llm_ok is False),
    }


def _has_results(outdir: Path) -> bool:
    """Any non-empty JSONL file: the rows a resumable runner would append to and skip."""
    for path in outdir.glob("*.jsonl"):
        try:
            if path.is_file() and path.read_text(encoding="utf-8").strip():
                return True
        except (OSError, UnicodeDecodeError):
            return True  # rows we cannot read are still rows: do not assume the directory is empty
    return False


def _recorded_mode(cfg: Path) -> str:
    try:
        data = json.loads(cfg.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise RunConfigUnreadableError(
            f"{cfg} cannot be read ({type(e).__name__}), so the --llm mode of the results next to "
            f"it is unknown; resuming could mix LLM and non-LLM rows. Use a new --tag.") from e
    if not isinstance(data, dict):
        raise RunConfigUnreadableError(
            f"{cfg} is not a JSON object, so the --llm mode of the results next to it is "
            f"unknown. Use a new --tag.")
    return data.get("llm", PRE_FLAG_MODE)  # configs written before the flag: heuristic-only


def check_resume(outdir: Path, llm: str) -> None:
    """Resumable runners append to an existing results file and skip finished ids, then write a
    new run_config.json. Resuming a directory produced with the other mode would silently mix LLM
    and non-LLM rows and relabel the old ones — refuse.

    - run_config.json present: its "llm" key, or "off" when it predates the flag.
    - run_config.json unreadable (or not an object): the earlier mode is unknown — refuse always.
    - run_config.json missing but results present (any non-empty *.jsonl): the results predate
      the flag, when every runner was heuristic-only — they count as "off".
    - neither: nothing to resume."""
    cfg = outdir / "run_config.json"
    if cfg.exists():
        previous = _recorded_mode(cfg)
        if previous != llm:
            raise LLMModeMismatchError(
                f"{outdir} already holds --llm {previous} results; resuming it with --llm {llm} "
                f"would mix the two. Use a new --tag.")
    elif llm != PRE_FLAG_MODE and _has_results(outdir):
        raise LLMModeMismatchError(
            f"{outdir} holds results but no run_config.json: they predate the --llm flag, when "
            f"every runner used the heuristic auditor only (--llm {PRE_FLAG_MODE}). Resuming it "
            f"with --llm {llm} would label those rows as --llm {llm} rows. Use a new --tag.")

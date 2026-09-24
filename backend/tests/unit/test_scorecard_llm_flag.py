"""`--llm on|off` → Settings, for the helper and for every runner that uses it.

No model and no network: the Ollama availability probe is monkeypatched everywhere.
"""
from __future__ import annotations

import argparse
import importlib
import json

import pytest

from evaluation import llm_flag

RUNNERS = (
    "evaluation.goldbench.run_gold",
    "evaluation.goldbench.run_stress",
    "evaluation.goldbench.run_inference",
    "evaluation.corpus_bist10.run_bench",
)
EXPECTED = [("on", "ollama", True), ("off", "mlx", False)]


def test_flag_defaults_to_off_and_rejects_other_values():
    ap = argparse.ArgumentParser()
    llm_flag.add_llm_argument(ap)
    assert ap.parse_args([]).llm == "off"
    assert ap.parse_args(["--llm", "on"]).llm == "on"
    with pytest.raises(SystemExit):
        ap.parse_args(["--llm", "maybe"])
    with pytest.raises(ValueError):
        llm_flag.auditor_overrides("maybe")


@pytest.mark.parametrize("llm,provider,required", EXPECTED)
def test_flag_beats_environment_and_explicit_overrides(llm, provider, required, monkeypatch):
    monkeypatch.setenv("AUDITOR_PROVIDER", "llamacpp")
    monkeypatch.setenv("REQUIRE_LLM_AUDITOR", "false" if required else "true")
    settings = llm_flag.build_settings(llm, auditor_provider="llamacpp",
                                       require_llm_auditor=not required)
    assert settings.auditor_provider == provider
    assert settings.require_llm_auditor is required


def test_on_fails_closed_when_the_model_is_unreachable(monkeypatch):
    from app.audit.ollama_provider import OllamaProvider

    monkeypatch.setattr(OllamaProvider, "is_available", lambda self: False)
    with pytest.raises(llm_flag.LLMUnavailableError, match="--llm on"):
        llm_flag.ensure_llm_ready(llm_flag.build_settings("on"))


def test_on_passes_when_the_model_is_available(monkeypatch):
    from app.audit.ollama_provider import OllamaProvider

    monkeypatch.setattr(OllamaProvider, "is_available", lambda self: True)
    llm_flag.ensure_llm_ready(llm_flag.build_settings("on"))


def test_off_never_probes_ollama(monkeypatch):
    from app.audit.ollama_provider import OllamaProvider

    def probe(self):
        raise AssertionError("--llm off must not contact Ollama")

    monkeypatch.setattr(OllamaProvider, "is_available", probe)
    llm_flag.ensure_llm_ready(llm_flag.build_settings("off"))


def test_llm_config_records_what_ran():
    on = llm_flag.llm_config("on", llm_flag.build_settings("on"))
    assert (on["llm"], on["auditor_provider"], on["require_llm_auditor"]) == ("on", "ollama", True)
    assert on["auditor_model"]
    off = llm_flag.llm_config("off", llm_flag.build_settings("off"))
    assert (off["llm"], off["auditor_provider"], off["auditor_model"]) == ("off", "mlx", None)


def test_resume_refuses_to_mix_modes(tmp_path):
    llm_flag.check_resume(tmp_path / "fresh", "on")  # nothing to resume
    cfg = tmp_path / "run_config.json"
    cfg.write_text(json.dumps({"llm": "off"}), encoding="utf-8")
    llm_flag.check_resume(tmp_path, "off")
    with pytest.raises(llm_flag.LLMModeMismatchError):
        llm_flag.check_resume(tmp_path, "on")
    # configs written before the flag existed were heuristic-only runs
    cfg.write_text(json.dumps({"auditor_provider": "mlx (deterministic heuristic)"}), "utf-8")
    with pytest.raises(llm_flag.LLMModeMismatchError):
        llm_flag.check_resume(tmp_path, "on")


@pytest.mark.parametrize("module", RUNNERS)
@pytest.mark.parametrize("llm,provider,required", EXPECTED)
def test_runner_repo_follows_the_flag(module, llm, provider, required, monkeypatch, tmp_path):
    mod = importlib.import_module(module)
    probed = []
    monkeypatch.setattr(mod, "ensure_llm_ready", lambda s: probed.append(s.auditor_provider))
    monkeypatch.chdir(tmp_path)  # runners use relative storage roots
    settings, _ = mod._repo("mapping", llm)
    assert settings.auditor_provider == provider
    assert settings.require_llm_auditor is required
    assert probed == [provider]  # the readiness check runs for every repo the runner builds


@pytest.mark.parametrize("module", RUNNERS)
def test_runner_cli_exposes_the_flag(module, capsys):
    mod = importlib.import_module(module)
    with pytest.raises(SystemExit) as exc:
        mod.main(["--help"])
    assert exc.value.code == 0
    assert "--llm {on,off}" in capsys.readouterr().out

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


# ------------------------------------------------------- resuming pre-flag directories

def test_results_without_a_config_count_as_off_and_refuse_on(tmp_path):
    """The 18 pre-flag directories: stress.jsonl, no run_config.json, heuristic-only rows."""
    old = tmp_path / "llm-gercek-mapping"
    old.mkdir()
    (old / "stress.jsonl").write_text('{"case_id": "a"}\n', encoding="utf-8")
    (old / "summary.json").write_text("{}", encoding="utf-8")
    with pytest.raises(llm_flag.LLMModeMismatchError, match="predate the --llm flag"):
        llm_flag.check_resume(old, "on")
    llm_flag.check_resume(old, "off")  # same (heuristic-only) mode: resuming is honest


def test_empty_results_without_a_config_are_nothing_to_resume(tmp_path):
    (tmp_path / "stress.jsonl").write_text("\n", encoding="utf-8")
    (tmp_path / "mode_checks.jsonl").touch()
    llm_flag.check_resume(tmp_path, "on")
    llm_flag.check_resume(tmp_path, "off")


@pytest.mark.parametrize("content", ["{not json", "[]", '"on"'])
@pytest.mark.parametrize("llm", ["on", "off"])
def test_an_unreadable_config_refuses_either_mode(tmp_path, content, llm):
    (tmp_path / "run_config.json").write_text(content, encoding="utf-8")
    with pytest.raises(llm_flag.RunConfigUnreadableError, match="new --tag"):
        llm_flag.check_resume(tmp_path, llm)


def test_unreadable_config_is_caught_by_the_runners_mismatch_handler(tmp_path, monkeypatch,
                                                                     capsys):
    from evaluation.goldbench import run_stress

    monkeypatch.setattr(run_stress, "OUT", tmp_path)
    (tmp_path / "x-mapping").mkdir()
    (tmp_path / "x-mapping" / "run_config.json").write_text("{", encoding="utf-8")
    monkeypatch.setattr(run_stress, "build_corpus", lambda: [])
    assert run_stress.main(["--tag", "x"]) == 2
    assert "HATA" in capsys.readouterr().out
    assert (tmp_path / "x-mapping" / "run_config.json").read_text(encoding="utf-8") == "{"


def test_pre_flag_directory_is_not_relabelled_by_run_stress(tmp_path, monkeypatch):
    from evaluation.goldbench import run_stress

    monkeypatch.setattr(run_stress, "OUT", tmp_path)
    old = tmp_path / "llm-gercek-mapping"
    old.mkdir()
    (old / "stress.jsonl").write_text('{"case_id": "a"}\n', encoding="utf-8")
    monkeypatch.setattr(run_stress, "ensure_llm_ready", lambda s: None)
    monkeypatch.setattr(run_stress, "build_corpus", lambda: [])
    assert run_stress.main(["--tag", "llm-gercek", "--llm", "on"]) == 2
    assert not (old / "run_config.json").exists()  # no config claiming "LLM on"


# --------------------------------------------- runners: own root, overrides, LLM counts

@pytest.mark.parametrize("module", ["evaluation.goldbench.run_gold",
                                    "evaluation.goldbench.run_stress"])
def test_runner_repo_accepts_a_root_and_settings_overrides(module, tmp_path, monkeypatch):
    mod = importlib.import_module(module)
    monkeypatch.setattr(mod, "ensure_llm_ready", lambda s: None)
    monkeypatch.setenv("ALLOW_TERMS", "Proje Adı")
    settings, repo = mod._repo("mapping", "off", root=tmp_path / "own",
                               term_lists=False, allow_terms="")
    assert settings.storage_root == tmp_path / "own"
    assert repo.backend.root == tmp_path / "own"
    assert (settings.term_lists, settings.allow_terms) == (False, "")


def test_run_stress_writes_per_document_llm_counts(tmp_path, monkeypatch):
    import httpx

    import app.pipeline.runner as runner
    from app.audit.auditor import PrivacyAuditor
    from app.audit.factory import CompositeAuditor
    from app.audit.heuristic import HeuristicAuditor
    from app.models.findings import RiskLevel
    from evaluation.goldbench import run_stress
    from evaluation.goldbench.stress import StressCase
    from evaluation.scorecard_common import NO_TERM_LISTS
    from tests.conftest import TR_PARA, make_docx

    class Timeout:
        name = "fake"

        def is_available(self) -> bool:
            return True

        def complete(self, system_prompt: str, user_prompt: str) -> str:
            raise httpx.ReadTimeout("slow")

    monkeypatch.setattr(runner, "build_auditor", lambda s: CompositeAuditor(
        HeuristicAuditor(), PrivacyAuditor(Timeout()), RiskLevel.low, require_llm=True))
    case = StressCase(case_id="docx-clean-00", fmt="docx", scenario="clean",
                      expected="safe_output")
    skipped = StressCase(case_id="pdf-x-00", fmt="pdf", scenario="x", expected="safe_output",
                         generated=False, skip_reason="test")
    out = tmp_path / "stress.jsonl"
    settings = run_stress.run_mode("mapping", [(case, make_docx([TR_PARA])), (skipped, b"")],
                                   out, root=tmp_path / "store", overrides=NO_TERM_LISTS)
    assert settings.storage_root == tmp_path / "store" and settings.term_lists is False
    rows = [json.loads(x) for x in out.read_text(encoding="utf-8").splitlines()]
    assert rows[0]["actual_status"] == "needs_human_review"
    counts = rows[0]["llm_audits"]
    assert counts["audits"] >= 1 and counts["llm_failed"] == counts["audits"]
    assert counts["llm_ok"] == 0
    assert rows[1]["llm_audits"] is None  # never reached the pipeline


def test_mode_check_canaries_are_real_pii_only():
    from evaluation.goldbench.run_gold import mode_check_canaries
    from evaluation.goldbench.schema import (
        Channel,
        Criticality,
        GoldMention,
        IdentifierClass,
        Necessity,
    )

    def mention(surface: str, cls: IdentifierClass) -> GoldMention:
        return GoldMention(mention_id=surface, entity_id="e", subject_id="s", surface=surface,
                           occurrence=0, entity_type="X", identifier_class=cls,
                           necessity=Necessity.MANDATORY, criticality=Criticality.HIGH,
                           channel=Channel.BODY)

    gold = [mention("Ahmet Yılmaz", IdentifierClass.DIRECT),
            mention("Mühendis", IdentifierClass.QUASI),
            mention("Yönetim Kurulu", IdentifierClass.NO_MASK)]
    assert mode_check_canaries(gold) == ["Ahmet Yılmaz", "Mühendis"]

"""Strict scorer copy (evaluation/strict): sha pin, value-free output, adapter guard rails.

No model is loaded: the engine adapter is replaced by a stub wherever run_strict() runs.
"""
from __future__ import annotations

import hashlib
import json
import socket
from pathlib import Path

import pytest

from evaluation.strict import run, scorer
from tests import posix_only

STRICT_DIR = Path(__file__).resolve().parents[2] / "evaluation" / "strict"
PINNED_SCORER_SHA256 = "bd4a6816969109a9cc5c96695c70e8adb8ac1b3cbefeb1e7274fa3d1d9c9253b"
SURFACE = "Ayşe Yılmaz"  # synthetic
CANARY = "TR330006100519786457841326"  # synthetic


def test_scorer_is_byte_identical_to_v2():
    digest = hashlib.sha256((STRICT_DIR / "scorer.py").read_bytes()).hexdigest()
    assert digest == PINNED_SCORER_SHA256, "scorer.py changed: a new scorer version is required"


def test_run_uses_the_local_scorer_copy():
    assert run.gold_case is scorer.gold_case
    assert run.summarize_gold is scorer.summarize_gold


def test_gold_case_reports_vhash_never_the_surface():
    case = {"id": "d1", "must_mask": [{"surface": SURFACE, "type": "PERSON", "critical": True}],
            "must_keep": ["Yönetim Kurulu"]}
    row = scorer.gold_case(case, "Hasta: <PERSON_1>, Yönetim Kurulu")
    mention = row["mentions"][0]
    assert mention["masked"] is True
    assert mention["vhash"] == hashlib.sha256(SURFACE.encode()).hexdigest()[:16]
    assert SURFACE not in json.dumps(row, ensure_ascii=False)
    assert row["keep_preserved"] == 1


def test_partial_residual_counts_as_an_escape():
    assert scorer.escape(SURFACE, "Hasta: <PERSON_1> Yılmaz") == (False, True)


def test_cli_refuses_the_studio_system(capsys):
    with pytest.raises(SystemExit):
        run.main(["--corpus", "x", "--out", "y", "--system", "studio"])
    assert "studio" in capsys.readouterr().err


def test_cli_refuses_an_existing_output_dir(tmp_path):
    with pytest.raises(SystemExit, match="already exists"):
        run.main(["--corpus", str(tmp_path), "--out", str(tmp_path)])


@pytest.fixture
def corpus(tmp_path):
    root = tmp_path / "corpus"
    root.mkdir()
    gold = [{"id": f"d{i}", "text": f"Hasta: {SURFACE}. Yönetim Kurulu",
             "must_keep": ["Yönetim Kurulu"],
             "must_mask": [{"surface": SURFACE, "type": "PERSON", "critical": True}]}
            for i in range(3)]
    probes = {"canaries": [{"id": "c1", "value": CANARY, "context_word": "IBAN", "critical": True,
                            "family": "IBAN"}] * 2,
              "over_mask_sentences": ["Genel Kurul toplandı.", "Bilanço onaylandı."]}
    (root / "goldbench-holdout.json").write_text(json.dumps(gold, ensure_ascii=False), "utf-8")
    (root / "probes.json").write_text(json.dumps(probes, ensure_ascii=False), "utf-8")
    (root / "stress-manifest.json").write_text("[]", "utf-8")
    return root


def test_run_strict_with_stub_engine_limits_panels_and_restores_socket(corpus, tmp_path,
                                                                      monkeypatch):
    # run_strict sets these; pre-setting them via monkeypatch restores the originals afterwards.
    for key, value in {"HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
                       "USE_PRIVACY_FILTER": "false"}.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(run, "_fable_anonymizer", lambda: (lambda text: text))  # masks nothing
    connect = socket.socket.connect
    out = tmp_path / "out"

    summary = run.run_strict(corpus, out, limit=1)

    assert socket.socket.connect is connect
    assert summary["complete"] is False and summary["limit"] == 1
    assert summary["gold"]["critical_recall"]["numerator"] == 0
    assert summary["gold"]["critical_recall"]["denominator"] == 1
    assert summary["probes"]["bare"] == {"numerator": 1, "denominator": 1, "rate": 1.0}
    assert summary["over_mask_sentences"]["denominator"] == 1
    assert summary["scorer_sha256"] == PINNED_SCORER_SHA256
    assert summary["allow_list"].startswith("none")
    artifact = out / "SYNTHETIC-MEASUREMENT-ONLY.json"
    if not posix_only.WINDOWS:  # permission bits are POSIX-only
        assert artifact.stat().st_mode & 0o777 == 0o600
    for name in ("metrics.json", "gold-safe.json", "probe-safe.json", "over-safe.json"):
        assert SURFACE not in (out / name).read_text(encoding="utf-8")


def test_run_strict_refuses_an_existing_dir_before_loading_the_engine(corpus, monkeypatch):
    monkeypatch.setattr(run, "_fable_anonymizer", lambda: pytest.fail("engine must not load"))
    with pytest.raises(FileExistsError):
        run.run_strict(corpus, corpus)

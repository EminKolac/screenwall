"""Scorecard orchestration with stubbed sections (no engine, no model), the Markdown report,
the raw-value guard, run-id allocation, and the section aggregations fed with synthetic rows."""
from __future__ import annotations

import hashlib
import json
import unicodedata
from datetime import date

import pytest

from evaluation import scorecard
from evaluation.scorecard_common import frac, vhash
from evaluation.scorecard_real import density_record, select_real_pdfs, summarize_real
from evaluation.scorecard_report import FAIL, NOT_MEASURED, PASS, evaluate_gates
from evaluation.scorecard_sections import (
    FORMATS,
    V5_SUBSET_IDS,
    gold_block,
    stress_block,
    strict_block,
)
from evaluation.strict.scorer import fraction, gold_case, summarize_gold

SURFACE = "Ayşe Yılmaz Demirtaş"  # synthetic, planted in the test corpus
CANARY = "TR330006100519786457841326"  # synthetic
OTHER_IDS = tuple(f"{d}-{i:03d}" for d in ("health", "hr", "public", "correspondence")
                  for i in range(3, 40, 4))
DAY = date.today().isoformat()


def _mention(masked: bool) -> dict:
    return {"mention_id": "m1", "entity_id": "e1", "subject_id": "s1", "vhash": "0" * 16,
            "entity_type": "PERSON", "identifier_class": "DIRECT", "necessity": "mandatory",
            "criticality": "critical", "channel": "body", "located": True,
            "detected_chars": 10, "total_chars": 10, "fully_detected": True,
            "partially_detected": False, "masked": masked, "residual_chars": 0,
            "leaked_in_export": False}


def _gold_rec(doc_id: str, fmt: str, masked: bool = True) -> dict:
    return {"id": f"{doc_id}:{fmt}", "doc_id": doc_id, "format": fmt, "result": "processed",
            "status": "approved", "seconds": 0.2, "mode_check": {"passed": True},
            "metrics": {"char_precision": 0.8}, "mentions": [_mention(masked)]}


def gold_stub(ctx):
    recs = [_gold_rec(d, f, masked=d != "health-003")
            for d in V5_SUBSET_IDS + OTHER_IDS for f in FORMATS]
    subset = gold_block([r for r in recs if r["doc_id"] in V5_SUBSET_IDS], 20)
    subset.update(rule="first 20", ids=list(V5_SUBSET_IDS), rule_matches_holdout_order=True)
    return {"llm": ctx.llm, "complete": True, "full": gold_block(recs, 60), "subset20": subset,
            "llm_evidence": None, "raw_results": str(ctx.work_dir / "results.jsonl")}


def strict_stub(ctx):
    cases = [{"id": f"d{i}", "must_mask": [{"surface": f"Kişi Adı {i}", "type": "PERSON",
                                            "critical": True}], "must_keep": ["Yönetim Kurulu"]}
             for i in range(3)]
    summary = {"gold": summarize_gold([gold_case(c, "<PERSON_1>") for c in cases]),
               "probes": {"bare": fraction(0, 16), "contextual": fraction(1, 16)},
               "over_mask_sentences": fraction(11, 40), "scorer_sha256": "bd4a68" + "0" * 58,
               "corpus_sha256": {}, "complete": True, "limit": 0, "allow_list": "none",
               "external_network": "blocked"}
    probe_rows = [{"index": i, "variant": v, "missed": i == 0 and v == "contextual",
                   "critical": True, "unprocessed": False}
                  for i in range(16) for v in ("bare", "contextual")]
    return strict_block(summary, probe_rows)


def _stress_row(expected: str, status: str, verdict: str, leaked: bool = False) -> dict:
    return {"case_id": "c", "fmt": "pdf", "scenario": "s", "expected": expected,
            "actual_status": status, "verdict": verdict, "planted_leaked": leaked,
            "architecturally_safe": False, "generated": True, "seconds": 6.5,
            "over_conservative": expected == "safe_output" and status == "needs_human_review"}


def stress_stub(ctx):
    rows = ([_stress_row("safe_output", "approved", "pass")] * 59
            + [_stress_row("safe_output", "needs_human_review", "pass")] * 3
            + [_stress_row("fail_closed", "rejected:invalid", "pass")] * 10)
    block = stress_block(rows)
    block.update(llm=ctx.llm, complete=True, llm_evidence=None,
                 corpus={"manifest_sha256": "6987da" + "0" * 58, "files": 72})
    return block


def failing_stub(ctx):
    raise RuntimeError("boom")


STUBS = {"gold": gold_stub, "strict": strict_stub, "stress": stress_stub}


@pytest.fixture
def env(tmp_path, monkeypatch):
    for key, value in scorecard.OFFLINE_ENV.items():
        monkeypatch.setenv(key, value)  # main() sets them; monkeypatch restores the originals
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    (corpus / "goldbench-holdout.json").write_text(json.dumps([{
        "id": "finance-003", "text": f"Hasta: {SURFACE}", "must_keep": [],
        "must_mask": [{"surface": SURFACE, "type": "PERSON", "critical": True}]}],
        ensure_ascii=False), encoding="utf-8")
    (corpus / "probes.json").write_text(json.dumps({"canaries": [{
        "id": "c1", "value": CANARY, "context_word": "IBAN", "critical": True, "family": "IBAN"}],
        "over_mask_sentences": []}), encoding="utf-8")
    (corpus / "stress-manifest.json").write_text("[]", encoding="utf-8")
    return {"corpus": corpus, "results": tmp_path / "results", "work": tmp_path / "work"}


def _main(env, *args, runners=STUBS):
    argv = ["--corpus", str(env["corpus"]), *args]
    return scorecard.main(argv, runners=runners, results_root=env["results"],
                          work_root=env["work"])


def test_orchestration_writes_expected_json_and_markdown(env):
    assert _main(env, "--tag", "t", "--sections", "gold,strict,stress") == scorecard.EXIT_OK

    out = env["results"] / f"{DAY}-t"
    card = json.loads((out / "scorecard.json").read_text(encoding="utf-8"))
    assert {"schema", "run_id", "started_at", "finished_at", "complete", "config", "gates",
            "sections", "work_dir", "pii_scan"} <= card.keys()
    assert card["run_id"] == f"{DAY}-t" and card["complete"] is True
    assert list(card["sections"]) == ["gold", "strict", "stress"]
    for section in card["sections"].values():
        assert section["status"] == "ok" and section["elapsed_seconds"] >= 0
    assert card["config"]["llm_settings"]["auditor_provider"] == "mlx"
    assert card["pii_scan"] == {"values_checked": 2, "min_length": 6, "hits": 0}
    gold = card["sections"]["gold"]
    assert gold["full"]["critical_recall"] == frac(177, 180)
    assert gold["subset20"]["critical_recall"] == frac(60, 60)
    strict = card["sections"]["strict"]
    assert strict["canary_escapes"] == frac(1, 32)
    assert strict["must_keep_kept"] == frac(0, 3)
    assert card["sections"]["stress"]["safe_delivery"] == frac(59, 62)

    md = (out / "scorecard.md").read_text(encoding="utf-8")
    assert "| Kapı | Hedef | Değer | Sonuç | Not |" in md
    assert "| Kritik recall (partial guard) | 3/3 |" in md
    assert "| Kritik recall (mention × format) | 177/180 | 60/60 | pipeline |" in md
    assert "| Güvenli teslim: safe_output → onaylı, sızıntısız | 59/62 |" in md
    assert "KISMİ KOŞU" not in md


def test_limit_marks_the_run_partial(env):
    assert _main(env, "--tag", "s", "--sections", "strict", "--limit", "2") == 0
    md = (env["results"] / f"{DAY}-s" / "scorecard.md").read_text(encoding="utf-8")
    assert "KISMİ KOŞU" in md


def test_failed_section_is_recorded_and_others_still_run(env):
    runners = {**STUBS, "gold": failing_stub}
    assert _main(env, "--tag", "e", "--sections", "gold,strict", runners=runners) == 1
    card = json.loads((env["results"] / f"{DAY}-e" / "scorecard.json").read_text("utf-8"))
    assert card["sections"]["gold"] == {"status": "error", "error": "RuntimeError",
                                        "elapsed_seconds": card["sections"]["gold"]
                                        ["elapsed_seconds"]}
    assert card["sections"]["strict"]["status"] == "ok"
    assert card["complete"] is False


def test_real_section_is_skipped_without_real_n(env):
    runners = {"real": failing_stub}
    assert _main(env, "--tag", "r", "--sections", "real", runners=runners) == 0
    card = json.loads((env["results"] / f"{DAY}-r" / "scorecard.json").read_text("utf-8"))
    assert card["sections"]["real"]["status"] == "skipped"


def test_raw_value_in_a_section_blocks_the_report(env, capsys):
    runners = {"strict": lambda ctx: {**strict_stub(ctx), "oops": f"kaçak {SURFACE}"}}
    assert _main(env, "--tag", "x", "--sections", "strict", runners=runners) == 3
    assert not (env["results"] / f"{DAY}-x").exists()
    err = capsys.readouterr().err
    assert vhash(SURFACE) in err and SURFACE not in err


def test_llm_on_stops_before_any_work_when_the_model_is_missing(env, monkeypatch):
    from app.audit.ollama_provider import OllamaProvider

    monkeypatch.setattr(OllamaProvider, "is_available", lambda self: False)
    assert _main(env, "--tag", "l", "--sections", "stress", "--llm", "on") == 2
    assert not env["results"].exists() and not env["work"].exists()


def test_existing_run_id_is_never_reused(tmp_path):
    (tmp_path / "r" / "2026-09-24-t").mkdir(parents=True)
    (tmp_path / "w" / "2026-09-24-t-2").mkdir(parents=True)
    run_id = scorecard.allocate_run_id("t", tmp_path / "r", tmp_path / "w", date(2026, 9, 24))
    assert run_id == "2026-09-24-t-3"


@pytest.mark.parametrize("bad", ["../x", "a/b", "", "-x"])
def test_tag_must_be_a_plain_name(bad):
    with pytest.raises(SystemExit):
        scorecard.parse_args(["--tag", bad])


def test_vhash_never_equals_the_raw_text():
    for value in (SURFACE, CANARY, "a", ""):
        h = vhash(value)
        assert h != value and len(h) == 16 and int(h, 16) >= 0
        assert h == hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]
    assert scorecard.find_raw_values([f"x {CANARY} y"], [CANARY]) == [vhash(CANARY)]


def test_gates_need_llm_on_for_the_stress_thresholds():
    ok_stress = {"status": "ok", "complete": True, "leaks_approved": frac(0, 72),
                 "safe_delivery": frac(59, 62),
                 "llm_evidence": {"median_seconds_per_file": 6.8, "plausible": True}}
    off = {g["gate"]: g["verdict"] for g in evaluate_gates({"stress": ok_stress}, "off")}
    on = {g["gate"]: g["verdict"] for g in evaluate_gates({"stress": ok_stress}, "on")}
    assert off["Stres: güvenli teslim (canlı LLM)"] == NOT_MEASURED
    assert on["Stres: güvenli teslim (canlı LLM)"] == PASS
    assert on["LLM denetçisi gerçekten çalıştı (medyan sn/dosya)"] == PASS
    slow_heuristic = {**ok_stress, "llm_evidence": {"median_seconds_per_file": 0.1,
                                                    "plausible": False}}
    verdicts = {g["gate"]: g["verdict"] for g in evaluate_gates({"stress": slow_heuristic}, "on")}
    assert verdicts["LLM denetçisi gerçekten çalıştı (medyan sn/dosya)"] == FAIL


def test_stress_safe_delivery_counts_only_clean_approvals():
    rows = [_stress_row("safe_output", "approved", "pass"),
            _stress_row("safe_output", "approved", "critical_false_approval", leaked=True),
            _stress_row("safe_output", "needs_human_review", "pass"),
            _stress_row("fail_closed", "rejected:invalid", "pass")]
    block = stress_block(rows)
    assert block["safe_delivery"] == frac(1, 3)
    assert block["leaks_approved"] == frac(1, 4)
    assert block["fail_closed_respected"] == frac(1, 1)
    assert block["routed_to_review"] == 1


def test_real_selection_is_sorted_by_nfc_name_and_skips_long_pdfs(tmp_path):
    names = ["b.pdf", "a.pdf", "c.PDF", "notes.txt", unicodedata.normalize("NFD", "ç.pdf")]
    for name in names:
        (tmp_path / name).write_bytes(b"%PDF-1.4")
    pages = {"a.pdf": 99, "b.pdf": 3, "c.PDF": 5}
    selected, skipped = select_real_pdfs(tmp_path, 2, max_pages=60, max_mb=0,
                                         page_counter=lambda p: pages.get(p.name, 1))
    assert [(p.name, n) for p, n in selected] == [("b.pdf", 3), ("c.PDF", 5)]
    assert skipped == [{"file": "a.pdf", "reason": "too_many_pages:99"}]
    again, _ = select_real_pdfs(tmp_path, 3, max_pages=60, max_mb=0,
                                page_counter=lambda p: pages.get(p.name, 1))
    assert unicodedata.normalize("NFC", again[-1][0].name) == "ç.pdf"


def test_density_counts_underscore_families():
    rec = density_record(2000, "<PERSON_1> ve <US_BANK_NUMBER_2>, yine <PERSON_1>")
    assert rec["families"] == {"PERSON": 2, "US_BANK_NUMBER": 1}
    assert rec["placeholders"] == 3 and rec["redaction_density"] == 1.5
    summary = summarize_real([{**rec, "result": "processed", "seconds": 1.0},
                              {"result": "error", "error": "ExtractionFailed", "seconds": 0.1}])
    assert summary["measured"] == 1 and summary["errors"] == 1
    assert summary["redaction_density"] == 1.5
    assert summary["family_share"] == {"PERSON": 0.6667, "US_BANK_NUMBER": 0.3333}

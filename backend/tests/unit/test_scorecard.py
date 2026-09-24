"""Scorecard orchestration with stubbed sections (no engine, no model), the Markdown report,
the raw-value guard, run-id allocation, and the section aggregations fed with synthetic rows."""
from __future__ import annotations

import hashlib
import json
import unicodedata
from datetime import date

import pytest

from evaluation import scorecard
from evaluation.scorecard_common import frac, llm_audit_totals, llm_evidence, vhash
from evaluation.scorecard_real import density_record, select_real_pdfs, summarize_real
from evaluation.scorecard_report import FAIL, LLM_GATE, NOT_MEASURED, PASS, evaluate_gates
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
HOLDOUT_SURFACE = "Mehmet Kaan Öztürkoğlu"  # synthetic, in the stubbed holdout gold
KEEP_TERM = "Yönetim Kurulu Kararı"  # a NO_MASK term: ordinary words, never scanned
OTHER_IDS = tuple(f"{d}-{i:03d}" for d in ("health", "hr", "public", "correspondence")
                  for i in range(3, 40, 4))
DAY = date.today().isoformat()
HOLDOUT_ROWS = [{"doc_id": "finance-003", "split": "holdout", "mentions": [
    {"surface": HOLDOUT_SURFACE, "identifier_class": "DIRECT"},
    {"surface": KEEP_TERM, "identifier_class": "NO_MASK"}]}]


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


def real_stub(ctx):
    rec = {**density_record(2000, "<PERSON_1>"), "result": "processed", "seconds": 1.0}
    return {**summarize_real([rec]), "requested": ctx.real, "complete": True, "skipped": [],
            "selection_rule": "first N", "max_pages": 60, "path": "engine", "per_document": [
                {"file": "a.pdf", "pages": 1, **rec}]}


STUBS = {"gold": gold_stub, "strict": strict_stub, "stress": stress_stub}


@pytest.fixture
def env(tmp_path, monkeypatch):
    for key, value in scorecard.OFFLINE_ENV.items():
        monkeypatch.setenv(key, value)  # main() sets them; monkeypatch restores the originals
    # the guard's gold source = the holdout the gold section scores; stubbed to stay hermetic
    monkeypatch.setattr(scorecard, "load_holdout_rows", lambda: HOLDOUT_ROWS)
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
    assert {"schema", "run_id", "started_at", "finished_at", "complete", "skipped", "config",
            "gates", "sections", "work_dir", "pii_scan"} <= card.keys()
    # a --sections subset is never a complete scorecard; what was not run is named
    assert card["run_id"] == f"{DAY}-t" and card["complete"] is False
    assert card["skipped"] == [{"section": "real", "reason": "not in --sections"}]
    assert list(card["sections"]) == ["gold", "strict", "stress"]
    for section in card["sections"].values():
        assert section["status"] == "ok" and section["elapsed_seconds"] >= 0
    assert card["config"]["llm_settings"]["auditor_provider"] == "mlx"
    assert card["config"]["pipeline_settings_overrides"] == {
        "term_lists": False, "allow_terms": "", "deny_terms": ""}
    assert card["pii_scan"] == {"values_checked": 3, "min_length": 6, "hits": 0,
                                "sources": {"goldbench_holdout": 1, "v2_corpus": 2}}
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
    assert "| Ölçüm | Holdout (60/60 belge) | v5 alt kümesi (20/20 belge) | Ölçüm yolu |" in md
    assert "| Güvenli teslim: safe_output → onaylı, sızıntısız | 59/62 |" in md
    assert "EKSİK KOŞU** — atlanan: real (not in --sections)" in md
    assert "KISMİ KOŞU" not in md


def test_all_four_sections_in_full_make_a_complete_run(env):
    runners = {**STUBS, "real": real_stub}
    assert _main(env, "--tag", "c", "--real", "1", runners=runners) == scorecard.EXIT_OK
    card = json.loads((env["results"] / f"{DAY}-c" / "scorecard.json").read_text("utf-8"))
    assert card["complete"] is True and card["skipped"] == []
    md = (env["results"] / f"{DAY}-c" / "scorecard.md").read_text(encoding="utf-8")
    assert "KISMİ KOŞU" not in md and "EKSİK KOŞU" not in md


def test_real_zero_is_not_complete_and_names_the_skip(env):
    runners = {**STUBS, "real": failing_stub}  # --real 0 never calls it
    assert _main(env, "--tag", "z", "--real", "0", runners=runners) == scorecard.EXIT_OK
    card = json.loads((env["results"] / f"{DAY}-z" / "scorecard.json").read_text("utf-8"))
    assert card["complete"] is False
    assert card["skipped"] == [{"section": "real", "reason": "--real 0"}]


def test_a_section_without_an_explicit_complete_flag_is_not_complete(env):
    runners = {**STUBS, "real": lambda ctx: {k: v for k, v in real_stub(ctx).items()
                                            if k != "complete"}}
    assert _main(env, "--tag", "n", "--real", "1", runners=runners) == scorecard.EXIT_OK
    card = json.loads((env["results"] / f"{DAY}-n" / "scorecard.json").read_text("utf-8"))
    assert card["complete"] is False and card["skipped"] == []
    md = (env["results"] / f"{DAY}-n" / "scorecard.md").read_text(encoding="utf-8")
    assert "KISMİ KOŞU" in md


def test_header_does_not_claim_llm_on_without_an_llm_section(env, monkeypatch):
    from app.audit.ollama_provider import OllamaProvider

    monkeypatch.setattr(OllamaProvider, "is_available",
                        lambda self: pytest.fail("strict alone must not probe Ollama"))
    assert _main(env, "--tag", "h", "--sections", "strict", "--llm", "on") == 0
    md = (env["results"] / f"{DAY}-h" / "scorecard.md").read_text(encoding="utf-8")
    assert "LLM denetçisi: kullanılmadı" in md and "LLM denetçisi: **on**" not in md
    card = json.loads((env["results"] / f"{DAY}-h" / "scorecard.json").read_text("utf-8"))
    assert card["config"]["llm_applies_to"] == []


def _with_empty_term_lists(runner):
    from evaluation.scorecard_common import term_list_record

    def run(ctx):
        return {**runner(ctx), "term_lists": term_list_record([], [], "stub")}

    return run


def test_markdown_shows_the_term_lists_of_every_section(env):
    from evaluation.scorecard_common import EMPTY_TERM_LISTS_SHA256

    runners = {name: _with_empty_term_lists(f) for name, f in STUBS.items()}
    assert _main(env, "--tag", "tl", "--sections", "gold,strict,stress", runners=runners) == 0
    md = (env["results"] / f"{DAY}-tl" / "scorecard.md").read_text(encoding="utf-8")
    assert (f"- Terim listeleri (allow/deny, motora giden): gold 0/0 · strict 0/0 · stress 0/0 "
            f"· sha256 `{EMPTY_TERM_LISTS_SHA256[:16]}…` = boş listeler") in md


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


def _evidence(seconds: float, failed: int = 0, missing: int = 0) -> dict:
    audits = {"audits": 80, "llm_ok": 80 - failed - missing, "llm_failed": failed,
              "without_llm": missing, "documents_audited": 70,
              "documents_not_fully_llm_audited": 1 if failed or missing else 0}
    return llm_evidence("on", seconds, audits)


def test_gates_need_llm_on_for_the_stress_thresholds():
    ok_stress = {"status": "ok", "complete": True, "leaks_approved": frac(0, 72),
                 "safe_delivery": frac(59, 62), "llm_evidence": _evidence(6.8)}
    off = {g["gate"]: g["verdict"] for g in evaluate_gates({"stress": ok_stress}, "off")}
    on = {g["gate"]: g["verdict"] for g in evaluate_gates({"stress": ok_stress}, "on")}
    assert off["Stres: güvenli teslim (canlı LLM)"] == NOT_MEASURED
    assert on["Stres: güvenli teslim (canlı LLM)"] == PASS
    assert on[LLM_GATE] == PASS
    slow_heuristic = {**ok_stress, "llm_evidence": _evidence(0.1)}
    verdicts = {g["gate"]: g["verdict"] for g in evaluate_gates({"stress": slow_heuristic}, "on")}
    assert verdicts[LLM_GATE] == FAIL


@pytest.mark.parametrize("failed,missing", [(1, 0), (0, 1)])
def test_llm_gate_needs_zero_failures_even_when_the_timing_looks_right(failed, missing):
    """Timing alone passed before: a few failed calls barely move the median."""
    stress = {"status": "ok", "complete": True, "leaks_approved": frac(0, 72),
              "safe_delivery": frac(59, 62), "llm_evidence": _evidence(6.8, failed, missing)}
    gates = {g["gate"]: g for g in evaluate_gates({"stress": stress}, "on")}
    assert gates[LLM_GATE]["verdict"] == FAIL
    assert "LLM kararı almadan" in gates[LLM_GATE]["note"]
    # a PASS "with a live LLM" cannot be claimed when the LLM did not audit every document
    assert gates["Stres: güvenli teslim (canlı LLM)"]["verdict"] == NOT_MEASURED
    leaky = {**stress, "leaks_approved": frac(1, 72)}
    gates = {g["gate"]: g for g in evaluate_gates({"stress": leaky}, "on")}
    assert gates["Stres: onaylı çıktıya sızıntı (canlı LLM)"]["verdict"] == FAIL  # still a FAIL


def test_llm_evidence_counts_failures_and_audits_without_an_llm():
    rows = [{"llm_audits": {"audits": 2, "llm_ok": 1, "llm_failed": 1}},
            {"llm_audits": {"audits": 1, "llm_ok": 0, "llm_failed": 0}},
            {"llm_audits": {"audits": 1, "llm_ok": 1, "llm_failed": 0}},
            {"llm_audits": None}, {}]
    totals = llm_audit_totals(rows)
    assert totals == {"documents_audited": 3, "audits": 4, "llm_ok": 2, "llm_failed": 1,
                      "without_llm": 1, "documents_not_fully_llm_audited": 2}
    ev = llm_evidence("on", 6.5, totals)
    assert ev["plausible"] and ev["llm_failures"] == 2 and ev["passed"] is False
    assert llm_evidence("on", 6.5, llm_audit_totals([]))["passed"] is False  # nothing audited
    assert llm_evidence("off", 6.5, totals) is None


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


# ------------------------------------------------------------------ raw-value guard sources

def test_guard_with_no_value_to_check_refuses_before_any_work(env, monkeypatch):
    monkeypatch.setattr(scorecard, "load_holdout_rows", lambda: [])
    empty = env["corpus"].parent / "empty-corpus"
    empty.mkdir()
    argv = ["--corpus", str(empty), "--tag", "g", "--sections", "strict"]
    code = scorecard.main(argv, runners=STUBS, results_root=env["results"],
                          work_root=env["work"])
    assert code == scorecard.EXIT_SETUP
    assert not env["results"].exists() and not env["work"].exists()
    with pytest.raises(scorecard.EmptyGuardError):
        scorecard.write_outputs({}, "", env["results"] / "x", [])
    assert not (env["results"] / "x").exists()


def test_guard_scans_the_gold_holdout_but_not_its_no_mask_terms(env):
    leak = {"strict": lambda ctx: {**strict_stub(ctx), "oops": HOLDOUT_SURFACE}}
    assert _main(env, "--tag", "hl", "--sections", "strict", runners=leak) == 3
    assert not (env["results"] / f"{DAY}-hl").exists()
    keep = {"strict": lambda ctx: {**strict_stub(ctx), "note": KEEP_TERM}}
    assert _main(env, "--tag", "hk", "--sections", "strict", runners=keep) == 0


def test_holdout_values_skip_no_mask_and_short_values():
    rows = [{"mentions": [{"surface": HOLDOUT_SURFACE, "identifier_class": "QUASI"},
                          {"surface": KEEP_TERM, "identifier_class": "NO_MASK"},
                          {"surface": "Ali", "identifier_class": "DIRECT"}]}]
    assert scorecard.holdout_gold_values(rows) == {HOLDOUT_SURFACE}


# ------------------------------------------------------------------------- fingerprint

def test_fingerprint_covers_evaluation_but_not_results_or_caches(tmp_path):
    root = tmp_path / "evaluation"
    (root / "goldbench" / "manifest").mkdir(parents=True)
    (root / "results" / "2026-09-24-x").mkdir(parents=True)
    (root / "__pycache__").mkdir()
    (root / "scorecard.py").write_text("A = 1\n", encoding="utf-8")
    (root / "goldbench" / "manifest" / "m.jsonl").write_text("{}\n", encoding="utf-8")

    def fp():
        return scorecard.source_fingerprint(root, "*", exclude_top=frozenset({"results"}))

    base = fp()
    (root / "results" / "2026-09-24-x" / "scorecard.json").write_text("{}", encoding="utf-8")
    (root / "__pycache__" / "scorecard.cpython-312.pyc").write_bytes(b"\0")
    (root / ".DS_Store").write_bytes(b"\0")
    assert fp() == base  # outputs and caches do not change it
    (root / "goldbench" / "manifest" / "m.jsonl").write_text("{\"x\": 1}\n", encoding="utf-8")
    assert fp() != base  # evaluation data does
    changed = fp()
    (root / "scorecard.py").write_text("A = 2\n", encoding="utf-8")
    assert fp() != changed  # and evaluation code does


def test_config_records_both_fingerprints(env):
    assert _main(env, "--tag", "fp", "--sections", "strict") == 0
    card = json.loads((env["results"] / f"{DAY}-fp" / "scorecard.json").read_text("utf-8"))
    for key in ("app_source_sha256", "evaluation_source_sha256"):
        assert len(card["config"][key]) == 64
    md = (env["results"] / f"{DAY}-fp" / "scorecard.md").read_text(encoding="utf-8")
    assert f"evaluation/ `{card['config']['evaluation_source_sha256'][:16]}`" in md


# ------------------------------------------------------------------------- term lists

def test_preflight_refuses_when_the_pipeline_ignores_term_lists(env, monkeypatch):
    import app.pipeline.terms as terms

    monkeypatch.setattr(terms, "effective_terms", lambda settings: ([], ["Genel Kurul"]))
    assert _main(env, "--tag", "p", "--sections", "strict") == scorecard.EXIT_SETUP
    assert not env["results"].exists() and not env["work"].exists()


def test_pipeline_term_lists_is_empty_only_with_the_lists_off(tmp_path, monkeypatch):
    from evaluation.llm_flag import build_settings
    from evaluation.scorecard_common import (
        EMPTY_TERM_LISTS_SHA256,
        NO_TERM_LISTS,
        TermListsActiveError,
        pipeline_term_lists,
    )

    monkeypatch.setenv("ALLOW_TERMS", "Proje Adı")
    monkeypatch.setenv("DENY_TERMS", "e2vc")
    (tmp_path / "user_settings.json").write_text(
        json.dumps({"never_mask": ["Genel Kurul"], "always_mask": ["Gizli Fon"]}), "utf-8")
    with pytest.raises(TermListsActiveError):  # the app default: seeded list + env + user
        pipeline_term_lists(build_settings("off", storage_root=tmp_path))
    record = pipeline_term_lists(build_settings("off", storage_root=tmp_path, **NO_TERM_LISTS))
    assert (record["allow"], record["deny"]) == (0, 0)
    assert record["sha256"] == EMPTY_TERM_LISTS_SHA256
    assert record["term_lists_setting"] is False


def _gold_ctx(tmp_path):
    from evaluation.scorecard_common import SectionContext

    work = tmp_path / "gold"
    work.mkdir()
    return SectionContext(llm="off", limit=0, real=0, real_max_pages=60, corpus=tmp_path,
                          work_dir=work)


def test_gold_section_runs_in_its_own_storage_root_without_term_lists(tmp_path, monkeypatch):
    from evaluation import scorecard_sections as sections
    from evaluation.goldbench import run_gold

    seen = {}

    def fake_run_mode(rows, mode, formats, out, limit=0, llm="off", *, root=None,
                      overrides=None):
        settings, _ = run_gold._repo(mode, llm, root=root, **(overrides or {}))
        seen.update(root=root, settings=settings)
        keep = {**_mention(True), "mention_id": "k", "identifier_class": "NO_MASK",
                "criticality": "low", "masked": False}
        lost = {**_mention(False), "mention_id": "l", "located": False}
        rec = {**_gold_rec("finance-003", "pdf"), "mentions": [_mention(True), keep, lost]}
        out.write_text(json.dumps(rec) + "\n", encoding="utf-8")
        return settings

    monkeypatch.setenv("ALLOW_TERMS", "Proje Adı")
    monkeypatch.setattr(run_gold, "run_mode", fake_run_mode)
    monkeypatch.setattr(sections, "load_holdout_rows", lambda: HOLDOUT_ROWS)
    ctx = _gold_ctx(tmp_path)
    block = sections.run_gold_section(ctx)

    assert seen["root"] == ctx.work_dir / "storage"
    assert seen["settings"].storage_root == ctx.work_dir / "storage"
    assert (seen["settings"].term_lists, seen["settings"].allow_terms) == (False, "")
    assert (block["term_lists"]["allow"], block["term_lists"]["deny"]) == (0, 0)
    full = block["full"]
    assert full["critical_recall"] == frac(1, 1)
    assert full["critical_not_located"] == 1  # excluded from the recall above, but shown
    assert full["no_mask_violations"] == frac(0, 1)  # honest without an allow-list
    assert "honest" in block["measured_by"]["no_mask_violations"]
    assert "no allow-list" in block["measured_by"]["critical_recall"]


def test_no_mask_count_is_withheld_when_lists_were_on():
    recs = [{**_gold_rec("finance-003", "pdf"), "mentions": [
        _mention(True), {**_mention(True), "identifier_class": "NO_MASK", "masked": True}]}]
    block = gold_block(recs, 60)
    assert block["no_mask_violations"] is None
    assert "must_keep_kept" in block["no_mask_violations_reason"]
    assert gold_block(recs, 60, lists_off=True)["no_mask_violations"] == frac(1, 1)


def test_regression_gate_labels_a_partial_run_with_its_real_counts():
    recs = [_gold_rec("finance-003", f) for f in FORMATS]
    gold = {"status": "ok", "complete": False, "full": gold_block(recs, 60),
            "subset20": gold_block(recs, 20)}
    gate = next(g for g in evaluate_gates({"gold": gold}, "off") if "holdout" in g["gate"])
    assert "60 belge" not in gate["gate"]
    assert gate["value"] == "3/3 (1/60 belge)" and gate["note"].startswith("kısmi: 1/60 belge")


def test_real_section_with_an_errored_document_is_not_complete(tmp_path, monkeypatch):
    from evaluation import scorecard_real as real
    from evaluation.scorecard_common import SectionContext

    ok = {**density_record(1000, "<PERSON_1>"), "file": "a.pdf", "result": "processed",
          "pages": 1, "seconds": 1.0}
    bad = {"file": "b.pdf", "result": "error", "error": "ExtractionFailed", "pages": 1,
           "seconds": 0.1}
    monkeypatch.setattr(real, "select_real_pdfs", lambda *a, **k: (
        [(tmp_path / "a.pdf", 1), (tmp_path / "b.pdf", 1)], []))
    recs = iter([ok, bad])
    monkeypatch.setattr(real, "measure_pdf", lambda *a: next(recs))
    (tmp_path / "real").mkdir()
    ctx = SectionContext(llm="off", limit=0, real=2, real_max_pages=60, corpus=tmp_path,
                         work_dir=tmp_path / "real")
    block = real.run_real_section(ctx)
    assert block["errors"] == 1 and block["complete"] is False
    assert (block["term_lists"]["allow"], block["term_lists"]["deny"]) == (0, 0)


def test_mode_checks_are_broken_down_per_check():
    def rec(m2: bool) -> dict:
        checks = {"M1_mapping_complete": True, "M2_roundtrip_complete": m2,
                  "M3_mapping_contained": True}
        return {**_gold_rec("finance-003", "pdf"),
                "mode_check": {"passed": all(checks.values()), "checks": checks}}

    block = gold_block([rec(False), rec(True)], 60)
    assert block["mode_check_passed"] == frac(1, 2)
    assert block["mode_checks"] == {"M1_mapping_complete": frac(2, 2),
                                    "M2_roundtrip_complete": frac(1, 2),
                                    "M3_mapping_contained": frac(2, 2)}

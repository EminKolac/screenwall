"""GoldBench rapor toplama mantığı — sentetik satırlarla, gerçek koşu gerektirmeden.

Odak: gate kararlarının (PASS / FAIL / ÖLÇÜLMEDİ) doğruluğu. En tehlikeli hata, ölçülmemiş bir
kriteri geçmiş saymaktır; testlerin çoğu tam olarak onu kovalar.
"""
from __future__ import annotations

import json

import pytest

from evaluation.goldbench import report_gold as rg


def mention(**kw) -> dict:
    base = {
        "mention_id": "m1", "entity_id": "S0:full_name", "subject_id": "S0",
        "vhash": "abc123", "entity_type": "PERSON", "identifier_class": "DIRECT",
        "necessity": "mandatory", "criticality": "critical", "channel": "body",
        "located": True, "detected_chars": 10, "total_chars": 10,
        "fully_detected": True, "partially_detected": False, "masked": True,
        "residual_chars": 0, "leaked_in_export": False,
    }
    base.update(kw)
    return base


def doc(mentions: list[dict], doc_id: str = "d0", char_precision: float = 1.0,
        **kw) -> dict:
    rec = {
        "id": f"{doc_id}:docx", "doc_id": doc_id, "format": "docx", "domain": "finance",
        "language": "tr", "split": "dev", "mode": "mapping", "result": "processed",
        "status": "approved", "seconds": 1.0,
        "metrics": {"char_precision": char_precision},
        "mentions": mentions,
        "mode_check": {"passed": True, "checks": {}},
    }
    rec.update(kw)
    return rec


def blob_for(rows: list[dict], stress_path=None, inf_rows=None) -> dict:
    return rg.build_blob("t", "mapping", rows, {}, stress_path, inf_rows or [])


# --------------------------------------------------------------------- boş girdi

def test_empty_rows_do_not_divide_by_zero():
    b = blob_for([])
    assert b["documents"]["records"] == 0
    assert b["detection"]["mention_recall"] == 0.0
    assert b["detection"]["redaction_coverage_score"] == 0.0
    # Hiçbir şey ölçülemediğinde gate GEÇTİ diyemez.
    assert b["release_gate"]["overall"] == rg.GATE_INCOMPLETE
    assert b["release_gate"]["passed"] == 0


def test_document_without_mentions_is_tolerated():
    b = blob_for([doc([]), doc([], doc_id="d1")])
    assert b["documents"]["records"] == 2
    assert b["detection"]["mentions_total"] == 0
    assert b["release_gate"]["overall"] == rg.GATE_INCOMPLETE


# --------------------------------------------------------------------- toplama

def test_micro_average_not_per_document_average():
    """40 mention'lı belge, 1 mention'lı belgeden daha ağır basmalı."""
    good = doc([mention(mention_id=f"a{i}") for i in range(9)], doc_id="d0")
    bad = doc([mention(mention_id="b0", masked=False, detected_chars=0,
                       fully_detected=False)], doc_id="d1")
    det = rg.detection_metrics([good, bad])
    assert det["mentions_total"] == 10
    assert det["mention_recall"] == 0.9  # 9/10, belge ortalaması olsaydı 0.5 olurdu


def test_entity_ids_are_namespaced_per_document():
    """Aynı entity_id iki belgede geçerse birleşmemeli — belge başına entity sayılır."""
    rows = [doc([mention()], doc_id="d0"), doc([mention()], doc_id="d1")]
    assert rg.detection_metrics(rows)["entities_total"] == 2


def test_no_mask_violation_drives_over_masking_rate():
    rows = [doc([
        mention(),
        mention(mention_id="n1", entity_id="S0:job", identifier_class="NO_MASK",
                criticality="low", masked=True),
        mention(mention_id="n2", entity_id="S0:city", identifier_class="NO_MASK",
                criticality="low", masked=False),
    ])]
    det = rg.detection_metrics(rows)
    assert det["no_mask_total"] == 2
    assert det["no_mask_violations"] == 1
    assert det["over_masking_rate"] == 0.5
    assert det["mentions_total"] == 1  # NO_MASK recall'a girmez


def test_detected_total_chars_recovered_from_char_precision():
    rows = [doc([mention(detected_chars=10, total_chars=10)], char_precision=0.5)]
    assert rg._detected_total_chars(rows) == 20
    assert rg.detection_metrics(rows)["char_precision"] == 0.5


# --------------------------------------------------------------------- gate kararları

def _verdicts(gate: dict) -> dict[str, str]:
    return {c["criterion"]: c["verdict"] for c in gate["criteria"]}


def test_gate_passes_when_everything_measured_and_clean(tmp_path):
    stress = tmp_path / "stress.jsonl"
    stress.write_text(json.dumps({"case_id": "c0", "scenario": "s", "verdict": "pass",
                                  "generated": True, "architecturally_safe": False}) + "\n",
                      encoding="utf-8")
    inf = [{"utility_retention": 0.95, "utility_drop": 0.05,
            "attribute_inference_success": 0.02, "trir": 0.01}]
    rows = [doc([
        mention(),
        mention(mention_id="n1", entity_id="S0:city", identifier_class="NO_MASK",
                criticality="low", masked=False),
    ])]
    gate = blob_for(rows, stress_path=stress, inf_rows=inf)["release_gate"]
    assert gate["overall"] == rg.GATE_OK
    assert gate["unmeasured"] == 0
    assert set(_verdicts(gate).values()) == {rg.PASS}


def test_unmeasured_criteria_never_count_as_pass():
    """Stres ve fayda koşusu yoksa gate EKSİK olmalı — asla GEÇTİ."""
    rows = [doc([
        mention(),
        mention(mention_id="n1", entity_id="S0:city", identifier_class="NO_MASK",
                criticality="low", masked=False),
    ])]
    gate = blob_for(rows)["release_gate"]
    v = _verdicts(gate)
    assert v["utility_retention"] == rg.UNMEASURED
    assert v["stress critical_false_approval"] == rg.UNMEASURED
    assert v["critical_false_negatives"] == rg.PASS
    assert gate["overall"] == rg.GATE_INCOMPLETE
    assert gate["unmeasured"] == 2


def test_fail_beats_incomplete():
    """Bir kriter FAIL, bir kriter ÖLÇÜLMEDİ ise sonuç BAŞARISIZ olmalı."""
    rows = [doc([mention(masked=False, detected_chars=0, fully_detected=False)])]
    gate = blob_for(rows)["release_gate"]
    assert _verdicts(gate)["critical_false_negatives"] == rg.FAIL
    assert gate["overall"] == rg.GATE_FAIL


def test_missing_critical_mentions_is_unmeasured_not_pass():
    rows = [doc([mention(criticality="low")])]
    v = _verdicts(blob_for(rows)["release_gate"])
    assert v["critical_false_negatives"] == rg.UNMEASURED
    assert v["critical_entity_recall"] == rg.UNMEASURED


def test_missing_no_mask_control_makes_over_masking_unmeasured():
    """NO_MASK negatif kontrolü yoksa over_masking_rate 0.0 görünür — bu PASS sayılmamalı."""
    rows = [doc([mention()])]
    assert rg.detection_metrics(rows)["over_masking_rate"] == 0.0
    assert _verdicts(blob_for(rows)["release_gate"])["over_masking_rate"] == rg.UNMEASURED


@pytest.mark.parametrize("rate,expected", [(0.0, rg.PASS), (0.10, rg.PASS), (0.11, rg.FAIL)])
def test_over_masking_threshold_boundary(rate, expected):
    n = 100
    violations = round(rate * n)
    ms = [mention(mention_id=f"k{i}", entity_id=f"S0:k{i}", identifier_class="NO_MASK",
                  criticality="low", masked=i < violations) for i in range(n)]
    ms.append(mention())
    assert _verdicts(blob_for([doc(ms)])["release_gate"])["over_masking_rate"] == expected


@pytest.mark.parametrize("ret,expected", [(0.90, rg.PASS), (0.89, rg.FAIL), (None, rg.UNMEASURED)])
def test_utility_retention_threshold(ret, expected):
    inf = [{"utility_retention": ret}] if ret is not None else []
    gate = blob_for([doc([mention()])], inf_rows=inf)["release_gate"]
    assert _verdicts(gate)["utility_retention"] == expected


def test_leaked_in_export_fails_gate():
    rows = [doc([mention(leaked_in_export=True)])]
    assert _verdicts(blob_for(rows)["release_gate"])["leaked_in_export"] == rg.FAIL


def test_critical_entity_recall_threshold():
    """20 kritik entity'nin 19'u korunursa 0.95 → PASS; 18'i korunursa 0.90 → FAIL."""
    def build(ok: int) -> list[dict]:
        ms = [mention(mention_id=f"c{i}", entity_id=f"S{i}:name", masked=i < ok)
              for i in range(20)]
        return [doc(ms)]

    assert _verdicts(blob_for(build(19))["release_gate"])["critical_entity_recall"] == rg.PASS
    assert _verdicts(blob_for(build(18))["release_gate"])["critical_entity_recall"] == rg.FAIL


# --------------------------------------------------------------------- stres

def test_stress_critical_false_approval_fails_gate(tmp_path):
    p = tmp_path / "stress.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in [
        {"case_id": "a", "scenario": "split_run_pii", "verdict": "pass",
         "generated": True, "architecturally_safe": False},
        {"case_id": "b", "scenario": "format_variants", "verdict": "critical_false_approval",
         "generated": True, "architecturally_safe": False, "planted_leaked": True},
        {"case_id": "c", "scenario": "metadata", "verdict": "pass",
         "generated": True, "architecturally_safe": True},
    ]) + "\n", encoding="utf-8")
    st = rg.stress_metrics(p)
    assert st["critical_false_approval"] == 1
    # Mimari gereği güvenli vaka "gerçekten test edilen" sayısına GİRMEZ.
    assert st["actually_tested"] == 2
    assert st["architecturally_safe"] == 1
    gate = blob_for([doc([mention()])], stress_path=p)["release_gate"]
    assert _verdicts(gate)["stress critical_false_approval"] == rg.FAIL


def test_stress_absent_is_unmeasured():
    assert rg.stress_metrics(None) is None
    assert rg.stress_metrics.__doc__  # dokümante edilmiş davranış


# --------------------------------------------------------------------- gizlilik / fayda

def test_inference_absent_reports_none_not_zero():
    b = blob_for([doc([mention()])])
    assert b["privacy_attack"]["attribute_inference_success"] is None
    assert b["privacy_attack"]["trir"] is None
    assert b["utility"]["utility_retention"] is None


def test_inference_values_are_averaged():
    inf = [{"trir": 0.2, "attribute_inference_success": 0.1},
           {"trir": 0.4, "attribute_inference_success": 0.3}]
    m = rg.inference_metrics(inf)
    assert m["trir"] == 0.3
    assert m["attribute_inference_success"] == 0.2
    assert m["trir_n"] == 2


def test_partial_inference_fields_do_not_fabricate_the_rest():
    m = rg.inference_metrics([{"trir": 0.5}])
    assert m["trir"] == 0.5
    assert m["utility_retention"] is None


# --------------------------------------------------------------------- PII taraması

def test_raw_pii_field_scan_is_clean_for_valid_rows():
    scan = rg.raw_pii_field_scan([doc([mention()])])
    assert scan["clean"] is True
    assert scan["forbidden_fields"] == []


def test_raw_pii_field_scan_flags_surface_leak():
    scan = rg.raw_pii_field_scan([doc([mention(surface="Ahmet Yılmaz")])])
    assert scan["clean"] is False
    assert "surface" in scan["forbidden_fields"]


def test_raw_pii_field_scan_flags_missing_vhash():
    assert rg.raw_pii_field_scan([doc([mention(vhash="")])])["clean"] is False


def test_report_markdown_never_contains_raw_pii():
    rows = [doc([mention(surface="Ahmet Yılmaz")])]
    b = blob_for(rows)
    md = rg._md("mapping", {}, b["documents"], b["detection"], b["release_safety"],
                b["privacy_attack"], b["utility"], b["release_gate"], b["pii_field_scan"])
    assert "Ahmet" not in md
    assert "UYARI" in md  # sızıntı şüphesi rapora uyarı olarak yansır


# --------------------------------------------------------------------- iki mod karşılaştırması

def test_comparison_flags_identical_detection_metrics():
    rows = [doc([mention()])]
    m = rg.build_blob("t", "mapping", rows, {}, None, [])
    d = rg.build_blob("t", "destructive", rows, {}, None, [])
    cmp_blob = rg.compare(m, d)
    assert cmp_blob["d4_identical"] is True
    assert cmp_blob["differences"] == []
    md = rg._comparison_md("t", m, d, cmp_blob)
    assert "D4: ✓" in md


def test_comparison_flags_divergence_as_regression():
    m = rg.build_blob("t", "mapping", [doc([mention()])], {}, None, [])
    d = rg.build_blob("t", "destructive",
                      [doc([mention(masked=False)])], {}, None, [])
    cmp_blob = rg.compare(m, d)
    assert cmp_blob["d4_identical"] is False
    names = {x["metric"] for x in cmp_blob["differences"]}
    assert "mention_recall" in names
    md = rg._comparison_md("t", m, d, cmp_blob)
    assert "REGRESYON" in md


# --------------------------------------------------------------------- uçtan uca

def test_report_one_mode_writes_files(tmp_path, monkeypatch):
    monkeypatch.setattr(rg, "DATA", tmp_path)
    d = tmp_path / "results" / "x-mapping"
    d.mkdir(parents=True)
    (d / "results.jsonl").write_text(json.dumps(doc([mention()])) + "\n", encoding="utf-8")
    (d / "run_config.json").write_text(json.dumps({"tag": "x"}), encoding="utf-8")

    blob = rg._report_one_mode("x", "mapping")
    assert blob is not None
    assert (d / "REPORT.md").exists()
    saved = json.loads((d / "metrics.json").read_text(encoding="utf-8"))
    assert saved["release_gate"]["overall"] == rg.GATE_INCOMPLETE
    assert "Release gate" in (d / "REPORT.md").read_text(encoding="utf-8")


def test_main_auto_mode_handles_missing_results(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(rg, "DATA", tmp_path)
    assert rg.main(["--tag", "yok"]) == 1
    assert "bulunamadı" in capsys.readouterr().out


def test_main_writes_comparison_when_both_modes_present(tmp_path, monkeypatch):
    monkeypatch.setattr(rg, "DATA", tmp_path)
    for mode in ("mapping", "destructive"):
        d = tmp_path / "results" / f"y-{mode}"
        d.mkdir(parents=True)
        (d / "results.jsonl").write_text(
            json.dumps(doc([mention()], mode=mode)) + "\n", encoding="utf-8")
    rc = rg.main(["--tag", "y", "--mode", "both"])
    assert rc == 1  # ölçülmemiş kriterler var → sıfır dönmez
    assert (tmp_path / "results" / "y" / "COMPARISON.md").exists()
    cmp_blob = json.loads(
        (tmp_path / "results" / "y" / "comparison.json").read_text(encoding="utf-8"))
    assert cmp_blob["d4_identical"] is True

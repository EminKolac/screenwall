"""GoldBench stres korpusu üretim testleri.

Kapsam SADECE üretim mantığıdır — pipeline BURADA çalıştırılmaz (bu testler hızlı kalmalı;
uçtan uca ölçüm `evaluation/goldbench/run_stress.py` işidir).

Kritik iddia determinizmdir: aynı seed → aynı byte'lar → aynı sha256. Bu tutmazsa iki koşunun
sonuçları karşılaştırılamaz ve benchmark'ın regresyon tespit etme yeteneği kaybolur.
"""
from __future__ import annotations

import hashlib
import json
import zipfile
from io import BytesIO

import pytest

from app.extraction.base import UploadRejected, validate_upload
from evaluation.goldbench.stress import (
    ARCHITECTURALLY_SAFE,
    FAIL_CLOSED,
    FORMATS,
    PER_FORMAT,
    SAFE_OUTPUT,
    SCENARIO_FORMATS,
    build_corpus,
    build_one,
    corpus_hashes,
    plan,
    summary,
)

_MAX = 25 * 1024 * 1024


@pytest.fixture(scope="module")
def corpus():
    return build_corpus()


# --- determinizm --------------------------------------------------------------------------------

def test_corpus_hashes_are_stable_across_builds():
    """Aynı seed → aynı sha256. Konteyner zaman damgaları (zip date_time, dcterms:modified,
    w:date, PDF /ID ve annotation /M) normalize edilmezse bu test kırılır."""
    assert corpus_hashes() == corpus_hashes()


def test_rebuilding_a_single_case_gives_identical_bytes(corpus):
    for case, data in corpus:
        if not case.generated:
            continue
        assert hashlib.sha256(build_one(case)).hexdigest() == hashlib.sha256(data).hexdigest(), \
            f"{case.case_id} deterministik değil"


def test_case_ids_are_unique(corpus):
    ids = [c.case_id for c, _ in corpus]
    assert len(ids) == len(set(ids))


# --- kapsam / dağılım ---------------------------------------------------------------------------

def test_seventytwo_documents_evenly_split_across_formats(corpus):
    assert len(corpus) == 72
    for fmt in FORMATS:
        assert sum(1 for c, _ in corpus if c.fmt == fmt) == PER_FORMAT


def test_every_format_produces_real_bytes(corpus):
    magic = {"pdf": b"%PDF", "docx": b"PK", "xlsx": b"PK"}
    for case, data in corpus:
        if not case.generated:
            continue
        assert data, f"{case.case_id} boş"
        assert data.startswith(magic[case.fmt]), f"{case.case_id} yanlış magic"


def test_scenarios_only_appear_in_applicable_formats(corpus):
    for case, _ in corpus:
        assert case.fmt in SCENARIO_FORMATS[case.scenario], \
            f"{case.case_id}: senaryo bu formatta anlamlı değil"


def test_every_declared_scenario_is_actually_produced(corpus):
    produced = {c.scenario for c, _ in corpus}
    assert produced == set(SCENARIO_FORMATS)


# --- beklenti tutarlılığı -----------------------------------------------------------------------

def test_expected_is_binary_and_consistent_with_scenario(corpus):
    for case, _ in corpus:
        assert case.expected in (SAFE_OUTPUT, FAIL_CLOSED)
        if case.scenario in ("corrupt_ooxml", "zip_bomb"):
            assert case.expected == FAIL_CLOSED, f"{case.case_id} fail_closed olmalı"
        else:
            assert case.expected == SAFE_OUTPUT, f"{case.case_id} safe_output olmalı"


def test_safe_output_cases_carry_planted_values(corpus):
    for case, _ in corpus:
        if case.expected == SAFE_OUTPUT:
            assert case.planted_values, f"{case.case_id}: sızıntı aranacak değer yok"
            assert all(v.strip() for v in case.planted_values)


def test_fail_closed_cases_plant_nothing(corpus):
    """Bozuk konteynerde PII yoktur — bir sızıntı iddiası ölçülemez, o yüzden liste boş kalmalı."""
    for case, _ in corpus:
        if case.expected == FAIL_CLOSED:
            assert case.planted_values == []


def test_safe_dict_never_exposes_raw_values(corpus):
    """Rapor yüzeyi ham PII taşımamalı — sadece sha256[:16]."""
    for case, _ in corpus:
        d = case.safe_dict()
        assert "planted_values" not in d
        blob = json.dumps(d, ensure_ascii=False)
        for v in case.planted_values:
            assert v not in blob


# --- mimari güvenlik işaretlemesi ---------------------------------------------------------------

def test_architecturally_safe_flag_matches_the_declared_set(corpus):
    """`metadata` ve `external_link` export mimarisi gereği çıktıya ulaşamaz — bunların
    "test edildi ve geçti" sayılmaması için işaret DOĞRU olmalı."""
    for case, _ in corpus:
        assert case.architecturally_safe == (case.scenario in ARCHITECTURALLY_SAFE), \
            f"{case.case_id}: architecturally_safe yanlış işaretlenmiş"


def test_architecturally_safe_scenarios_are_actually_present(corpus):
    flagged = {c.scenario for c, _ in corpus if c.architecturally_safe}
    assert flagged == set(ARCHITECTURALLY_SAFE)


def test_non_flagged_scenarios_are_the_real_test_surface(corpus):
    tested = [c for c, _ in corpus if not c.architecturally_safe]
    assert len(tested) == len(corpus) - sum(1 for c, _ in corpus if c.architecturally_safe)
    assert tested, "gerçekten test edilen vaka kalmadı"


# --- üretilemeyen vakalar -----------------------------------------------------------------------

def test_ungenerated_cases_are_recorded_not_dropped(corpus):
    """Üretilemeyen bir senaryo SESSİZCE düşmez: korpusta kalır, gerekçesi yazılır."""
    assert len(corpus) == len(plan())
    for case, data in corpus:
        if case.generated:
            assert case.skip_reason == ""
        else:
            assert case.skip_reason, f"{case.case_id}: gerekçesiz atlandı"
            assert data == b""


def test_summary_reports_generation_gaps():
    s = summary()
    assert s["total"] == 72
    assert s["by_format"] == {f: PER_FORMAT for f in FORMATS}
    assert s["generated"] + len(s["not_generated"]) == s["total"]
    assert s["expected_fail_closed"] + s["expected_safe_output"] == s["total"]


# --- kapı davranışı (üretimin doğru şeyi ürettiğinin ucuz kanıtı) --------------------------------

def test_fail_closed_documents_are_rejected_by_upload_validation(corpus):
    for case, data in corpus:
        if case.expected != FAIL_CLOSED or not case.generated:
            continue
        with pytest.raises(UploadRejected):
            validate_upload(data, f"{case.case_id}.{case.fmt}", _MAX)


def test_safe_output_documents_pass_upload_validation(corpus):
    for case, data in corpus:
        if case.expected != SAFE_OUTPUT or not case.generated:
            continue
        validate_upload(data, f"{case.case_id}.{case.fmt}", _MAX)


def test_zip_bomb_carries_required_package_parts(corpus):
    """Reddin sebebi "eksik parça" değil gerçekten bomba koruması olmalı; aksi halde test
    zip-bomb kapısını hiç yoklamamış olur."""
    required = {"docx": "word/document.xml", "xlsx": "xl/workbook.xml"}
    for case, data in corpus:
        if case.scenario != "zip_bomb":
            continue
        names = set(zipfile.ZipFile(BytesIO(data)).namelist())
        assert "[Content_Types].xml" in names
        assert required[case.fmt] in names

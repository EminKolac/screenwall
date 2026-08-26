"""GoldBench dış geçerlilik adaptörleri — şema eşleme testleri.

BU TESTLER AĞA ÇIKMAZ. Fikstürler, canlı veriden DOĞRULANMIŞ gerçek alan adlarını birebir
taklit eden birkaç satırlık inline sözlüklerdir (bkz. tab.py / redactionbench.py docstring'leri).
Gerçek dataset gerektiren testler `pytest.mark.skipif(not is_fetched())` ile korunur.
"""
from __future__ import annotations

import json

import pytest

from evaluation.goldbench.external import (
    ADAPTERS,
    CANONICAL_ENTITY_TYPES,
    CONTEXTUAL,
    DATE,
    DIRECT,
    ID,
    LOCATION,
    MANDATORY,
    NO_MASK,
    ORG,
    OTHER,
    PERSON,
    QUASI,
    SENSITIVE_ATTRIBUTE,
    get_adapter,
    manifest_is_complete,
    tab,
)
from evaluation.goldbench.external import redactionbench as rb

# --------------------------------------------------------------------------------------------
# Fikstürler — canlı veriden doğrulanmış alan adlarıyla
# --------------------------------------------------------------------------------------------

TAB_DOC = {
    "doc_id": "001-83927",
    "text": "Case of 40593/04 v. Republic of Turkey. The Turkish applicant Mr Cengiz Polat.",
    "dataset_type": "dev",
    "quality_checked": True,
    "task": "Annotate the document to anonymise the following person: Cengiz Polat",
    "annotations": {
        "annotator1": {"entity_mentions": [
            {"entity_type": "CODE", "entity_mention_id": "em1", "start_offset": 8,
             "end_offset": 16, "span_text": "40593/04", "edit_type": "check",
             "identifier_type": "DIRECT", "entity_id": "e1",
             "confidential_status": "NOT_CONFIDENTIAL"},
            {"entity_type": "ORG", "entity_mention_id": "em2", "start_offset": 20,
             "end_offset": 38, "span_text": "Republic of Turkey", "edit_type": "insert",
             "identifier_type": "NO_MASK", "entity_id": "e2",
             "confidential_status": "NOT_CONFIDENTIAL"},
            {"entity_type": "DEM", "entity_mention_id": "em3", "start_offset": 44,
             "end_offset": 51, "span_text": "Turkish", "edit_type": "check",
             "identifier_type": "QUASI", "entity_id": "e3", "confidential_status": "ETHNIC"},
            {"entity_type": "PERSON", "entity_mention_id": "em4", "start_offset": 62,
             "end_offset": 77, "span_text": "Mr Cengiz Polat", "edit_type": "check",
             "identifier_type": "DIRECT", "entity_id": "e4",
             "confidential_status": "NOT_CONFIDENTIAL"},
        ]},
        "annotator2": {"entity_mentions": [
            # Aynı PERSON span'i ikinci annatörde de var → annotators=2 olmalı.
            {"entity_type": "PERSON", "entity_mention_id": "em9", "start_offset": 62,
             "end_offset": 77, "span_text": "Mr Cengiz Polat", "edit_type": "check",
             "identifier_type": "DIRECT", "entity_id": "e9",
             "confidential_status": "NOT_CONFIDENTIAL"},
        ]},
    },
}

RB_ROW = {
    "raw_text": "Name: Melissa Schettler\nEmail: m@x.edu\nMajor: Biochemistry",
    "spans": [
        {"start": 6, "end": 23, "label": "mandatory"},
        {"start": 31, "end": 38, "label": "mandatory"},
        {"start": 46, "end": 58, "label": "contextual"},
    ],
    "category": "academic",
    "genre": "_appeal_form",
    "is_synthetic": True,
    "original_document_url": None,
}


def _by_offset(spans, start):
    return next(s for s in spans if s.start == start)


# --------------------------------------------------------------------------------------------
# TAB
# --------------------------------------------------------------------------------------------

class TestTabMapping:
    def test_entity_types_kanonik_aileye_esleniyor(self):
        doc = tab.parse_document(TAB_DOC)
        assert doc.doc_id == "001-83927"
        assert doc.source == "tab"
        types = {s.native_type: s.entity_type for s in doc.spans}
        assert types == {"CODE": ID, "ORG": ORG, "DEM": OTHER, "PERSON": PERSON}
        assert all(s.entity_type in CANONICAL_ENTITY_TYPES for s in doc.spans)

    def test_identifier_class_ve_necessity(self):
        doc = tab.parse_document(TAB_DOC)
        code = _by_offset(doc.spans, 8)
        assert (code.identifier_class, code.necessity) == (DIRECT, MANDATORY)

        # NO_MASK korunur — over-masking negatif kontrolü.
        org = _by_offset(doc.spans, 20)
        assert (org.identifier_class, org.necessity) == (NO_MASK, CONTEXTUAL)

        # confidential_status=ETHNIC → SENSITIVE_ATTRIBUTE'a terfi, mandatory olur.
        dem = _by_offset(doc.spans, 44)
        assert (dem.identifier_class, dem.necessity) == (SENSITIVE_ATTRIBUTE, MANDATORY)

    def test_no_mask_gizli_ozelligi_ezer(self):
        # Annotatör "maskeleme" dediyse gizlilik etiketi bunu bozmamalı.
        assert tab.map_identifier_class("NO_MASK", "HEALTH") == NO_MASK
        assert tab.map_identifier_class("QUASI", "HEALTH") == SENSITIVE_ATTRIBUTE
        assert tab.map_identifier_class("QUASI", "NOT_CONFIDENTIAL") == QUASI
        # Bilinmeyen etiket → temkinli taraf (maskelenmeli).
        assert tab.map_identifier_class("BILINMEYEN", "") == QUASI

    def test_coklu_annotator_birlesim_ve_sayim(self):
        doc = tab.parse_document(TAB_DOC)
        person = _by_offset(doc.spans, 62)
        assert person.annotators == 2
        assert doc.meta["annotator_count"] == 2
        # Birleşim: annotator1'in tekil span'leri de kalmalı.
        assert len(doc.spans) == 4

    def test_offsetler_metne_denk_geliyor(self):
        doc = tab.parse_document(TAB_DOC)
        for span in doc.spans:
            assert doc.text[span.start:span.end] == span.surface

    def test_bozuk_mention_belgeyi_dusurmez(self):
        raw = json.loads(json.dumps(TAB_DOC))
        raw["annotations"]["annotator1"]["entity_mentions"].extend([
            {"entity_type": "PERSON", "start_offset": "abc", "end_offset": 5},
            {"entity_type": "PERSON", "start_offset": 10, "end_offset": 10},  # boş aralık
        ])
        doc = tab.parse_document(raw)
        assert len(doc.spans) == 4

    def test_to_gold_spans_sozlugu(self):
        doc = tab.parse_document(TAB_DOC)
        rows = tab.to_gold_spans(doc)
        assert len(rows) == len(doc.spans)
        row = next(r for r in rows if r["start"] == 62)
        assert row["doc_id"] == "001-83927"
        assert row["entity_type"] == PERSON
        assert row["identifier_class"] == DIRECT
        assert row["necessity"] == MANDATORY
        assert row["source"] == "tab"          # ana TR skoruyla karışmasın diye taşınır
        assert row["annotators"] == 2

    def test_datetime_ve_loc_eslemesi(self):
        raw = {"doc_id": "d", "text": "Ankara 2019", "annotations": {"a1": {"entity_mentions": [
            {"entity_type": "LOC", "start_offset": 0, "end_offset": 6, "span_text": "Ankara",
             "identifier_type": "QUASI", "confidential_status": "NOT_CONFIDENTIAL"},
            {"entity_type": "DATETIME", "start_offset": 7, "end_offset": 11, "span_text": "2019",
             "identifier_type": "QUASI", "confidential_status": "NOT_CONFIDENTIAL"},
        ]}}}
        doc = tab.parse_document(raw)
        assert [s.entity_type for s in doc.spans] == [LOCATION, DATE]


class TestTabGracefulDegradation:
    def test_fetch_edilmemisse_bos_liste(self, tmp_path):
        assert tab.is_fetched(root=tmp_path) is False
        assert tab.load(root=tmp_path) == []

    def test_bilinmeyen_split_exception_atmaz(self, tmp_path):
        result = tab.fetch(tmp_path, splits=("yok",))
        assert result.ok is False
        assert "yok" in result.error
        assert result.license == "MIT"        # lisans başarısızlıkta da kaydedilir

    def test_manifest_ok_false_ise_fetched_sayilmaz(self, tmp_path):
        dest = tmp_path / "tab"
        dest.mkdir()
        (dest / "fetch_manifest.json").write_text(
            json.dumps({"ok": False, "files": []}), encoding="utf-8")
        assert tab.is_fetched(root=tmp_path) is False


# --------------------------------------------------------------------------------------------
# RedactionBench
# --------------------------------------------------------------------------------------------

class TestRedactionBenchMapping:
    def test_label_esleme(self):
        doc = rb.parse_document(RB_ROW, index=0)
        assert doc.doc_id == "rb-0000"
        assert doc.source == "redactionbench"
        mandatory = _by_offset(doc.spans, 6)
        assert (mandatory.identifier_class, mandatory.necessity) == (DIRECT, MANDATORY)
        contextual = _by_offset(doc.spans, 46)
        assert (contextual.identifier_class, contextual.necessity) == (QUASI, CONTEXTUAL)

    def test_entity_type_her_zaman_other(self):
        # Dataset varlık türü VERMİYOR — bu benchmark'ta aile kırılımı yapılamaz.
        doc = rb.parse_document(RB_ROW)
        assert {s.entity_type for s in doc.spans} == {OTHER}

    def test_offsetler_yari_acik_araliktir(self):
        doc = rb.parse_document(RB_ROW)
        assert _by_offset(doc.spans, 6).surface == "Melissa Schettler"
        for span in doc.spans:
            assert doc.text[span.start:span.end] == span.surface

    def test_meta_alanlari_korunuyor(self):
        doc = rb.parse_document(RB_ROW)
        assert doc.meta["category"] == "academic"
        assert doc.meta["is_synthetic"] is True
        assert doc.meta["original_document_url"] is None

    def test_bozuk_ve_yinelenen_spanler(self):
        raw = json.loads(json.dumps(RB_ROW))
        raw["spans"].extend([
            {"start": 6, "end": 23, "label": "mandatory"},   # birebir yinelenen
            {"start": 5, "end": 5, "label": "mandatory"},    # boş aralık
            {"start": None, "end": 3, "label": "mandatory"}, # bozuk
        ])
        doc = rb.parse_document(raw)
        assert len(doc.spans) == 3

    def test_bilinmeyen_label_temkinli_tarafa_duser(self):
        doc = rb.parse_document({"raw_text": "abcdef",
                                 "spans": [{"start": 0, "end": 3, "label": "wat"}]})
        assert doc.spans[0].identifier_class == DIRECT
        assert doc.spans[0].necessity == MANDATORY

    def test_spanler_offsete_gore_sirali(self):
        raw = {"raw_text": "abcdefghij", "spans": [
            {"start": 5, "end": 7, "label": "contextual"},
            {"start": 0, "end": 2, "label": "mandatory"},
        ]}
        doc = rb.parse_document(raw)
        assert [s.start for s in doc.spans] == [0, 5]

    def test_to_gold_spans_sozlugu(self):
        doc = rb.parse_document(RB_ROW)
        rows = rb.to_gold_spans(doc)
        assert len(rows) == 3
        assert all(r["source"] == "redactionbench" for r in rows)
        assert all(r["entity_type"] == OTHER for r in rows)
        assert {r["necessity"] for r in rows} == {MANDATORY, CONTEXTUAL}


class TestRedactionBenchGracefulDegradation:
    def test_fetch_edilmemisse_bos_liste(self, tmp_path):
        assert rb.is_fetched(root=tmp_path) is False
        assert rb.load(root=tmp_path) == []

    def test_lisans_kaydediliyor(self):
        assert rb.LICENSE == "CC-BY-4.0"
        assert rb.LICENSE_URL.startswith("https://creativecommons.org/")

    def test_manifest_var_ama_dosya_yoksa_fetched_degil(self, tmp_path):
        dest = tmp_path / "redactionbench"
        dest.mkdir()
        (dest / "fetch_manifest.json").write_text(
            json.dumps({"ok": True, "files": [{"name": rb.LOCAL_NAME}]}), encoding="utf-8")
        assert manifest_is_complete(dest) is False
        assert rb.load(root=tmp_path) == []

    def test_manifest_ve_dosya_varsa_yukleniyor(self, tmp_path):
        # Ağ YOK: manifest ve JSONL elle yazılıyor, load() gerçekten okuyor mu bakılıyor.
        dest = tmp_path / "redactionbench"
        dest.mkdir()
        (dest / rb.LOCAL_NAME).write_text(
            json.dumps(RB_ROW, ensure_ascii=False) + "\n" + "bozuk-satir\n", encoding="utf-8")
        (dest / "fetch_manifest.json").write_text(
            json.dumps({"ok": True, "files": [{"name": rb.LOCAL_NAME}]}), encoding="utf-8")
        docs = rb.load(root=tmp_path)
        assert len(docs) == 1                  # bozuk satır sessizce atlanır
        assert len(docs[0].spans) == 3
        assert rb.load(limit=0, root=tmp_path) == []


# --------------------------------------------------------------------------------------------
# Ortak arayüz sözleşmesi
# --------------------------------------------------------------------------------------------

class TestAdapterContract:
    @pytest.mark.parametrize("name", ADAPTERS)
    def test_adaptorler_ayni_arayuzu_sunuyor(self, name):
        mod = get_adapter(name)
        for fn in ("is_fetched", "fetch", "load", "to_gold_spans"):
            assert callable(getattr(mod, fn)), f"{name}.{fn} eksik"
        assert getattr(mod, "LICENSE", "") != ""   # bilinmiyorsa bile "unknown" yazılmalı

    def test_bilinmeyen_adaptor_hata_verir(self):
        with pytest.raises(ValueError):
            get_adapter("bilinmeyen")

    @pytest.mark.parametrize("name", ADAPTERS)
    def test_fetch_edilmemis_kokte_load_bos(self, name, tmp_path):
        """Dış geçerlilik katmanı benchmark'ın geri kalanını ASLA çökertmez."""
        mod = get_adapter(name)
        assert mod.is_fetched(root=tmp_path) is False
        assert mod.load(limit=5, root=tmp_path) == []


# --------------------------------------------------------------------------------------------
# Gerçek dataset gerektiren testler — indirilmemişse atlanır
# --------------------------------------------------------------------------------------------

@pytest.mark.skipif(not tab.is_fetched(), reason="TAB fetch edilmemiş (korpus kurulum adımı)")
def test_gercek_tab_yuklenebiliyor():
    docs = tab.load(limit=3)
    assert docs
    for doc in docs:
        assert doc.text and doc.doc_id
        for span in doc.spans:
            assert doc.text[span.start:span.end] == span.surface
            assert span.entity_type in CANONICAL_ENTITY_TYPES


@pytest.mark.skipif(not rb.is_fetched(),
                    reason="RedactionBench fetch edilmemiş (korpus kurulum adımı)")
def test_gercek_redactionbench_yuklenebiliyor():
    docs = rb.load(limit=3)
    assert docs
    for doc in docs:
        assert doc.text and doc.doc_id
        for span in doc.spans:
            assert doc.text[span.start:span.end] == span.surface
            assert span.necessity in (MANDATORY, CONTEXTUAL)

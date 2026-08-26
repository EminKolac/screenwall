"""TAB (Text Anonymization Benchmark) adaptörü — dış geçerlilik kontrolü.

KAYNAK: https://github.com/NorskRegnesentral/text-anonymization-benchmark
1.268 İngilizce AİHM (ECHR) kararı; direct/quasi identifier, gizli (confidential) öznitelik ve
coreference anotasyonlu. Lisans: MIT (repo LICENSE.txt).

ŞEMA DOĞRULAMA DURUMU: DOĞRULANDI (canlı `echr_dev.json` üstünde, 127 belge).
Aşağıdaki alan adları ve değer sözlükleri varsayım değil, gerçek dosyadan sayılarak çıkarıldı:

  belge: {doc_id, text, annotations, dataset_type, meta, task, quality_checked}
  annotations: {"<annotator_id>": {"entity_mentions": [ ... ]}}   # ÇOKLU ANNOTATÖR
  mention: {entity_type, entity_mention_id, start_offset, end_offset, span_text,
            edit_type, identifier_type, entity_id, confidential_status}

  entity_type        ∈ {PERSON, CODE, ORG, DEM, DATETIME, LOC, QUANTITY, MISC}
  identifier_type    ∈ {DIRECT, QUASI, NO_MASK}
  confidential_status ∈ {NOT_CONFIDENTIAL, POLITICS, ETHNIC, BELIEF, HEALTH, SEX}

AĞ ERİŞİMİ: `fetch()` tek seferlik KORPUS KURULUM adımıdır. Runtime local-first garantisi
değişmez — bu modül `app/` içinden asla import edilmez, yalnızca benchmark koşarken çalışır.

SONUÇ BİRLEŞTİRME: TAB skorları ana Türkçe GoldBench skoruyla BİRLEŞTİRİLMEZ. İngilizce hukuk
metni, farklı annotation felsefesi — ayrı tabloda, "dış geçerlilik" başlığı altında raporlanır.
"""
from __future__ import annotations

import json
from pathlib import Path

from . import (
    CONTEXTUAL,
    DATE,
    DEFAULT_ROOT,
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
    ExternalDoc,
    ExternalSpan,
    FetchResult,
    download,
    manifest_is_complete,
    sha256_file,
    utc_now,
    write_manifest,
)

SOURCE = "tab"
LICENSE = "MIT"
LICENSE_URL = "https://github.com/NorskRegnesentral/text-anonymization-benchmark/blob/master/LICENSE.txt"
BASE_URL = "https://raw.githubusercontent.com/NorskRegnesentral/text-anonymization-benchmark/master"

#: Repodaki split dosyaları. Varsayılan olarak dev+test indirilir; train (~47 MB) opsiyoneldir.
SPLIT_FILES = {"train": "echr_train.json", "dev": "echr_dev.json", "test": "echr_test.json"}
DEFAULT_SPLITS = ("dev", "test")

#: TAB entity_type → bizim kanonik ailemiz.
#: CODE, TAB'da dosya/başvuru numarası gibi kodlar için kullanılıyor → ID.
#: DEM (demografik: "Turkish"), QUANTITY ve MISC'in bizde birebir karşılığı yok → OTHER.
ENTITY_TYPE_MAP = {
    "PERSON": PERSON,
    "LOC": LOCATION,
    "ORG": ORG,
    "DATETIME": DATE,
    "CODE": ID,
    "DEM": OTHER,
    "QUANTITY": OTHER,
    "MISC": OTHER,
}

#: NOT_CONFIDENTIAL dışındaki her değer TAB'da "özel nitelikli kişisel veri" anlamına gelir.
CONFIDENTIAL_VALUES = frozenset({"POLITICS", "ETHNIC", "BELIEF", "HEALTH", "SEX"})


def data_dir(root: Path | None = None) -> Path:
    return (root or DEFAULT_ROOT) / SOURCE


def is_fetched(root: Path | None = None) -> bool:
    """Korpus indirilmiş ve kullanılabilir mi. Erişilemiyorsa sessizce False — exception YOK."""
    return manifest_is_complete(data_dir(root))


def fetch(dest: Path, splits: tuple[str, ...] = DEFAULT_SPLITS) -> FetchResult:
    """TAB split dosyalarını `dest` altına indirir, sha256'larını kaydeder.

    ASLA raise etmez: ağ kapalıysa / repo taşınmışsa `ok=False` ve dolu `error` döner.
    Çağıran taraf bunu "fetched değil, atlanıyor" diye yorumlar.
    """
    dest = Path(dest)
    unknown = [s for s in splits if s not in SPLIT_FILES]
    if unknown:
        return FetchResult(
            source=SOURCE, ok=False, dest=str(dest), license=LICENSE, license_url=LICENSE_URL,
            fetched_at=utc_now(), error=f"bilinmeyen split(ler): {unknown}",
        )

    files: list[dict] = []
    errors: list[str] = []
    doc_count = 0
    for split in splits:
        name = SPLIT_FILES[split]
        target = dest / name
        ok, err = download(f"{BASE_URL}/{name}", target)
        if not ok:
            errors.append(f"{name}: {err}")
            continue
        files.append({"name": name, "sha256": sha256_file(target),
                      "bytes": target.stat().st_size, "split": split})
        doc_count += _count_docs(target)

    ok = bool(files) and not errors
    return FetchResult(
        source=SOURCE, ok=ok, dest=str(dest), files=files, license=LICENSE,
        license_url=LICENSE_URL, doc_count=doc_count, fetched_at=utc_now(),
        schema_verified=True,
        notes="Korpus kurulum adımı (tek seferlik ağ erişimi). Skorlar ana TR skoruyla "
              "birleştirilmez; ayrı raporlanır.",
        error="; ".join(errors),
    )


def _count_docs(path: Path) -> int:
    try:
        return len(json.loads(path.read_text(encoding="utf-8")))
    except Exception:
        return 0


def fetch_default(root: Path | None = None,
                  splits: tuple[str, ...] = DEFAULT_SPLITS) -> FetchResult:
    """Varsayılan dizine indirir ve manifest'i yazar (CLI/kurulum girişi)."""
    dest = data_dir(root)
    result = fetch(dest, splits=splits)
    write_manifest(dest, result)
    return result


def map_identifier_class(identifier_type: str, confidential_status: str = "") -> str:
    """TAB identifier_type + confidential_status → bizim identifier_class.

    Karar: NO_MASK her şeyi ezer. TAB'da NO_MASK "annotatör bunun maskelenMEmesi gerektiğine
    karar verdi" demektir; bu bizim over-masking negatif kontrolümüzün ta kendisi. Gizli
    öznitelik etiketi (BELIEF/HEALTH/...) yalnızca maskelenmesi gereken span'lerde
    SENSITIVE_ATTRIBUTE'a terfi eder.
    """
    itype = (identifier_type or "").upper()
    if itype == "NO_MASK":
        return NO_MASK
    if (confidential_status or "").upper() in CONFIDENTIAL_VALUES:
        return SENSITIVE_ATTRIBUTE
    if itype == "DIRECT":
        return DIRECT
    if itype == "QUASI":
        return QUASI
    return QUASI  # bilinmeyen etiket → temkinli taraf: maskelenmesi gereken sayılır


def map_necessity(identifier_class: str) -> str:
    """DIRECT ve SENSITIVE_ATTRIBUTE kaçırılırsa gerçek ihlal → mandatory.

    QUASI, TAB'ın kendi bulgusunda annotatörler arası uzlaşının düştüğü sınıf → contextual.
    NO_MASK için "gereklilik" kavramı tanımsız; enum bir değer istediği için contextual yazılır
    ve skorlamada zaten identifier_class ile ayrıştırılır.
    """
    if identifier_class in (DIRECT, SENSITIVE_ATTRIBUTE):
        return MANDATORY
    return CONTEXTUAL


def parse_document(raw: dict) -> ExternalDoc:
    """Ham TAB belge sözlüğünü ExternalDoc'a çevirir.

    Çoklu annotatör: TAB'ın kendi `evaluation.py`'si annotatörler arasında micro-average alır.
    Biz tek bir gold liste ürettiğimiz için span'lerin BİRLEŞİMİNİ alıyoruz ve her span'de kaç
    annatörün onu işaretlediğini `annotators` alanında taşıyoruz — çağıran taraf isterse
    "en az 2 annatör" gibi bir eşikle süzebilir. Birleşim, kaçırılan PII'yi cezalandıran
    (recall'a temkinli) taraftır.
    """
    text = raw.get("text") or ""
    annotations = raw.get("annotations") or {}

    # (start, end, entity_type, identifier_type, confidential_status) → annotatör sayısı
    agg: dict[tuple, dict] = {}
    for annotator, block in sorted(annotations.items()):
        for mention in (block or {}).get("entity_mentions") or []:
            try:
                start = int(mention["start_offset"])
                end = int(mention["end_offset"])
            except (KeyError, TypeError, ValueError):
                continue  # bozuk kayıt — belgenin tamamını düşürmeyiz
            if end <= start:
                continue
            native = str(mention.get("entity_type") or "")
            itype = str(mention.get("identifier_type") or "")
            conf = str(mention.get("confidential_status") or "")
            key = (start, end, native, itype, conf)
            entry = agg.get(key)
            if entry is None:
                agg[key] = {
                    "annotators": {annotator},
                    "surface": str(mention.get("span_text") or text[start:end]),
                    "entity_id": str(mention.get("entity_id") or ""),
                }
            else:
                entry["annotators"].add(annotator)

    spans: list[ExternalSpan] = []
    for (start, end, native, itype, conf), entry in sorted(agg.items()):
        identifier_class = map_identifier_class(itype, conf)
        spans.append(ExternalSpan(
            start=start, end=end,
            entity_type=ENTITY_TYPE_MAP.get(native, OTHER),
            identifier_class=identifier_class,
            necessity=map_necessity(identifier_class),
            surface=entry["surface"],
            entity_id=entry["entity_id"],
            annotators=len(entry["annotators"]),
            native_type=native,
        ))

    return ExternalDoc(
        doc_id=str(raw.get("doc_id") or ""),
        text=text,
        spans=spans,
        source=SOURCE,
        meta={
            "dataset_type": raw.get("dataset_type"),
            "quality_checked": raw.get("quality_checked"),
            "task": raw.get("task"),
            "annotator_count": len(annotations),
            "language": "en",
            "domain": "legal_echr",
        },
    )


def load(limit: int | None = None, root: Path | None = None,
         splits: tuple[str, ...] = DEFAULT_SPLITS) -> list[ExternalDoc]:
    """İndirilmiş TAB belgelerini yükler. Fetch edilmemişse BOŞ LİSTE döner (exception yok)."""
    dest = data_dir(root)
    if limit is not None and limit <= 0:
        return []
    if not manifest_is_complete(dest):
        return []

    docs: list[ExternalDoc] = []
    for split in splits:
        name = SPLIT_FILES.get(split)
        path = dest / name if name else None
        if path is None or not path.is_file():
            continue
        try:
            raw_docs = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue  # bozuk dosya → o split atlanır, benchmark çökmez
        for raw in raw_docs:
            docs.append(parse_document(raw))
            if limit is not None and len(docs) >= limit:
                return docs
    return docs


def to_gold_spans(doc: ExternalDoc) -> list[dict]:
    """ExternalDoc'u bizim skorlayıcımızın beklediği gold span sözlüklerine çevirir.

    Offset'ler `doc.text` üzerinde yarı-açık [start, end). `source` alanı sonuçların ana TR
    skoruyla yanlışlıkla birleştirilmesini engellemek için her kayıtta taşınır.
    """
    return [
        {
            "doc_id": doc.doc_id,
            "start": span.start,
            "end": span.end,
            "entity_type": span.entity_type,
            "identifier_class": span.identifier_class,
            "necessity": span.necessity,
            "surface": span.surface,
            "entity_id": span.entity_id,
            "annotators": span.annotators,
            "native_type": span.native_type,
            "source": SOURCE,
        }
        for span in doc.spans
    ]

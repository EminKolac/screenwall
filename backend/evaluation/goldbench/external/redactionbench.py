"""RedactionBench adaptörü — dış geçerlilik kontrolü.

KAYNAK: https://huggingface.co/datasets/RedactionBench/RedactionBench  (paper: arXiv:2606.18782)
200 İngilizce belge, 11 kategori (academic/code/emails/files/financial/government/legal/logs/
medical/operations/terminal), karakter seviyeli span anotasyonu, mandatory/contextual ayrımı.
Lisans: CC BY 4.0 → türetilmiş raporlarda ATIF ZORUNLU.

ŞEMA DOĞRULAMA DURUMU: DOĞRULANDI (HF datasets-server `first-rows` çıktısı üstünde).
Gerçek özellik listesi:

  raw_text              : string   — belgenin metni (marker'lar çıkarılmış)
  spans                 : list[{start:int, end:int, label:str}]  — yarı-açık [start, end)
  category              : string
  genre                 : string
  is_synthetic          : bool
  original_document_url : string|null

  label ∈ {"mandatory", "contextual"}   — BAŞKA ETİKET YOK

DOĞRULANAMAYAN / EKSİK OLAN — DİKKAT:
1. RedactionBench span'lerinde VARLIK TÜRÜ (entity type) YOKTUR. Yalnızca mandatory/contextual
   var. Bu yüzden `entity_type` her span'de OTHER'dır ve bu benchmark üstünde PERSON/IBAN/…
   kırılımlı recall RAPORLANAMAZ. Sadece toplam tespit kalitesi ölçülebilir.
2. Resmî metrik R-Score'un referans implementasyonu yayımlanmamıştır (dataset README: "A
   reference implementation will be released shortly"). Bu modül R-Score HESAPLAMAZ; yalnızca
   gold span'leri bizim şemamıza taşır. R-Score iddiası, referans kod çıkana dek YAPILMAMALIDIR.
3. Belge kimliği (doc_id) alanı dataset'te YOKTUR — satır indeksinden türetilir ("rb-0001").

AĞ ERİŞİMİ: `fetch()` tek seferlik KORPUS KURULUM adımıdır. Runtime local-first garantisi
değişmez — bu modül `app/` içinden asla import edilmez.

SONUÇ BİRLEŞTİRME: RedactionBench skorları ana Türkçe GoldBench skoruyla BİRLEŞTİRİLMEZ.
İngilizce, ağırlıklı sentetik korpus — ayrı tabloda "dış geçerlilik" başlığı altında raporlanır.
"""
from __future__ import annotations

import json
from pathlib import Path

from . import (
    CONTEXTUAL,
    DEFAULT_ROOT,
    DIRECT,
    MANDATORY,
    OTHER,
    QUASI,
    ExternalDoc,
    ExternalSpan,
    FetchResult,
    manifest_is_complete,
    sha256_file,
    utc_now,
    write_manifest,
)

SOURCE = "redactionbench"
LICENSE = "CC-BY-4.0"
LICENSE_URL = "https://creativecommons.org/licenses/by/4.0/"
DATASET = "RedactionBench/RedactionBench"
CONFIG = "default"
SPLIT = "test"

#: HF datasets-server satır API'si. Parquet yerine bunu kullanıyoruz çünkü projede pyarrow
#: bağımlılığı YOK — JSON satırları ek bağımlılık gerektirmeden okunabiliyor.
ROWS_URL = "https://datasets-server.huggingface.co/rows"
PARQUET_URL = (
    f"https://huggingface.co/api/datasets/{DATASET}/parquet/{CONFIG}/{SPLIT}/0.parquet"
)
LOCAL_NAME = "redactionbench_test.jsonl"
PAGE_SIZE = 100

#: RedactionBench label → bizim identifier_class.
#: mandatory: "her makul gizlilik çerçevesinde maskelenmeli" → tek başına belirleyici sayıyoruz.
#: contextual: "maskeleme downstream politikaya bağlı" (kurum adı, unvan, kısmi kimlik, ağ
#: metadata'sı) → bizim QUASI tanımıyla örtüşür.
LABEL_TO_IDENTIFIER_CLASS = {"mandatory": DIRECT, "contextual": QUASI}
LABEL_TO_NECESSITY = {"mandatory": MANDATORY, "contextual": CONTEXTUAL}


def data_dir(root: Path | None = None) -> Path:
    return (root or DEFAULT_ROOT) / SOURCE


def is_fetched(root: Path | None = None) -> bool:
    """Korpus indirilmiş ve kullanılabilir mi. Erişilemiyorsa sessizce False — exception YOK."""
    return manifest_is_complete(data_dir(root))


def fetch(dest: Path, max_rows: int | None = None, timeout: float = 60.0) -> FetchResult:
    """RedactionBench test split'ini JSONL olarak `dest` altına indirir, sha256'sını kaydeder.

    ASLA raise etmez: HF erişilemezse / dataset gated hâle gelirse `ok=False` ve dolu `error`
    döner; çağıran taraf "fetched değil, atlanıyor" der.
    """
    dest = Path(dest)
    try:
        import httpx
    except ImportError as exc:  # pragma: no cover
        return _fail(dest, f"httpx import edilemedi: {exc}")

    target = dest / LOCAL_NAME
    tmp = target.with_suffix(".part")
    rows_written = 0
    try:
        dest.mkdir(parents=True, exist_ok=True)
        with httpx.Client(timeout=timeout, follow_redirects=True) as client, \
                tmp.open("w", encoding="utf-8") as fh:
            offset = 0
            while True:
                length = PAGE_SIZE
                if max_rows is not None:
                    length = min(length, max_rows - rows_written)
                    if length <= 0:
                        break
                resp = client.get(ROWS_URL, params={
                    "dataset": DATASET, "config": CONFIG, "split": SPLIT,
                    "offset": offset, "length": length,
                })
                resp.raise_for_status()
                payload = resp.json()
                rows = payload.get("rows") or []
                if not rows:
                    break
                for item in rows:
                    fh.write(json.dumps(item.get("row") or {}, ensure_ascii=False) + "\n")
                    rows_written += 1
                offset += len(rows)
                total = payload.get("num_rows_total")
                if isinstance(total, int) and offset >= total:
                    break
        if rows_written == 0:
            tmp.unlink(missing_ok=True)
            return _fail(dest, "dataset boş döndü (erişim kısıtlanmış olabilir)")
        tmp.replace(target)
    except Exception as exc:
        tmp.unlink(missing_ok=True)
        return _fail(dest, f"{type(exc).__name__}: {exc}")

    return FetchResult(
        source=SOURCE, ok=True, dest=str(dest),
        files=[{"name": LOCAL_NAME, "sha256": sha256_file(target),
                "bytes": target.stat().st_size, "rows": rows_written}],
        license=LICENSE, license_url=LICENSE_URL, doc_count=rows_written,
        fetched_at=utc_now(), schema_verified=True,
        notes="Korpus kurulum adımı (tek seferlik ağ erişimi). CC BY 4.0 — raporda atıf "
              "zorunlu. entity_type YOK (hepsi OTHER); R-Score referans implementasyonu "
              "yayımlanmadığı için burada HESAPLANMAZ. Skorlar ana TR skoruyla birleştirilmez. "
              f"Kanonik parquet: {PARQUET_URL}",
    )


def _fail(dest: Path, message: str) -> FetchResult:
    return FetchResult(
        source=SOURCE, ok=False, dest=str(dest), license=LICENSE, license_url=LICENSE_URL,
        fetched_at=utc_now(), error=message,
    )


def fetch_default(root: Path | None = None, max_rows: int | None = None) -> FetchResult:
    """Varsayılan dizine indirir ve manifest'i yazar (CLI/kurulum girişi)."""
    dest = data_dir(root)
    result = fetch(dest, max_rows=max_rows)
    write_manifest(dest, result)
    return result


def parse_document(raw: dict, index: int = 0) -> ExternalDoc:
    """Ham RedactionBench satırını ExternalDoc'a çevirir.

    doc_id dataset'te YOK → satır indeksinden türetilir. entity_type dataset'te YOK → OTHER.
    """
    text = raw.get("raw_text") or ""
    spans: list[ExternalSpan] = []
    seen: set[tuple[int, int, str]] = set()
    for item in raw.get("spans") or []:
        try:
            start = int(item["start"])
            end = int(item["end"])
        except (KeyError, TypeError, ValueError):
            continue  # bozuk span — belgeyi düşürmeyiz
        if end <= start:
            continue
        label = str(item.get("label") or "").lower()
        key = (start, end, label)
        if key in seen:
            continue
        seen.add(key)
        # Bilinmeyen etiket → temkinli taraf: maskelenmesi gereken (DIRECT/mandatory) sayılır.
        spans.append(ExternalSpan(
            start=start, end=end,
            entity_type=OTHER,  # dataset varlık türü vermiyor — aile kırılımı YAPILAMAZ
            identifier_class=LABEL_TO_IDENTIFIER_CLASS.get(label, DIRECT),
            necessity=LABEL_TO_NECESSITY.get(label, MANDATORY),
            surface=text[start:end],
            annotators=1,
            native_type=label,
        ))
    spans.sort(key=lambda s: (s.start, s.end, s.native_type))

    doc_id = str(raw.get("doc_id") or f"rb-{index:04d}")
    return ExternalDoc(
        doc_id=doc_id, text=text, spans=spans, source=SOURCE,
        meta={
            "category": raw.get("category"),
            "genre": raw.get("genre"),
            "is_synthetic": raw.get("is_synthetic"),
            "original_document_url": raw.get("original_document_url"),
            "language": "en",
        },
    )


def load(limit: int | None = None, root: Path | None = None) -> list[ExternalDoc]:
    """İndirilmiş RedactionBench belgelerini yükler. Fetch edilmemişse BOŞ LİSTE döner."""
    dest = data_dir(root)
    if limit is not None and limit <= 0:
        return []
    if not manifest_is_complete(dest):
        return []
    path = dest / LOCAL_NAME
    if not path.is_file():
        return []

    docs: list[ExternalDoc] = []
    try:
        with path.open(encoding="utf-8") as fh:
            for index, line in enumerate(fh):
                line = line.strip()
                if not line:
                    continue
                try:
                    raw = json.loads(line)
                except json.JSONDecodeError:
                    continue  # bozuk satır atlanır, benchmark çökmez
                docs.append(parse_document(raw, index=index))
                if limit is not None and len(docs) >= limit:
                    break
    except OSError:
        return docs
    return docs


def to_gold_spans(doc: ExternalDoc) -> list[dict]:
    """ExternalDoc'u bizim skorlayıcımızın beklediği gold span sözlüklerine çevirir.

    `entity_type` her zaman OTHER — bu benchmark'ta varlık ailesi kırılımı YAPILAMAZ.
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

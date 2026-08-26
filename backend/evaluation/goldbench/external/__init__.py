"""GoldBench dış geçerlilik (external validity) katmanı — ortak sözleşme.

NEDEN VAR:
GoldBench bugün tamamen kendi tanımladığımız bir ölçek. Kendi korpusumuzda kendi şemamıza göre
skor üretiyoruz; bu skor dışarıdan kalibre edilemiyor. TAB ve RedactionBench yayımlanmış,
hakemli benchmark'lar. Onların üstünde skor üretmek "kendi sınavımızdan geçtik" ile "herkesin
sınavında şu skoru aldık" arasındaki farkı verir.

AĞ ERİŞİMİ — KORPUS KURULUM ADIMIDIR, RUNTIME DEĞİL:
`fetch()` tek seferlik bir korpus kurulum adımıdır (tıpkı bir test fixture'ını indirmek gibi).
Ürünün runtime'ı local-first kalır; anonimleştirme pipeline'ı hiçbir zaman ağa çıkmaz. Bu
modüller yalnızca `evaluation/` altında, benchmark koşarken çağrılır — `app/` içinden ASLA
import edilmez.

SONUÇLAR BİRLEŞTİRİLMEZ:
TAB (İngilizce AİHM kararları) ve RedactionBench (İngilizce, çoğu sentetik doküman) bizim ana
Türkçe skorumuzla AYNI TABLOYA KONMAZ. Farklı dil, farklı domain, farklı annotation felsefesi.
Ayrı raporlanır; "dış geçerlilik kontrolü" olarak okunur, ana skorun parçası olarak değil.

ZARİF BOZULMA:
Dataset indirilmemişse veya erişilemiyorsa `is_fetched()` False döner, `load()` boş liste döner.
Bu modüller benchmark'ın geri kalanını ASLA exception ile çökertmez — çağıran taraf
"fetched değil, atlanıyor" deyip devam eder.
"""
from __future__ import annotations

import hashlib
import os
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

# Bizim iç şemamızdaki kanonik varlık aileleri (schema.py ile uyumlu; oradaki entity_type
# serbest string olduğu için burada dış benchmark'ları eşleyeceğimiz daraltılmış küme tutuluyor).
PERSON = "PERSON"
LOCATION = "LOCATION"
ORG = "ORG"
DATE = "DATE"
EMAIL = "EMAIL"
PHONE = "PHONE"
ID = "ID"
OTHER = "OTHER"

CANONICAL_ENTITY_TYPES = (PERSON, LOCATION, ORG, DATE, EMAIL, PHONE, ID, OTHER)

# schema.IdentifierClass ile birebir aynı değerler — dış adaptörler schema'ya bağımlı olmasın
# diye string olarak tutuluyor (bu paket schema.py'yi import etmez, tek yönlü bağımlılık).
DIRECT = "DIRECT"
QUASI = "QUASI"
SENSITIVE_ATTRIBUTE = "SENSITIVE_ATTRIBUTE"
NO_MASK = "NO_MASK"

MANDATORY = "mandatory"
CONTEXTUAL = "contextual"

#: Dış korpusların indirileceği kök dizin. `data/` gitignore'lu — byte'lar repoya girmez.
DEFAULT_ROOT = Path(os.environ.get("GOLDBENCH_EXTERNAL_DIR", "data/goldbench_external"))

#: Her adaptörün dizininde tutulan indirme kaydı.
MANIFEST_NAME = "fetch_manifest.json"

#: Kayıtlı adaptörler. `get_adapter()` ile lazy import edilir (dairesel import olmasın diye).
ADAPTERS = ("tab", "redactionbench")


@dataclass(frozen=True)
class ExternalSpan:
    """Dış benchmark'ın bir anotasyonunun BİZİM şemamıza eşlenmiş hâli.

    Offset'ler `ExternalDoc.text` üzerinde yarı-açık aralıktır: [start, end).
    Burada `locate()`/occurrence oyunu YOK — dış korpuslarda taşıyıcı round-trip'i olmadığı için
    karakter offset'leri güvenilir (bkz. schema.py'deki surface+occurrence gerekçesi).
    """

    start: int
    end: int
    entity_type: str          # CANONICAL_ENTITY_TYPES'tan biri
    identifier_class: str     # DIRECT | QUASI | SENSITIVE_ATTRIBUTE | NO_MASK
    necessity: str            # mandatory | contextual
    surface: str = ""         # ham metin dilimi — rapora girmez, yalnızca hata ayıklama için
    entity_id: str = ""       # coreference bağı (TAB verir, RedactionBench vermez)
    annotators: int = 1       # kaç annotatör bu span'i işaretledi (TAB çoklu annotatör)
    native_type: str = ""     # kaynak benchmark'ın orijinal etiketi — eşleme denetimi için

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class ExternalDoc:
    """Dış benchmark'tan gelen tek bir belge."""

    doc_id: str
    text: str
    spans: list[ExternalSpan] = field(default_factory=list)
    source: str = ""          # "tab" | "redactionbench"
    meta: dict = field(default_factory=dict)


@dataclass(frozen=True)
class FetchResult:
    """Bir indirme denemesinin sonucu. Başarısızlık exception DEĞİL, ok=False ile bildirilir."""

    source: str
    ok: bool
    dest: str
    files: list[dict] = field(default_factory=list)   # {name, sha256, bytes}
    license: str = "unknown"                          # bilinmiyorsa "unknown"
    license_url: str = ""
    doc_count: int = 0
    fetched_at: str = ""
    schema_verified: bool = False   # şema canlı veriye karşı doğrulandı mı
    notes: str = ""
    error: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def sha256_file(path: Path) -> str:
    """Dosyanın sha256'sı — korpusun tekrar üretilebilirlik kaydı."""
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def download(url: str, target: Path, timeout: float = 120.0) -> tuple[bool, str]:
    """`url`i `target`a indirir. (ok, hata_mesajı) döner — ASLA raise etmez.

    Ağ erişimi burada, yalnızca korpus kurulumunda olur. httpx projede zaten mevcut.
    """
    try:
        import httpx
    except ImportError as exc:  # pragma: no cover - httpx projede zorunlu bağımlılık
        return False, f"httpx import edilemedi: {exc}"

    tmp = target.with_suffix(target.suffix + ".part")
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with httpx.stream("GET", url, follow_redirects=True, timeout=timeout) as resp:
            resp.raise_for_status()
            with tmp.open("wb") as fh:
                for chunk in resp.iter_bytes(1 << 16):
                    fh.write(chunk)
        tmp.replace(target)
        return True, ""
    except Exception as exc:  # ağ/HTTP/disk — hepsi zarifçe raporlanır
        tmp.unlink(missing_ok=True)
        return False, f"{type(exc).__name__}: {exc}"


def write_manifest(dest: Path, result: FetchResult) -> None:
    """İndirme kaydını yazar. `is_fetched()` bu dosyaya bakar."""
    import json

    dest.mkdir(parents=True, exist_ok=True)
    (dest / MANIFEST_NAME).write_text(
        json.dumps(result.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
    )


def read_manifest(dest: Path) -> dict | None:
    """Manifest'i okur; yoksa veya bozuksa None döner (hata fırlatmaz)."""
    import json

    path = dest / MANIFEST_NAME
    try:
        if not path.is_file():
            return None
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def manifest_is_complete(dest: Path) -> bool:
    """Manifest ok=True mi ve listelediği dosyalar diskte duruyor mu."""
    data = read_manifest(dest)
    if not data or not data.get("ok"):
        return False
    files = data.get("files") or []
    if not files:
        return False
    return all((dest / f.get("name", "")).is_file() for f in files)


def get_adapter(name: str):
    """Adaptör modülünü lazy import eder (paket __init__'i alt modülleri import etmez)."""
    if name not in ADAPTERS:
        raise ValueError(f"bilinmeyen adaptör: {name!r} (geçerli: {ADAPTERS})")
    from importlib import import_module

    return import_module(f"{__name__}.{name}")


__all__ = [
    "ADAPTERS", "CANONICAL_ENTITY_TYPES", "CONTEXTUAL", "DATE", "DEFAULT_ROOT", "DIRECT",
    "EMAIL", "ExternalDoc", "ExternalSpan", "FetchResult", "ID", "LOCATION", "MANDATORY",
    "MANIFEST_NAME", "NO_MASK", "ORG", "OTHER", "PERSON", "PHONE", "QUASI",
    "SENSITIVE_ATTRIBUTE", "download", "get_adapter", "manifest_is_complete", "read_manifest",
    "sha256_file", "utc_now", "write_manifest",
]

"""GoldBench gold-annotation şeması — tüm paketin ortak sözleşmesi.

Neden surface + occurrence_index (offset DEĞİL):
Bir belge üretildikten sonra pdf/docx/xlsx taşıyıcılarına yazılır ve pipeline onu TEKRAR çıkarır.
Bu round-trip'te boşluk, satır sonu ve tablo hücresi birleştirme nedeniyle karakter offset'leri
kayar — üretim anındaki offset, çıkarım sonrası metinde geçerli olmaz. Bu yüzden gold kayıt
"hangi string, belgede kaçıncı geçişi" olarak saklanır; skorlama anında bu surface çıkarılmış
metinde YENİDEN konumlandırılır (`locate()`), böylece offset'ler her zaman pipeline'ın gerçekten
gördüğü koordinat uzayında olur.

Skorlama iki farklı şeyi ayrı ayrı ölçer (bkz. `score.py`):
  1. Tespit kalitesi — gold span'ler vs. dedektör span'leri, AYNI koordinat uzayında (çıkarılmış
     orijinal metin). TAB/RedactionBench de böyle yapar. Karakter seviyeli metrikler burada.
  2. Gerçek maskeleme — değer anonim çıktıda/export'ta hâlâ var mı. Sızıntı kontrolü burada.

Bir değeri tespit etmek ama maskelememek mümkündür (eşik/çakışma), bu yüzden ikisi ayrı ölçülür.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import asdict, dataclass, field
from enum import Enum

_WS = re.compile(r"\s+")


def norm(s: str) -> str:
    """Boşlukları sadeleştirir + NFKC. Satır sonuna bölünmüş PII'yi eşleştirmek için gerekli."""
    return _WS.sub(" ", unicodedata.normalize("NFKC", s or "")).strip()


def value_hash(value: str) -> str:
    """Rapor-güvenli, geri döndürülemez kimlik. Ham PII ASLA rapora/log'a yazılmaz."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


class IdentifierClass(str, Enum):
    """KVKK m.3/1-(b) "başka verilerle eşleştirilerek dahi" ibaresi tam olarak QUASI'yi kastediyor;
    bu ayrım olmadan o maddeye dayanan bir iddia ölçülemez."""

    DIRECT = "DIRECT"                          # tek başına kimliği belirler (TCKN, e-posta, IBAN)
    QUASI = "QUASI"                            # tek başına değil, birleşince belirler (meslek)
    SENSITIVE_ATTRIBUTE = "SENSITIVE_ATTRIBUTE"  # özel nitelikli (sağlık, sendika, ceza geçmişi)
    NO_MASK = "NO_MASK"                        # maskelenMEmeli — over-masking negatif kontrolü


class Necessity(str, Enum):
    MANDATORY = "mandatory"    # kaçırılırsa gerçek ihlal
    CONTEXTUAL = "contextual"  # bağlama göre; annotatörler arası uzlaşı düşük (RedactionBench)


class Criticality(str, Enum):
    CRITICAL = "critical"  # release gate'e giren sınıf
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class Channel(str, Enum):
    """Değerin belgede yaşadığı yüzey. Yüzey bazlı recall kırılımı için — bir yüzeyin tamamen
    kör olması (örn. header) tek bir toplam recall sayısında görünmez."""

    BODY = "body"
    TABLE = "table"
    HEADING = "heading"
    HEADER = "header"
    FOOTER = "footer"
    COMMENT = "comment"
    METADATA = "metadata"
    FILENAME = "filename"
    SHEET_NAME = "sheet_name"


@dataclass(frozen=True)
class GoldMention:
    """Bir değerin belgedeki TEK bir geçişi.

    `entity_id` aynı gerçek varlığın tüm geçişlerini bağlar ("Ahmet Yılmaz" / "Ahmet Bey" /
    "A. Yılmaz" → aynı entity_id). Entity-level recall bunun üstünde hesaplanır: bir mention bile
    açık kalırsa entity korunmamış sayılır (TAB'ın önerdiği katı ölçüt).
    `subject_id` ise entity'nin ait olduğu veri sahibi (kişi) — attribute inference ve TRIR için.
    """

    mention_id: str
    entity_id: str
    subject_id: str
    surface: str                 # ham değer — SADECE bellekte/gold dosyasında, rapora asla girmez
    occurrence: int              # bu surface'in belge metnindeki kaçıncı geçişi (0-tabanlı)
    entity_type: str             # PERSON / TCKN / IBAN / EMAIL / PHONE / ADDRESS / OCCUPATION ...
    identifier_class: IdentifierClass
    necessity: Necessity
    criticality: Criticality
    channel: Channel
    src_start: int = -1          # üretim anındaki offset (referans; skorlamada KULLANILMAZ)
    src_end: int = -1

    @property
    def vhash(self) -> str:
        return value_hash(self.surface)

    def safe_dict(self) -> dict:
        """Rapor-güvenli görünüm — ham surface YOK."""
        d = asdict(self)
        d.pop("surface", None)
        d["vhash"] = self.vhash
        d["identifier_class"] = self.identifier_class.value
        d["necessity"] = self.necessity.value
        d["criticality"] = self.criticality.value
        d["channel"] = self.channel.value
        return d

    def to_gold_dict(self) -> dict:
        """Gold dosyasına yazılan tam kayıt (surface DAHİL — bu dosya cevap anahtarıdır)."""
        d = asdict(self)
        d["identifier_class"] = self.identifier_class.value
        d["necessity"] = self.necessity.value
        d["criticality"] = self.criticality.value
        d["channel"] = self.channel.value
        return d

    @staticmethod
    def from_gold_dict(d: dict) -> GoldMention:
        return GoldMention(
            mention_id=d["mention_id"], entity_id=d["entity_id"], subject_id=d["subject_id"],
            surface=d["surface"], occurrence=int(d.get("occurrence", 0)),
            entity_type=d["entity_type"],
            identifier_class=IdentifierClass(d["identifier_class"]),
            necessity=Necessity(d["necessity"]), criticality=Criticality(d["criticality"]),
            channel=Channel(d["channel"]),
            src_start=int(d.get("src_start", -1)), src_end=int(d.get("src_end", -1)),
        )


@dataclass
class GoldDocument:
    """Bir gold belgenin tam kaydı. `formats` aynı içeriğin taşıyıcı dosyalarıdır — içerik
    birebir aynı olduğu için formatlar arası fark YALNIZCA format işlemeden gelir."""

    doc_id: str
    domain: str                  # finance / legal / health / hr / public / correspondence
    language: str                # tr / en / mixed
    split: str                   # dev / public / holdout
    text: str                    # üretilen düz metin (taşıyıcılara yazılan içerik)
    mentions: list[GoldMention] = field(default_factory=list)
    subjects: list[str] = field(default_factory=list)
    formats: dict[str, str] = field(default_factory=dict)  # fmt -> dosya adı

    def meta_dict(self) -> dict:
        """Manifest kaydı — metin ve ham değerler HARİÇ."""
        return {
            "doc_id": self.doc_id, "domain": self.domain, "language": self.language,
            "split": self.split, "subjects": list(self.subjects),
            "mention_count": len(self.mentions),
            "entity_count": len({m.entity_id for m in self.mentions}),
            "formats": dict(self.formats),
        }


def locate(text: str, surface: str, occurrence: int = 0) -> tuple[int, int] | None:
    """`surface`in `text` içindeki `occurrence`. geçişini bul → (start, end) veya None.

    Önce birebir arar; bulamazsa boşluk-esnek arama yapar (taşıyıcı round-trip'i bir değeri satır
    sonuna bölmüş olabilir: "0532 764\n21 09"). Esnek arama, surface'in boşluklarını `\\s+` ile
    değiştirip regex olarak arar — bu yüzden diğer tüm karakterler `re.escape` edilir.
    """
    if not text or not surface:
        return None
    idx, start = -1, 0
    for _ in range(occurrence + 1):
        idx = text.find(surface, start)
        if idx < 0:
            break
        start = idx + 1
    if idx >= 0:
        return idx, idx + len(surface)

    parts = [re.escape(p) for p in surface.split() if p]
    if not parts:
        return None
    pattern = re.compile(r"\s+".join(parts))
    matches = list(pattern.finditer(text))
    if occurrence < len(matches):
        m = matches[occurrence]
        return m.start(), m.end()
    return None

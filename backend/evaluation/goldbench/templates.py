"""Gold belge şablonları — 6 alan, her biri gerçek Türk kurumsal belge yapısını taklit eder.

Şablonlar `DocBuilder` üzerinden yazılır: metin eklerken PII değerleri `pii()` ile kaydedilir,
böylece cevap anahtarı belge ile BİRLİKTE üretilir — sonradan etiketleme yok, kaçırma riski yok.

Tasarım kuralları (her şablon uyar):
  - En az 2 veri sahibi, ≥3 PII türü, ≥1 tekrarlanan entity, ≥1 coreference varyantı, ≥1 quasi.
  - `NO_MASK` kontrolleri: maskelenMEmesi gereken sıradan iş terimleri. Over-masking (precision
    kaybı) ancak bunlar sayesinde ölçülebilir — yoksa "her şeyi maskele" mükemmel skor alır.
  - Downstream soru setinin cevabı ASLA PII olmamalı (bkz. inference_set): iyi bir karartıcı zaten
    PII'yi yok eder, onu fayda kaybı saymak yanlış ölçüm olur.
"""
from __future__ import annotations

import random

from app.extraction.base import Block, BlockType, ExtractedContent, TableCell
from app.models.document import FileKind
from evaluation.goldbench.identity import Person
from evaluation.goldbench.schema import (
    Channel,
    Criticality,
    GoldMention,
    IdentifierClass,
    Necessity,
)

# Maskelenmemesi gereken sıradan iş dili — over-masking ölçümünün negatif kontrolü.
NO_MASK_TERMS = [
    "Genel Kurul", "Yönetim Kurulu", "Faaliyet Raporu", "Gider Pusulası",
    "Sözleşme Bedeli", "Teslim Tarihi", "Ödeme Planı", "Fatura Dönemi",
    "Risk Değerlendirmesi", "İş Sağlığı ve Güvenliği", "Kalite Kontrol",
]

_DIRECT_SPECS: dict[str, tuple[str, Criticality]] = {
    "full_name": ("PERSON", Criticality.CRITICAL),
    "tckn": ("TCKN", Criticality.CRITICAL),
    "phone": ("PHONE", Criticality.CRITICAL),
    "email": ("EMAIL", Criticality.CRITICAL),
    "iban": ("IBAN", Criticality.CRITICAL),
    "card": ("CARD", Criticality.CRITICAL),
    "address": ("ADDRESS", Criticality.CRITICAL),
}
_QUASI_SPECS: dict[str, tuple[str, Criticality]] = {
    "occupation": ("OCCUPATION", Criticality.MEDIUM),
    "employer": ("EMPLOYER", Criticality.MEDIUM),
    "district": ("LOCATION", Criticality.MEDIUM),
    "education": ("EDUCATION", Criticality.LOW),
    "salary_band": ("SALARY", Criticality.MEDIUM),
}
_SENSITIVE_SPECS: dict[str, tuple[str, Criticality]] = {
    "health": ("HEALTH", Criticality.CRITICAL),
    "disability": ("DISABILITY", Criticality.CRITICAL),
    "union": ("UNION", Criticality.HIGH),
    "legal": ("LEGAL", Criticality.HIGH),
}


class DocBuilder:
    """Belge + cevap anahtarını birlikte kurar.

    `occurrence` ataması: aynı surface'in kaçıncı kez KAYIT EDİLDİĞİ sayılır. Skorlama anında
    `locate(text, surface, occurrence)` metindeki n. geçişi bulur. Bu, ancak bir değerin belgedeki
    HER geçişi kaydedilirse doğru olur — bu yüzden şablonlar kişi verisini asla düz metin olarak
    yazmaz, hep `pii()` üzerinden geçirir.
    """

    def __init__(self, doc_id: str) -> None:
        self.doc_id = doc_id
        self.blocks: list[Block] = []
        self.mentions: list[GoldMention] = []
        self._seen: dict[str, int] = {}
        self._buf: list[str] = []
        self._channel = Channel.BODY
        self._n = 0

    # --- metin biriktirme ---
    def t(self, s: str) -> DocBuilder:
        self._buf.append(s)
        return self

    def pii(self, person: Person, attr: str, surface: str | None = None,
            channel: Channel | None = None) -> DocBuilder:
        """Kişinin bir özelliğini metne yazar ve cevap anahtarına kaydeder."""
        value = surface if surface is not None else getattr(person, attr)
        if attr in _DIRECT_SPECS:
            etype, crit = _DIRECT_SPECS[attr]
            klass, need = IdentifierClass.DIRECT, Necessity.MANDATORY
        elif attr in _QUASI_SPECS:
            etype, crit = _QUASI_SPECS[attr]
            klass, need = IdentifierClass.QUASI, Necessity.CONTEXTUAL
        elif attr in _SENSITIVE_SPECS:
            etype, crit = _SENSITIVE_SPECS[attr]
            klass, need = IdentifierClass.SENSITIVE_ATTRIBUTE, Necessity.MANDATORY
        else:  # alias — kişi adının başka bir yüzeyi
            etype, crit = "PERSON", Criticality.CRITICAL
            klass, need = IdentifierClass.DIRECT, Necessity.MANDATORY

        occ = self._seen.get(value, 0)
        self._seen[value] = occ + 1
        self._n += 1
        # entity_id: aynı kişinin aynı özelliği → aynı entity. Ad ve alias'lar TEK entity'de
        # toplanır ("Ahmet Yılmaz" ile "Ahmet Bey" aynı varlık) — entity-level recall bunu ister.
        ent_attr = "full_name" if attr in ("full_name", "alias") else attr
        self.mentions.append(GoldMention(
            mention_id=f"{self.doc_id}-m{self._n:03d}",
            entity_id=f"{person.subject_id}:{ent_attr}",
            subject_id=person.subject_id,
            surface=value, occurrence=occ, entity_type=etype,
            identifier_class=klass, necessity=need, criticality=crit,
            channel=channel or self._channel,
        ))
        self._buf.append(value)
        return self

    def no_mask(self, term: str) -> DocBuilder:
        """Maskelenmemesi gereken terim — over-masking'in negatif kontrolü."""
        occ = self._seen.get(term, 0)
        self._seen[term] = occ + 1
        self._n += 1
        self.mentions.append(GoldMention(
            mention_id=f"{self.doc_id}-n{self._n:03d}", entity_id=f"NOMASK:{term}",
            subject_id="-", surface=term, occurrence=occ, entity_type="NO_MASK",
            identifier_class=IdentifierClass.NO_MASK, necessity=Necessity.CONTEXTUAL,
            criticality=Criticality.LOW, channel=self._channel,
        ))
        self._buf.append(term)
        return self

    # --- blok kapatma ---
    def _flush(self, btype: BlockType) -> None:
        text = "".join(self._buf).strip()
        self._buf.clear()
        if text:
            self.blocks.append(Block(block_id=str(len(self.blocks)), type=btype, text=text))

    def heading(self) -> DocBuilder:
        self._channel = Channel.HEADING
        self._flush(BlockType.heading)
        self._channel = Channel.BODY
        return self

    def para(self) -> DocBuilder:
        self._flush(BlockType.paragraph)
        return self

    def table(self, rows: list[list[str]]) -> DocBuilder:
        """Hazır satırlarla tablo bloğu. PII içeren hücreler ÖNCE `pii()` ile kaydedilmiş
        olmalıdır — `table_pii` yardımcısı bunu yapar."""
        cells = [TableCell(row=r, col=c, text=v)
                 for r, row in enumerate(rows) for c, v in enumerate(row)]
        self.blocks.append(Block(block_id=str(len(self.blocks)), type=BlockType.table, cells=cells))
        return self

    def table_pii(self, rows: list[list[tuple[Person, str] | str]]) -> DocBuilder:
        """Tablo satırları: her hücre ya düz metin ya (person, attr) çifti. PII hücreleri
        kaydedilir, sonra tablo bloğu kurulur.

        Bekleyen paragraf metni ÖNCE flush edilir — aksi halde tablodan önce yazılmış metin
        sessizce kaybolurdu (ve onun içindeki kayıtlı mention'lar metinde bulunamaz hale gelirdi).
        """
        self._flush(BlockType.paragraph)
        self._channel = Channel.TABLE
        out: list[list[str]] = []
        for row in rows:
            vals: list[str] = []
            for cell in row:
                if isinstance(cell, tuple):
                    person, attr = cell
                    self.pii(person, attr, channel=Channel.TABLE)
                    vals.append("".join(self._buf))
                    self._buf.clear()
                else:
                    vals.append(cell)
            out.append(vals)
        self._channel = Channel.BODY
        return self.table(out)

    def build(self) -> tuple[ExtractedContent, list[GoldMention]]:
        self._flush(BlockType.paragraph)
        return ExtractedContent(kind=FileKind.docx, blocks=self.blocks), self.mentions


# ---------------------------------------------------------------- şablonlar

def hr_file(b: DocBuilder, rng: random.Random, people: list[Person]) -> None:
    """İK / özlük dosyası — en yoğun PII taşıyan belge türü."""
    p, mgr = people[0], people[1]
    b.t("PERSONEL ÖZLÜK DOSYASI").heading()
    b.t("Çalışan: ").pii(p, "full_name").t(" — ").pii(p, "occupation")
    b.t(". İşyeri: ").pii(p, "employer").t(".").para()
    b.table_pii([
        ["Alan", "Değer"],
        ["Ad Soyad", (p, "full_name")],
        ["T.C. Kimlik No", (p, "tckn")],
        ["Telefon", (p, "phone")],
        ["E-posta", (p, "email")],
        ["Adres", (p, "address")],
        ["Maaş bandı", (p, "salary_band")],
        ["Öğrenim durumu", (p, "education")],
    ])
    b.t("Sağlık raporu: ").pii(p, "health").t(". Engel durumu: ").pii(p, "disability").t(".")
    b.para()
    b.t("Sendika: ").pii(p, "union").t(". Ücret ödemesi ").pii(p, "iban")
    b.t(" numaralı hesaba yapılmaktadır.").para()
    b.t("Dosya ").no_mask("Risk Değerlendirmesi").t(" kapsamında ")
    b.pii(mgr, "full_name").t(" tarafından incelenmiştir. ")
    b.pii(p, "alias", surface=p.aliases[0]).t(" ile görüşme yapılmıştır.").para()


def contract(b: DocBuilder, rng: random.Random, people: list[Person]) -> None:
    """Hukuk / sözleşme — taraflar, imza blokları, tekrarlanan taraf adları."""
    a, c = people[0], people[1]
    b.t("HİZMET SÖZLEŞMESİ").heading()
    b.t("İşbu sözleşme, bir tarafta ").pii(a, "full_name").t(" (T.C. ").pii(a, "tckn")
    b.t(", adres: ").pii(a, "address").t(") ile diğer tarafta ").pii(c, "full_name")
    b.t(" arasında akdedilmiştir.").para()
    b.t("Madde 1 — ").no_mask("Sözleşme Bedeli").t(": 480.000 TL + KDV. ")
    b.no_mask("Ödeme Planı").t(": üç eşit taksit.").para()
    b.t("Madde 2 — ").no_mask("Teslim Tarihi").t(": 30 Kasım 2026.").para()
    b.t("Ödemeler ").pii(a, "iban").t(" hesabına yapılacaktır. İletişim: ")
    b.pii(a, "email").t(" / ").pii(a, "phone").t(".").para()
    b.t("İmza: ").pii(a, "alias", surface=a.aliases[1]).t(" — ")
    b.pii(c, "alias", surface=c.aliases[2]).t(".").para()


def health_record(b: DocBuilder, rng: random.Random, people: list[Person]) -> None:
    """Sağlık — özel nitelikli veri yoğun (KVKK m.6)."""
    p, doc = people[0], people[1]
    b.t("HASTA DEĞERLENDİRME FORMU").heading()
    b.t("Hasta: ").pii(p, "full_name").t(" (T.C. ").pii(p, "tckn").t("), ")
    b.t(str(p.age)).t(" yaşında, ").pii(p, "occupation").t(".").para()
    b.t("Tanı: ").pii(p, "health").t(". Ek durum: ").pii(p, "disability").t(".").para()
    b.t("İkamet: ").pii(p, "district").t(" / ").t(p.city).t(". İletişim: ").pii(p, "phone")
    b.t(".").para()
    b.t("Değerlendiren hekim: ").pii(doc, "full_name").t(". Kontrol randevusu ")
    b.no_mask("Kalite Kontrol").t(" biriminden alınacaktır.").para()
    b.t("Hasta ").pii(p, "alias", surface=p.aliases[0]).t(" ile telefonla teyit edildi.").para()


def finance_doc(b: DocBuilder, rng: random.Random, people: list[Person]) -> None:
    """Finans / bankacılık — hesap, kart, IBAN yoğun."""
    p, ofc = people[0], people[1]
    b.t("MÜŞTERİ HESAP ÖZETİ").heading()
    b.t("Hesap sahibi: ").pii(p, "full_name").t(" — T.C. ").pii(p, "tckn").t(".").para()
    b.table_pii([
        ["Kalem", "Bilgi"],
        ["IBAN", (p, "iban")],
        ["Kart", (p, "card")],
        ["Kayıtlı telefon", (p, "phone")],
        ["E-posta", (p, "email")],
        ["Adres", (p, "address")],
    ])
    b.t("Gelir beyanı: ").pii(p, "salary_band").t(". İşveren: ").pii(p, "employer").t(".").para()
    b.t(" ").no_mask("Fatura Dönemi").t(": Ekim 2026. ").no_mask("Gider Pusulası")
    b.t(" ekte sunulmuştur.").para()
    # Aynı entity'nin ikinci geçişi + coreference varyantı: entity-level recall ancak bir varlık
    # birden fazla yüzeyle geçtiğinde mention-level'dan ayrışır (biri açık kalırsa entity düşer).
    b.t("Hesap sahibi ").pii(p, "full_name").t(" (").pii(p, "alias", surface=p.aliases[1])
    b.t(") ile teyit sağlanmıştır.").para()
    b.t("Müşteri temsilcisi ").pii(ofc, "full_name").t(" — ").pii(ofc, "email").t(".").para()


def public_form(b: DocBuilder, rng: random.Random, people: list[Person]) -> None:
    """Kamu / idari işlem — başvuru dilekçesi."""
    p, off = people[0], people[1]
    b.t("BAŞVURU DİLEKÇESİ").heading()
    b.t("Başvuran: ").pii(p, "full_name").t(", T.C. ").pii(p, "tckn").t(", ikamet: ")
    b.pii(p, "address").t(".").para()
    b.t("Mesleğim ").pii(p, "occupation").t(" olup ").pii(p, "employer")
    b.t(" bünyesinde çalışmaktayım. Öğrenim durumum: ").pii(p, "education").t(".").para()
    b.t("Hakkımdaki durum: ").pii(p, "legal").t(".").para()
    b.t("Tebligat adresim yukarıdadır; telefon ").pii(p, "phone").t(", e-posta ")
    b.pii(p, "email").t(".").para()
    # Aynı entity'nin ikinci geçişi + coreference varyantı (entity-level recall için gerekli).
    b.t("Gereğini arz ederim. ").pii(p, "full_name").t(" — ")
    b.pii(p, "alias", surface=p.aliases[1]).t(".").para()
    b.t("İşlemi yürüten memur: ").pii(off, "full_name").t(". ").no_mask("Yönetim Kurulu")
    b.t(" kararı beklenmektedir.").para()


def correspondence(b: DocBuilder, rng: random.Random, people: list[Person]) -> None:
    """Müşteri yazışması — serbest metin, PII cümle içine gömülü (kalıp dışı tespit testi)."""
    p, agent = people[0], people[1]
    b.t("MÜŞTERİ YAZIŞMASI").heading()
    b.t("Sayın ").pii(p, "alias", surface=p.aliases[0]).t(", ")
    b.t("14 Ekim 2026 tarihli talebiniz alınmıştır.").para()
    b.t("Kayıtlarımızda adınız ").pii(p, "full_name").t(" olarak, kimlik numaranız ")
    b.pii(p, "tckn").t(" olarak görünmektedir. ")
    b.t("Adresinizi ").pii(p, "address").t(" şeklinde güncelledik.").para()
    b.t("İade tutarı ").pii(p, "iban").t(" hesabına aktarılacaktır. ")
    b.t("Sorularınız için ").pii(agent, "email").t(" adresinden bize ulaşabilirsiniz.").para()
    b.t(p.district).t(" şubemizde ").pii(p, "occupation")
    b.t(" olarak çalıştığınızı belirtmiştiniz; ").no_mask("Teslim Tarihi")
    b.t(" bilgisi ayrıca iletilecektir.").para()


DOMAINS: dict[str, object] = {
    "hr": hr_file,
    "legal": contract,
    "health": health_record,
    "finance": finance_doc,
    "public": public_form,
    "correspondence": correspondence,
}

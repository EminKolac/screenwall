"""Human-readable reasons: why a value was masked, where a unit sits, why a document waits.

Everything the review screen says about a mask comes from here, derived from the edit's detector
entity type and source. Sentences are Turkish, short, and never contain the value itself.
"""
from __future__ import annotations

import re

from app.anonymization.types import USER_PREFIX
from app.models.document import LEGACY_STATUS_TEXT

_BY_TYPE = {
    "TR_TCKN": "TCKN doğrulandı",
    "TR_VKN": "Vergi numarası (bağlamla)",
    "TR_IBAN": "IBAN biçimi",
    "IBAN_CODE": "IBAN biçimi",
    "CREDIT_CARD": "Kart numarası doğrulandı",
    "EMAIL_ADDRESS": "E-posta biçimi",
    "TR_GSM": "Cep telefonu biçimi",
    "TR_PHONE": "Telefon (bağlamla)",
    "UK_PHONE": "Telefon biçimi",
    "PHONE_NUMBER": "Telefon biçimi",
    "IP_ADDRESS": "IP adresi",
    "URL": "Bağlantı",
    "SECRET_KEY": "Gizli anahtar biçimi",
    "TR_ACCOUNT": "Hesap numarası",
    "TR_PLATE": "Plaka biçimi",
    "TR_PASSPORT": "Pasaport numarası",
    "PASSPORT": "Pasaport numarası",
    "US_SSN": "Sosyal güvenlik numarası",
    "TR_COMPANY": "Şirket unvanı (yasal ek)",
    "TR_ADDRESS": "Adres biçimi",
    "TR_SALARY_BAND": "Maaş bilgisi",
    "TR_HEALTH": "Sağlık bilgisi",
    "TR_DISABILITY": "Engellilik bilgisi",
    "TR_PERSON_CTX": "Alan etiketi ve ad",
    "PERSON": "Ad (dil modeli)",
    "LOCATION": "Yer adı (dil modeli)",
    "ORGANIZATION": "Kurum adı (dil modeli)",
    "SENSITIVE": "Her zaman maskele listesi",
}

_BY_SOURCE = {
    "adjacency": "Hücrelere bölünmüş değer",
    "deny": "Her zaman maskele listesi",
    "user": "Sizin kararınız",
    "propagation:any": "Aynı değerin başka yazımı",
    "propagation:glued": "Adın bitişik yazımı",
    "propagation:surname": "Maskelenen adın soyadı",
    "propagation:company": "Şirket adının kısa biçimi",
}


def evidence(entity_type: str, source: str) -> list[str]:
    """Machine reason codes for one edit, e.g. ["recognizer:TR_TCKN", "detector:tr"]."""
    codes = []
    if source in _BY_SOURCE or source.startswith("propagation"):
        codes.append(source)
    if entity_type.startswith(USER_PREFIX):
        codes.append("user")
    else:
        codes.append(f"recognizer:{entity_type}")
    if source in ("en", "tr"):
        codes.append(f"detector:{source}")
    return codes


def reason(entity_type: str, source: str) -> str:
    if source in _BY_SOURCE:
        return _BY_SOURCE[source]
    if entity_type.startswith(USER_PREFIX):
        return _BY_SOURCE["user"]
    return _BY_TYPE.get(entity_type, "Kişisel veri deseni")


_LOCATION_RULES = [
    (re.compile(r"^page (\d+) table"), lambda m: f"Sayfa {m[1]} · tablo"),
    (re.compile(r"^page (\d+) annotation"), lambda m: f"Sayfa {m[1]} · not"),
    (re.compile(r"^page (\d+)"), lambda m: f"Sayfa {m[1]}"),
    (re.compile(r"^para (\d+)"), lambda m: f"Paragraf {m[1]}"),
    (re.compile(r"^table (\d+)"), lambda m: f"Tablo {m[1]}"),
    (re.compile(r"^sheet (.+)$"), lambda m: f"{m[1]} sayfası"),
    (re.compile(r"^comment"), lambda m: "Yorum"),
    (re.compile(r"^header"), lambda m: "Üst bilgi"),
    (re.compile(r"^footer"), lambda m: "Alt bilgi"),
]


def location_label(location: str) -> str:
    for pattern, render in _LOCATION_RULES:
        m = pattern.match(location or "")
        if m:
            return render(m)
    return location or "Belge"


FINDING_REASON = "Denetim burada kişisel veri kalmış olabileceğini söylüyor"

# Extraction reasons (no_text, ocr_unavailable, ...) live with their detection in services/ingest.
REVIEW_REASONS = {
    "audit_residual": "Denetim maskeli metinde kişisel veri kalmış olabileceğini buldu.",
    "auditor_unavailable": "Lokal LLM denetimi çalışmıyordu; belge otomatik onaylanmadı.",
    "processing_failed": "Belge işlenirken bir hata oluştu.",
    "processing_interrupted": "İşlem yarıda kaldı; belgeyi yeniden yükleyin.",
    "changed_after_approval": "Onaydan sonra değişiklik yapıldı; yeniden onay gerekiyor.",
    "legacy_status": LEGACY_STATUS_TEXT,
    "settings_unreadable": ("Ayarlar dosyası okunamadı; 'her zaman maskele' listeniz bu belgeye "
                            "uygulanmadı. Metni dikkatle inceleyin."),
}


def unlocated_reason(count: int) -> str:
    return (f"Denetim {count} olası kalıntı bildirdi ama metinde yerini gösteremedi; lütfen "
            "metni gözden geçirin.")

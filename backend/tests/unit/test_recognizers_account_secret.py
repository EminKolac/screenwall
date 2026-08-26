"""TR_ACCOUNT ve SECRET_KEY tanıyıcılarının birim testleri.

Neden bu iki tür: base Presidio'da ne ACCOUNT ne de SECRET tanıyıcısı var. Benchmark'ta
hesap/müşteri numarası recall'u %0 ölçüldü (BIST canary'de başarısız olan tek tür), API key ise
stress setinde sızan vakalardan biriydi.

Testler tanıyıcıları DOĞRUDAN çağırır (tüm pipeline'ı kurmadan). Bu yüzden dönen score'lar
BASE score'dur: Presidio'nun bağlam artışı (LemmaContextAwareEnhancer, +0.35 ve 0.4 tabanı)
AnalyzerEngine katmanında uygulanır, recognizer içinde değil. Dolayısıyla "bağlam zorunlu"
iddiası burada iki parçalı doğrulanır:
  1. base score < eşik (0.4)  → bağlamsız hiçbir çıplak sayı maskelenemez,
  2. base + 0.35 >= eşik      → bağlam kelimesi varsa maskelenir.
"""
from __future__ import annotations

import pytest

from app.anonymization.recognizers.turkish import turkish_recognizers

# app/config.py::anonymizer_score_threshold varsayılanı. Testler bu eşiğe göre kalibre edilmiş
# score'ları korur; eşik değişirse burası da bilinçli olarak güncellenmeli.
SCORE_THRESHOLD = 0.4
# presidio_analyzer LemmaContextAwareEnhancer varsayılanı (context_similarity_factor).
CONTEXT_BOOST = 0.35


def _recognizer(entity: str):
    for rec in turkish_recognizers():
        if entity in rec.supported_entities:
            return rec
    raise AssertionError(f"{entity} tanıyıcısı kayıtlı değil")


def _analyze(entity: str, text: str):
    rec = _recognizer(entity)
    return rec.analyze(text, entities=[entity], nlp_artifacts=None) or []


def _matched(entity: str, text: str) -> list[str]:
    return [text[r.start:r.end] for r in _analyze(entity, text)]


# --- TR_ACCOUNT: pozitif ---------------------------------------------------------------------

@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Hesap no: 8842-556310-04 üzerinden ödeme yapılmıştır.", "8842-556310-04"),
        ("Müşteri numarası 45219078 olan abonelik iptal edildi.", "45219078"),
        ("Cari hesap 1029384756 bakiyesi güncellendi.", "1029384756"),
        ("Abone no 7788990 için sözleşme yenilendi.", "7788990"),
    ],
)
def test_account_formats_detected(text: str, expected: str) -> None:
    assert expected in _matched("TR_ACCOUNT", text)


def test_account_base_score_requires_context() -> None:
    """Bağlam OLMADAN eşiği geçemez, bağlam İLE geçer — aşırı-maskelemeye karşı ana koruma."""
    results = _analyze("TR_ACCOUNT", "Hesap no: 45219078")
    assert results, "desen eşleşmeli"
    score = results[0].score
    assert score < SCORE_THRESHOLD, "bağlamsız çıplak sayı tek başına maskelenmemeli"
    assert score + CONTEXT_BOOST >= SCORE_THRESHOLD, "bağlam kelimesiyle eşiği geçmeli"


# --- TR_ACCOUNT: negatif (EN ÖNEMLİ BÖLÜM) ---------------------------------------------------
# Bu cümleler gerçek finansal belgelerden alınan biçimlerdir. Maskelenirlerse ölçülen
# %100 over-masking sorunu büyür ve rapor okunamaz hale gelir.

@pytest.mark.parametrize(
    "text",
    [
        "2026 yılında 450.000 TL tutarında yatırım harcaması gerçekleşmiştir.",
        "Sayfa 12 / 340",
        "Vergi matrahı 1.250.000 TL olarak hesaplanmıştır.",
        "31 Aralık 2025 tarihli finansal tablolar bağımsız denetimden geçmiştir.",
        "Net dönem karı 98.765.432 TL seviyesindedir.",
        "Faaliyet giderleri %12,4 oranında artmıştır.",
        "Toplam varlıklar 3.201.559 bin TL'dir.",
        "Madde 4-2 uyarınca genel kurul toplanmıştır.",
    ],
)
def test_account_does_not_match_financial_noise(text: str) -> None:
    assert _matched("TR_ACCOUNT", text) == []


def test_account_ignores_long_invoice_numbers() -> None:
    """12+ haneli fatura/sipariş numaraları kapsam dışı (üst sınır 11 hane)."""
    assert _matched("TR_ACCOUNT", "Fatura No: 202400123456789") == []


# --- SECRET_KEY: pozitif ---------------------------------------------------------------------

@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Erişim anahtarı sk_live_9Qm2fXbT7hVrN4KpLZ olarak tanımlıdır.",
         "sk_live_9Qm2fXbT7hVrN4KpLZ"),
        ("Test ortamı: pk_test_ABCdef1234567890xyz", "pk_test_ABCdef1234567890xyz"),
        ("key AKIAIOSFODNN7EXAMPLE end", "AKIAIOSFODNN7EXAMPLE"),
        ("token ghp_abcdefghij0123456789ABCDEFghijklmnopqr",
         "ghp_abcdefghij0123456789ABCDEFghijklmnopqr"),
        ("Maps anahtarı AIzaSyD1234567890abcdefghijklmnopqrst kullanılıyor.",
         "AIzaSyD1234567890abcdefghijklmnopqrst"),
    ],
)
def test_secret_prefixed_formats_detected(text: str, expected: str) -> None:
    assert expected in _matched("SECRET_KEY", text)


def test_secret_prefixed_score_clears_threshold_without_context() -> None:
    """Ayırt edici prefix'ler doğal metinde tesadüfen oluşmaz → bağlam beklemek sızıntı riski."""
    results = _analyze("SECRET_KEY", "sk_live_9Qm2fXbT7hVrN4KpLZ")
    assert results and results[0].score >= SCORE_THRESHOLD


def test_secret_bearer_and_jwt_detected() -> None:
    assert _matched("SECRET_KEY", "Authorization: Bearer aZ39Kp7Qw12MtokenValue")
    jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dBjftJeZ4CVPmB92K27uhbUJU1p1r0"
    assert jwt in _matched("SECRET_KEY", f"Token: {jwt}")


def test_secret_generic_entropy_requires_context() -> None:
    """32+ karakterlik genel dizi ÇOK gürültülü → tek başına eşiğin altında kalmalı."""
    token = "aB3dE5gH7jK9mN1pQ3sT5vW7yZ9aB3dE5gH7jK9m"  # 40 karakter
    results = _analyze("SECRET_KEY", f"Anahtar {token} olarak saklanır.")
    assert results, "desen eşleşmeli"
    generic = min(r.score for r in results)
    assert generic < SCORE_THRESHOLD, "bağlamsız yüksek-entropi dizisi maskelenmemeli"
    assert generic + CONTEXT_BOOST >= SCORE_THRESHOLD


# --- SECRET_KEY: negatif ---------------------------------------------------------------------

@pytest.mark.parametrize(
    "text",
    [
        "Şirketin 2025 yılı sürdürülebilirlik raporu yayımlanmıştır.",
        "Konsolide finansal tablolar bağımsız denetçi görüşü ile sunulmuştur.",
        "Sayfa 12 / 340",
        "Toplam gelir 1.234.567 TL olarak gerçekleşti.",
    ],
)
def test_secret_does_not_match_ordinary_prose(text: str) -> None:
    assert _matched("SECRET_KEY", text) == []


def test_secret_short_identifiers_not_matched() -> None:
    """32 karakterin altındaki sıradan tanımlayıcılar genel desene takılmamalı."""
    assert _matched("SECRET_KEY", "Belge kodu FR-2025-KURUMSAL-YONETIM olarak atandı.") == []


# --- Regresyon ------------------------------------------------------------------------------

def test_existing_recognizers_still_registered() -> None:
    entities = {e for rec in turkish_recognizers() for e in rec.supported_entities}
    assert {
        "TR_TCKN", "TR_VKN", "TR_GSM", "TR_PHONE", "TR_IBAN", "TR_PLATE", "TR_PASSPORT",
        "TR_ACCOUNT", "SECRET_KEY",
    } <= entities

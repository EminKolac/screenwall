"""Turkish-specific Presidio recognizers (regex + checksum, context-boosted).

TCKN uses the official checksum (high precision). VKN/landline/plate/passport use low base
scores raised by context words, so bare numbers are not over-flagged below the score threshold.
"""
from __future__ import annotations

import re

from presidio_analyzer import Pattern, PatternRecognizer


def valid_tckn(text: str) -> bool:
    """Validate a Turkish national ID (TCKN) by its checksum digits."""
    s = "".join(ch for ch in text if ch.isdigit())
    if len(s) != 11 or s[0] == "0":
        return False
    d = [int(c) for c in s]
    if sum(d[:10]) % 10 != d[10]:
        return False
    odd = d[0] + d[2] + d[4] + d[6] + d[8]
    even = d[1] + d[3] + d[5] + d[7]
    return (odd * 7 - even) % 10 == d[9]


class _TcknRecognizer(PatternRecognizer):
    def __init__(self) -> None:
        super().__init__(
            supported_entity="TR_TCKN",
            supported_language="tr",
            patterns=[Pattern("tckn", r"\b[1-9][0-9]{10}\b", 0.3)],
            context=["tckn", "kimlik", "t.c.", "tc kimlik", "kimlik no"],
        )

    def validate_result(self, pattern_text: str):  # noqa: D102
        return valid_tckn(pattern_text)


def turkish_recognizers() -> list[PatternRecognizer]:
    return [
        _TcknRecognizer(),
        PatternRecognizer(
            supported_entity="TR_VKN", supported_language="tr",
            patterns=[Pattern("vkn", r"\b\d{10}\b", 0.2)],
            context=["vkn", "vergi", "vergi no", "vergi kimlik", "vergi dairesi"],
        ),
        PatternRecognizer(
            supported_entity="TR_GSM", supported_language="tr",
            # `\b` DEĞİL `(?<![\w+])`: `\b` boşluk ile "+" arasında eşleşmediği için "+90 532 764
            # 21 09" span'i "+"ı dışarıda bırakıyordu (kısmi span; english.py'deki UK_PHONE ile
            # aynı kök neden, aynı düzeltme — ölçümle bulundu, bkz. thoughts/EXPERIMENTS.md).
            patterns=[Pattern(
                "gsm", r"(?<![\w+])(?:\+?90[ -]?|0)?5\d{2}[ -]?\d{3}[ -]?\d{2}[ -]?\d{2}\b", 0.5)],
            context=["gsm", "cep", "telefon", "tel"],
        ),
        PatternRecognizer(
            supported_entity="TR_PHONE", supported_language="tr",
            patterns=[Pattern(
                "landline",
                # TR_GSM ile aynı `(?<![\w+])` düzeltmesi (bkz. yukarıdaki gerekçe).
                r"(?<![\w+])(?:\+?90[ -]?|0)?(?:2|3|4)\d{2}[ -]?\d{3}[ -]?\d{2}[ -]?\d{2}\b",
                0.3)],
            context=["tel", "telefon", "faks", "sabit"],
        ),
        PatternRecognizer(
            supported_entity="TR_IBAN", supported_language="tr",
            patterns=[Pattern("tr_iban", r"\bTR\d{2}[ ]?(?:\d{4}[ ]?){5}\d{2}\b", 0.7)],
            context=["iban", "hesap"],
        ),
        PatternRecognizer(
            supported_entity="TR_PLATE", supported_language="tr",
            patterns=[Pattern(
                "plate", r"\b(?:0[1-9]|[1-7]\d|8[01])[ ]?[A-ZÇĞİÖŞÜ]{1,3}[ ]?\d{2,4}\b", 0.4)],
            context=["plaka", "araç", "arac"],
        ),
        PatternRecognizer(
            supported_entity="TR_PASSPORT", supported_language="tr",
            # Deney döngüsü Faz 2 — GoldBench stres testinde bir PDF form widget'ının pasaport
            # değeri (bağlam kelimesi olmadan, izole bir alanda) kaçtı: context uplift (+0.35)
            # tetiklenmedi çünkü değer kendi bloğunda tek başınaydı. Diğer kritik/DIRECT
            # türlerin (TCKN checksum'lı, IBAN/GSM yapısal) hiçbiri salt bağlama muhtaç değil —
            # PASSPORT da aynı sınıfta (kullanıcının "kritik türlerde bağlama güvenme" kararı).
            # Taban 0.3→0.45: eşiği (0.4) bağlamsız da geçer, ama context'siz saf desen
            # eşleşmesiyle hâlâ en düşük güven bandında kalır (TR_IBAN 0.7, TR_PLATE 0.4'ün
            # altında) — assay: bu artışın GoldBench recall/aşırı-maskeleme dengesini bozup
            # bozmadığı ayrı ölçüldü (bkz. thoughts/EXPERIMENTS.md iterasyon 2).
            patterns=[Pattern("tr_passport", r"\b[A-Z]\d{8}\b", 0.45)],
            context=["pasaport", "passport"],
        ),
        _account_recognizer(),
        _secret_recognizer(),
        _salary_band_recognizer(),
        _company_recognizer(),
        _address_recognizer(),
        _disability_recognizer(),
        _health_recognizer(),
        _person_context_recognizer(),
    ]


# --- ACCOUNT ---------------------------------------------------------------------------------
# Neden: base Presidio'da ACCOUNT tanıyıcısı YOK; benchmark'ta hesap/müşteri numarası recall'u
# %0 ölçüldü (BIST canary'de başarısız olan tek tür). Ama çıplak rakam dizisi finansal
# belgelerde tutar/matrah/sayfa/sipariş no ile birebir çakışır — bu yüzden desenler DÜŞÜK base
# score alır ve tek başlarına eşiği (anonymizer_score_threshold = 0.4) GEÇEMEZ.
#
# Skor mantığı (TR_VKN ile aynı kalibrasyon): base 0.25 + Presidio bağlam artışı 0.35 = 0.60
# > 0.4 eşik. Bağlam kelimesi yoksa 0.25 < 0.4 → maskelenmez. Yani bağlam ZORUNLU, ki
# projenin en büyük sorunu olan aşırı-maskelemeye yeni bir gürültü kaynağı eklenmesin.
_ACCOUNT_BASE_SCORE = 0.25

# Gruplu hesap no (örn. "8842-556310-04"): üç grup + tire zorunlu. İki gruplu biçim
# ("2024-2025" yıl aralığı, "12-34" madde no) BİLEREK dışarıda bırakıldı — orada ayırt edici
# sinyal yok, sadece yanlış pozitif üretirdi.
_ACCOUNT_GROUPED = r"\b\d{3,6}-\d{4,8}-\d{1,4}\b"

# Çıplak hesap/müşteri/abone no: 7-11 hane, ayraçsız. Türkçe finansal metinde tutarlar binlik
# ayraçlı yazılır ("1.250.000", "450.000"), bu yüzden \b sınırları o sayıları parçalar ve
# hiçbir parça 7 haneye ulaşmaz. Yıl (4), sayfa no (1-3) zaten kısa kalır. 12+ hane fatura/
# sipariş numaraları da kapsam dışı (üst sınır 11).
_ACCOUNT_BARE = r"\b\d{7,11}\b"


def _account_recognizer() -> PatternRecognizer:
    return PatternRecognizer(
        supported_entity="TR_ACCOUNT", supported_language="tr",
        patterns=[
            # Deney v5 — GRUPLU desen 0.45: üç grup + iki tire ("8842-556310-04") doğal Türkçe
            # metinde bağlam olmadan da yeterince özgül (BIST canary D1'deki 128 isabetin kökü,
            # bağlam kelimesiz enjeksiyondu). Emsal: TR_PASSPORT 0.3→0.45 holdout'ta sıfır yan
            # etkiyle geçti. ÇIPLAK desen (7-11 hane) bağlam şartında KALIR — o gerçekten
            # belirsiz (sipariş no, iç referans...).
            Pattern("account_grouped", _ACCOUNT_GROUPED, 0.45),
            Pattern("account_bare", _ACCOUNT_BARE, _ACCOUNT_BASE_SCORE),
        ],
        # Tek token'lar: Presidio bağlam eşleştirmesi lemma/token bazlıdır, çok kelimeli
        # ifadeler ("müşteri no") zaten token'larına bölünerek eşleşir. "no"/"numara" gibi
        # aşırı genel token'lar KASITLI olarak yok — her belgede geçer, bağlam kapısını
        # işlevsiz bırakırdı. "vergi"/"fatura" da yok: onlar TR_VKN'nin alanı.
        context=[
            "hesap", "müşteri", "musteri", "abone", "sözleşme", "sozlesme",
            "cari", "account", "iban",
        ],
    )


# --- SECRET ----------------------------------------------------------------------------------
# Neden: stress setinde sızan vakalardan biri API key'di. Desenler iki sınıfa ayrılır:
#   1) Ayırt edici prefix'li (sk_live_, AKIA, ghp_, AIza, JWT) → kendi başına yüksek score;
#      bu biçimler doğal metinde tesadüfen oluşmaz, bağlam beklemek sızıntı riski yaratır.
#   2) Genel yüksek-entropi dizisi → ÇOK gürültülü (hash, dosya adı, base64 gövde, uzun
#      kelime birleşimi), bu yüzden base 0.15 ile eşiğin altında tutulur ve ancak bağlam
#      kelimesiyle (0.15 + 0.35 = 0.50) maskelenir.
# app/audit/heuristic.py'deki backstop desenleriyle bilinçli olarak hizalı: aynı biçimler,
# ama burada tespit (maskeleme) aşamasında, orada son kontrol aşamasında.
_SECRET_GENERIC_BASE_SCORE = 0.15


def _secret_recognizer() -> PatternRecognizer:
    return PatternRecognizer(
        supported_entity="SECRET_KEY", supported_language="tr",
        patterns=[
            # Stripe-vari yayınlanabilir/gizli anahtarlar. 8+ gövde: kısa "sk_test_x" gibi
            # dokümantasyon örneklerini elemek için.
            # Deney v5 iter 3 — gövde {8,}→{4,} + opsiyonel TEK boşluk arası ikinci parça:
            # OOXML split-run bir anahtarı "sk_live_9Qm2f XbT7hVrN4KpLZ" gibi boşlukla bölüyor
            # (GoldBench stres docx-split_run_pii-08, kritik yanlış onay — dünkü motorda da
            # sızıyordu, izolasyonla doğrulandı). İkinci parçada `(?=[^ ]*\d)` ŞART — ilk sürüm
            # bu şartsızdı ve anahtarı izleyen sıradan kelimeyi yutuyordu ("sk_live_… olarak" tek
            # span oldu; birim testi yakaladı, ölçüldü): anahtar parçası rakam içerir, Türkçe/
            # İngilizce kelime içermez. Prefix (sk|pk|rk)_(live|test)_ zaten çok özgül; "sk_test_x"
            # gibi 1-3 karakterlik dokümantasyon örnekleri {4,} ile hâlâ dışarıda.
            Pattern("secret_stripe",
                    r"\b(?:sk|pk|rk)_(?:live|test)_[A-Za-z0-9]{4,}"
                    r"(?: (?=[A-Za-z0-9]*\d)[A-Za-z0-9]{6,})?\b", 0.85),
            # AWS access key id: AKIA + 16 büyük harf/rakam (12+ esnek tutuldu, eski
            # ASIA/ABIA varyantları için değil — sadece AKIA, yanlış pozitif olmasın).
            Pattern("secret_aws", r"\bAKIA[0-9A-Z]{12,}\b", 0.8),
            # GitHub token aileleri (personal/oauth/user/server/refresh).
            Pattern("secret_github", r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}\b", 0.85),
            # Google API key.
            Pattern("secret_google", r"\bAIza[0-9A-Za-z_\-]{18,}\b", 0.8),
            # JWT: üç base64url parçası, "eyJ" ile başlayan header. Nokta ayraçları ayırt edici.
            Pattern(
                "secret_jwt",
                r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\b",
                0.8,
            ),
            # "Bearer <token>": anahtar kelimenin kendisi bağlamı taşıdığı için score yüksek.
            # Span "Bearer" kelimesini de kapsar — Presidio tam eşleşmeyi maskeler; şemayı
            # kaybetmek zararsız, token'ın yarısını açıkta bırakmak değil.
            Pattern("secret_bearer", r"(?i)\bBearer\s+[A-Za-z0-9._\-]{16,}", 0.7),
            # Genel yüksek-entropi: TEK BAŞINA eşiği geçemez, bağlam kelimesi zorunlu.
            Pattern("secret_generic", r"\b[A-Za-z0-9_\-]{32,}\b", _SECRET_GENERIC_BASE_SCORE),
        ],
        context=[
            "token", "secret", "apikey", "api", "key", "anahtar", "credential",
            "şifre", "sifre", "parola", "password", "authorization", "bearer",
        ],
    )


# --- SALARY BAND -------------------------------------------------------------------------------
# Deney döngüsü (Faz 2, iterasyon 1): GoldBench'te leaked_in_export'un %71'i (42/59) SALARY
# türünden ve bu tür için HİÇ tanıyıcı yoktu — bu maaş bandı ("60.000-85.000 TL") bir QUASI
# tanımlayıcı (KVKK m.3'ün "başka verilerle eşleştirilerek dahi" ibaresinin konusu), tek başına
# değil ama meslek/işyeri ile birleşince kimliği daraltır.
#
# İki kalıp: aralık ("45.000-60.000 TL") ve alt-sınır ("120.000 TL üzeri"). İkisi de bir tekil
# tutarla (örn. "Sözleşme Bedeli 480.000 TL") ÇAKIŞMAZ — biri tire ile aralık, biri "üzeri"
# sonekini şart koşar. Yine de bağlam zorunlu tutuldu (base 0.3 + 0.35 artış = 0.65 > 0.4 eşik,
# bağlamsız 0.3 < 0.4 elenir) — genel finansal tutar aralıkları (kredi limiti vb.) ile
# karışmasın diye.
_SALARY_RANGE = r"\b\d{1,3}(?:\.\d{3})*\s*-\s*\d{1,3}(?:\.\d{3})*\s*TL\b"
_SALARY_FLOOR = r"\b\d{1,3}(?:\.\d{3})*\s*TL\s*üzeri\b"


def _salary_band_recognizer() -> PatternRecognizer:
    return PatternRecognizer(
        supported_entity="TR_SALARY_BAND", supported_language="tr",
        patterns=[
            Pattern("salary_range", _SALARY_RANGE, 0.3),
            Pattern("salary_floor", _SALARY_FLOOR, 0.3),
        ],
        context=["maaş", "ücret", "gelir", "salary", "bandı", "bordro"],
    )


# --- ŞİRKET UNVANI (TR_COMPANY) ------------------------------------------------------------
# Deney döngüsü Faz 2 iter 2: leaked_in_export'un kalanının %88'i (15/17) EMPLOYER — Faz 1'de
# aşırı-maskelemeyi kesmek için ORGANIZATION'ı köreltmemin doğrudan maliyeti (SpacyRecognizer
# context=[] taşıdığı için o tür artık bağlamla da kurtarılamıyor). Çözüm ORGANIZATION'ı geri
# açmak DEĞİL (o zaten "API"/"TL" gibi yanlış pozitifleri üretiyordu) — Türk şirket unvanı
# eklerini (A.Ş., Ltd. Şti., A.O.) yakalayan DAR bir pattern tanıyıcı. Bu ekler doğal Türkçe
# metinde neredeyse yalnızca gerçek şirket unvanlarında geçer; TCKN/IBAN gibi güçlü bir yapısal
# sinyal olduğu için bağlam ZORUNLU değil (base score tek başına eşiği geçer).
_TR_COMPANY = (
    r"\b(?:[A-ZÇĞİÖŞÜ][a-zçğıöşüA-ZÇĞİÖŞÜ]*\s+){1,5}"
    r"(?:A\.Ş\.|Ltd\.\s*Şti\.|A\.O\.|Koll\.\s*Şti\.)"
)


def _company_recognizer() -> PatternRecognizer:
    # global_regex_flags OVERRIDE: PatternRecognizer'ın varsayılanı re.IGNORECASE içerir (Presidio
    # kaynağından doğrulandı). Bu desen büyük harfle başlayan ardışık kelimeler sinyaline dayanıyor
    # — IGNORECASE altında [A-ZÇĞİÖŞÜ] küçük harfle de eşleşir, sinyal tamamen anlamsızlaşır
    # (ölçüldü: "Sözleşme bedeli hakkında Anadolu Metal Sanayi A.Ş." → "bedeli hakkında" da
    # span'e dahil oluyordu). Bu yüzden bu tanıyıcı için IGNORECASE'i AÇIKÇA kapatıyoruz.
    import re as _re

    return PatternRecognizer(
        supported_entity="TR_COMPANY", supported_language="tr",
        patterns=[Pattern("tr_company", _TR_COMPANY, 0.55)],
        context=["şirket", "firma", "işveren", "sirket"],
        global_regex_flags=_re.DOTALL | _re.MULTILINE,
    )


# --- ADRES (TR_ADDRESS) --------------------------------------------------------------------
# Deney döngüsü Faz 2 iter 3: kalan 2 kritik kaçış ADDRESS türünden — Türkçe için özel bir adres
# tanıyıcısı hiç yoktu (grep ile doğrulanmıştı), adres tespiti tamamen genel LOCATION NER'e
# dayanıyordu ve o da bilinen sınırlarla kısmen kaçırıyordu. LOCATION'ı köreltmek riskliydi
# (Faz 1'de bilinçli olarak dokunulmadı); onun yerine iter 2'deki TR_COMPANY ile aynı strateji:
# yapısal bir adres kalıbı ("<Cadde/Bulvar/Sokak adı> No <sayı> <ilçe> <şehir>").
# TR_COMPANY'nin öğrettiği ders burada da geçerli: IGNORECASE kapalı olmalı, aksi halde büyük
# harf sinyali anlamsızlaşır.
_TR_ADDRESS = (
    r"\b(?:[A-ZÇĞİÖŞÜ][a-zçğıöşüA-ZÇĞİÖŞÜ]*\s+){1,4}"
    r"(?:Caddesi|Cadde|Bulvarı|Bulvar|Sokak|Sokağı|Mahallesi|Mahalle)\s+"
    r"No\.?\s*\d+\s+"
    r"(?:[A-ZÇĞİÖŞÜ][a-zçğıöşüA-ZÇĞİÖŞÜ]*\s*){1,3}"
)


def _address_recognizer() -> PatternRecognizer:
    import re as _re

    return PatternRecognizer(
        supported_entity="TR_ADDRESS", supported_language="tr",
        patterns=[Pattern("tr_address", _TR_ADDRESS, 0.5)],
        context=["adres", "ikamet", "tebligat"],
        global_regex_flags=_re.DOTALL | _re.MULTILINE,
    )


# --- ENGELLİLİK YÜZDESİ (TR_DISABILITY) ----------------------------------------------------
# Deney döngüsü Faz 2 iter 4 (holdout doğrulaması bulgusu): dev/public örnekleminde 0 kritik
# kaçış görünse de, hiç dokunulmamış holdout split'inde HEALTH+DISABILITY 37/42 kritik kaçışı
# oluşturdu — küçük örneklemin gizlediği gerçek bir boşluktu. Engellilik oranı Türkçe idari/
# İK belgelerinde neredeyse hep "%NN <işlev> kaybı" ya da "<işlev> engel (%NN)" kalıbıyla
# yazılır — yapısal, ayırt edici bir sinyal (TR_COMPANY/TR_ADDRESS ile aynı strateji).
_TR_DISABILITY = (
    r"(?:%\s*\d{1,3}\s+(?:işitme|görme|zihinsel|fiziksel|ortopedik)\s+kayb[ıi]"
    r"|(?:işitme|görme|zihinsel|fiziksel|ortopedik)\s+engel\s*\(%\s*\d{1,3}\))"
)


def _disability_recognizer() -> PatternRecognizer:
    import re as _re

    return PatternRecognizer(
        supported_entity="TR_DISABILITY", supported_language="tr",
        patterns=[Pattern("tr_disability", _TR_DISABILITY, 0.6)],
        context=["engel", "engelli", "kayıp"],
        global_regex_flags=_re.DOTALL | _re.MULTILINE,
    )


# --- TANI / SAĞLIK DURUMU (TR_HEALTH) ------------------------------------------------------
# Açık kelime dağarcığı (serbest tanı adları) genel bir regex'le yakalanamaz — bu yüzden gerçek
# bir Türkçe tanı/sağlık durumu terim sözlüğü (yaygın kronik hastalık ve ruh sağlığı terimleri).
# `allowlist_tr.py` ile aynı ilke: sadece GoldBench'in 7 örneğine değil, gerçek dünyada sık
# geçen ~25 terime genellenir — aksi halde bu, benchmark'a özel bir kısayol olurdu, gerçek bir
# tespit iyileştirmesi değil. Açık uçlu tanı adları (bu listede olmayan nadir hastalıklar) için
# kapsam dışı: Privacy Filter (bağlamsal, Faz 2'nin ayrı bir alt görevi) bu sınırı kapatacak.
_HEALTH_TERMS = [
    "tip 1 diyabet", "tip 2 diyabet", "diyabet", "hipertansiyon", "astım", "bel fıtığı",
    "migren", "romatoid artrit", "tiroid rahatsızlığı", "kalp yetmezliği", "böbrek yetmezliği",
    "karaciğer yetmezliği", "kronik böbrek hastalığı", "depresyon", "anksiyete bozukluğu",
    "panik atak", "epilepsi", "koroner arter hastalığı",
    "kronik obstrüktif akciğer hastalığı", "koah", "osteoporoz", "skolyoz", "fibromiyalji",
    "meme kanseri", "akciğer kanseri", "multipl skleroz",
]


def _health_recognizer() -> PatternRecognizer:
    return PatternRecognizer(
        supported_entity="TR_HEALTH", supported_language="tr",
        deny_list=_HEALTH_TERMS, deny_list_score=0.85,
    )


# --- PERSON (etiket-bağlamlı) ---------------------------------------------------------------
# Neden: fast yolda (PF kapalı) holdout PERSON kaçışlarının teşhisi (EXPERIMENTS.md v5) net bir
# desen gösterdi: kaçan adların çoğu "Hesap sahibi:", "Müşteri temsilcisi", "Hasta:" gibi bir
# ETİKETİN hemen ardından geliyor ve xx_ent_wiki_sm bunları görmüyor. Aynı sinyalin gücü Perde
# kıyasında da ölçüldü (rol-işaretli yapılandırılmış belgelerde %100 isim recall'u). Etiketler
# alan-genel Türkçe iş/idare kalıpları — GoldBench'e özgü değil (benchmark-kısayolu yasağı).
#
# İki ölçülmüş derse uyum: (1) IGNORECASE kapalı — büyük harf sinyali desenin özü ("Sözleşme
# bedeli hakkında..." dersi); (2) ad kısmı en fazla 3 kelime ve her kelime büyük harfle başlar,
# etiketin kendisi span dışında tutulur (yalnız yakalama grubu... Presidio grup desteklemez —
# lookbehind sabit-uzunluk ister, bu yüzden etiket span'e girer ve PERSON ailesinde maskelenir;
# etiket sözcüğünün maskelenmesi zararsızdır, adın açık kalmasından iyidir).
_PERSON_CTX = (
    r"(?:Sayın|Sn\.|Hasta|Hesap sahibi|Müşteri temsilcisi|Müşteri|Yetkili|Memur|Vekili|"
    r"temsilcisi|sahibi|yetkilisi|memur|adınız|Ad Soyad)"
    r"\s*[:\-–]?\s+"
    r"[A-ZÇĞİÖŞÜ][a-zçğıöşü'’-]+(?:\s+[A-ZÇĞİÖŞÜ][a-zçğıöşü'’-]+){1,2}"
)


def _person_context_recognizer() -> PatternRecognizer:
    # Tip PERSON DEĞİL TR_PERSON_CTX: istatistiksel-NER'e uygulanan ortografik kurallar
    # (tek-kelime elemesi, küçük-harfli-kelime elemesi) tip üzerinden ayırt edilir —
    # EntitySpan.source pattern/NER ayrımı taşımaz (PLAN §14.4'ün ölçülmüş sınırı). Yer tutucu
    # ailesi _TYPE_TO_PLACEHOLDER ile PERSON'a katlanır (TR_ADDRESS→LOCATION deseniyle aynı).
    return PatternRecognizer(
        supported_entity="TR_PERSON_CTX", supported_language="tr",
        patterns=[Pattern("tr_person_ctx", _PERSON_CTX, 0.5)],
        global_regex_flags=re.DOTALL | re.MULTILINE,  # IGNORECASE'siz — bkz. üstteki gerekçe
    )

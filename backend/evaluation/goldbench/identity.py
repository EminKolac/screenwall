"""Seeded sentetik kimlik/profil üreteci — GoldBench'in cevap anahtarının kaynağı.

Buradaki HİÇBİR değer gerçek bir kişiye ait değildir; hepsi tohumlanmış bir üreteçten gelir.
Bu, gerçek PII içeren belge kullanamamanın telafisi değil, bilinçli bir tercih: ground truth'u
biz ürettiğimiz için TAM — bu yüzden precision, F1/F2, R-Score ve attribute inference gibi
"neyin PII olmadığını da bilmeyi" gerektiren metrikler ancak burada hesaplanabilir. Gerçek
belgede (örn. BIST korpusu) tam envanter olmadığı için bunlar yapısal olarak ölçülemez.

Değerler GERÇEKTEN geçerli üretilir (TCKN checksum'ı, IBAN mod-97, kart Luhn) — bir tespit
kaçırması gerçek bir dedektör boşluğunu göstersin, bozuk girdiyi değil.

Profil üç katman taşır:
  - DIRECT      : tek başına kimliği belirler (ad, TCKN, IBAN, e-posta, telefon, adres)
  - QUASI       : birleşince belirler (doğum yılı, meslek, işyeri, ilçe, maaş bandı, eğitim)
  - SENSITIVE   : özel nitelikli (sağlık, engellilik, sendika, ceza geçmişi)
QUASI ve SENSITIVE katmanları attribute-inference saldırısının hedefidir: sistem tüm DIRECT
değerleri maskelese bile bu özellikler metinden çıkarılabiliyorsa gerçek gizlilik sağlanmamıştır.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

from evaluation.corpus import complete_tckn

_TR_FIRST_M = ["Ahmet", "Mehmet", "Mustafa", "Ali", "Hasan", "Emre", "Burak", "Serkan",
               "Volkan", "Kemal", "Oğuz", "Barış", "Cem", "Deniz", "Fatih"]
_TR_FIRST_F = ["Ayşe", "Fatma", "Zeynep", "Elif", "Merve", "Selin", "Deniz", "Gamze",
               "Pınar", "Ebru", "Şule", "Nalan", "Ceren", "Buse", "Yasemin"]
_TR_LAST = ["Yılmaz", "Kaya", "Demir", "Şahin", "Çelik", "Aydın", "Doğan", "Arslan",
            "Koç", "Kurt", "Özdemir", "Yıldız", "Aslan", "Çetin", "Erdoğan", "Polat"]
_EN_FIRST = ["James", "Sarah", "Michael", "Emily", "David", "Laura", "Robert", "Anna",
             "Thomas", "Claire", "Peter", "Julia"]
_EN_LAST = ["Whitfield", "Harrington", "Callahan", "Brooks", "Ellison", "Radcliffe",
            "Sinclair", "Merton", "Fairbanks", "Ashcroft"]

# İlçe–şehir eşleşmesi GERÇEK olmalı: "Kadıköy Ankara" gibi bir adres, quasi-identifier olarak
# coğrafi tutarlılığı bozar ve attribute-inference ölçümünü kirletir (saldırgan tutarsızlıktan
# sentetikliği anlar). Bu yüzden ilçe şehirden türetilir, bağımsız seçilmez.
_CITY_DISTRICTS: dict[str, list[str]] = {
    "İstanbul": ["Kadıköy", "Beşiktaş", "Şişli", "Üsküdar", "Bakırköy"],
    "Ankara": ["Çankaya", "Yenimahalle", "Keçiören", "Etimesgut"],
    "İzmir": ["Konak", "Karşıyaka", "Bornova", "Buca"],
    "Bursa": ["Nilüfer", "Osmangazi", "Yıldırım"],
    "Antalya": ["Muratpaşa", "Kepez", "Konyaaltı"],
    "Konya": ["Selçuklu", "Meram", "Karatay"],
    "Eskişehir": ["Odunpazarı", "Tepebaşı"],
}
_CITIES = list(_CITY_DISTRICTS)
_STREETS = ["Bağdat Caddesi", "Atatürk Bulvarı", "İnönü Caddesi", "Cumhuriyet Caddesi",
            "Gazi Mustafa Kemal Bulvarı", "Fevzi Çakmak Sokak", "Barbaros Bulvarı"]

_OCCUPATIONS = ["makine mühendisi", "mali müşavir", "hemşire", "avukat", "öğretmen",
                "yazılım geliştirici", "tır şoförü", "eczacı", "mimar", "veri analisti",
                "iş güvenliği uzmanı", "gıda mühendisi"]
_EMPLOYERS = ["Anadolu Metal Sanayi A.Ş.", "Ege Tekstil Ltd. Şti.", "Marmara Lojistik A.Ş.",
              "Toros Gıda Sanayi A.Ş.", "Kuzey İnşaat Taahhüt Ltd. Şti.",
              "Batı Enerji Dağıtım A.Ş.", "Doğu Kimya Sanayi A.Ş."]
_EDUCATION = ["lise", "ön lisans", "lisans", "yüksek lisans", "doktora"]
_SALARY_BANDS = ["asgari ücret bandı", "45.000-60.000 TL", "60.000-85.000 TL",
                 "85.000-120.000 TL", "120.000 TL üzeri"]
_RELATIONS = ["eşi", "kardeşi", "annesi", "babası", "kızı", "oğlu"]

# Özel nitelikli kişisel veri (KVKK m.6) — sentetik. Attribute-inference saldırısının hedefi.
_HEALTH = ["tip 2 diyabet", "hipertansiyon", "astım", "bel fıtığı", "migren",
           "romatoid artrit", "tiroid rahatsızlığı"]
_DISABILITY = ["%40 işitme kaybı", "%25 görme kaybı", "ortopedik engel (%30)"]
_UNION = ["Türk Metal Sendikası üyesi", "Tekstil İşçileri Sendikası üyesi",
          "Öz Gıda-İş Sendikası üyesi"]
_LEGAL = ["hakkında derdest icra takibi bulunmakta",
          "geçmişte trafik kazası kaynaklı tazminat davası açmış",
          "iş mahkemesinde işe iade davası bulunmakta"]

_EMAIL_DOMAINS = ["ornekposta.com", "ornekmail.com.tr", "testkurum.org"]
_BANK_CODES = ["00061", "00010", "00012", "00015", "00046", "00064", "00067"]


def _iban_tr(rng: random.Random) -> str:
    """mod-97 geçerli sentetik TR IBAN üretir (TR kk + 5 banka + 1 rezerv + 16 hesap)."""
    body = rng.choice(_BANK_CODES) + "0" + "".join(str(rng.randint(0, 9)) for _ in range(16))
    # IBAN kontrol: ülke+00 sona alınır, harfler sayıya çevrilir (T=29, R=27), mod 97
    numeric = body + "2927" + "00"
    check = 98 - (int(numeric) % 97)
    iban = f"TR{check:02d}{body}"
    return " ".join(iban[i:i + 4] for i in range(0, len(iban), 4))


def _luhn_card(rng: random.Random) -> str:
    """Luhn-geçerli TEST kart numarası (4111 test BIN'i ile — gerçek kart değil)."""
    digits = [4, 1, 1, 1] + [rng.randint(0, 9) for _ in range(11)]
    total = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2 == 0:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    digits.append((10 - total % 10) % 10)
    s = "".join(map(str, digits))
    return " ".join(s[i:i + 4] for i in range(0, 16, 4))


def _ascii_slug(name: str) -> str:
    table = str.maketrans("çğıöşüÇĞİÖŞÜ", "cgiosuCGIOSU")
    return name.translate(table).lower().replace(" ", ".")


@dataclass
class Person:
    """Tutarlı bir sentetik veri sahibi. `subject_id` attribute-inference ve TRIR'de kullanılır."""

    subject_id: str
    full_name: str
    first_name: str
    last_name: str
    lang: str
    tckn: str
    phone: str
    email: str
    iban: str
    card: str
    address: str
    # QUASI
    birth_year: int
    age: int
    occupation: str
    employer: str
    district: str
    city: str
    education: str
    salary_band: str
    relation_note: str
    # SENSITIVE
    health: str
    disability: str
    union: str
    legal: str
    # coreference varyantları — aynı entity, farklı yüzey
    aliases: list[str] = field(default_factory=list)

    def attribute_truth(self) -> dict[str, str]:
        """Attribute-inference saldırısının cevap anahtarı (sistem bunları GİZLEMELİ)."""
        return {
            "occupation": self.occupation, "employer": self.employer,
            "district": self.district, "city": self.city,
            "education": self.education, "salary_band": self.salary_band,
            "health": self.health, "disability": self.disability,
            "union": self.union, "age_band": f"{self.age // 10 * 10}-{self.age // 10 * 10 + 9}",
        }


def make_person(rng: random.Random, idx: int, lang: str = "tr") -> Person:
    """Tek bir tutarlı sentetik kişi üretir. Aynı seed + idx → aynı kişi (determinizm)."""
    if lang == "en":
        first = rng.choice(_EN_FIRST)
        last = rng.choice(_EN_LAST)
        male = first in _EN_FIRST[:1] or rng.random() < 0.5
    else:
        male = rng.random() < 0.5
        first = rng.choice(_TR_FIRST_M if male else _TR_FIRST_F)
        last = rng.choice(_TR_LAST)
    full = f"{first} {last}"
    honorific = ("Bey" if male else "Hanım") if lang != "en" else ("Mr." if male else "Ms.")

    birth_year = rng.randint(1962, 2001)
    age = 2026 - birth_year
    city = rng.choice(_CITIES)
    district = rng.choice(_CITY_DISTRICTS[city])

    return Person(
        subject_id=f"S{idx:04d}",
        full_name=full, first_name=first, last_name=last, lang=lang,
        tckn=complete_tckn("".join(str(rng.randint(1, 9)) for _ in range(9))),
        phone=f"05{rng.randint(30, 59)} {rng.randint(100, 999)} "
              f"{rng.randint(10, 99)} {rng.randint(10, 99)}",
        email=f"{_ascii_slug(full)}@{rng.choice(_EMAIL_DOMAINS)}",
        iban=_iban_tr(rng),
        card=_luhn_card(rng),
        address=f"{rng.choice(_STREETS)} No {rng.randint(3, 240)} {district} {city}",
        birth_year=birth_year, age=age,
        occupation=rng.choice(_OCCUPATIONS), employer=rng.choice(_EMPLOYERS),
        district=district, city=city,
        education=rng.choice(_EDUCATION), salary_band=rng.choice(_SALARY_BANDS),
        relation_note=rng.choice(_RELATIONS),
        health=rng.choice(_HEALTH), disability=rng.choice(_DISABILITY),
        union=rng.choice(_UNION), legal=rng.choice(_LEGAL),
        aliases=[f"{first} {honorific}" if lang != "en" else f"{honorific} {last}",
                 f"{first[0]}. {last}", last],
    )


def candidate_pool(rng: random.Random, size: int, lang: str = "tr") -> list[Person]:
    """TRIR/linkage için sabit aday kişi havuzu. Saldırgan, anonim belgeyi bu havuzdaki
    kişilerle eşleştirmeye çalışır — havuz olmadan yeniden-tanımlama riski ölçülemez."""
    return [make_person(rng, i, lang) for i in range(size)]

"""Turkish structural recognizers: labelled name fields and official address notation.

Found on a real e-Devlet "Yerleşim Yeri ve Diğer Adres Belgesi" (2026-09-25): the holder's name
stood in "Adı : …" / "Soyadı : …" lines in CAPITALS and the address used the official
abbreviations ("… MAH. … SK. NO: 123 / NO: 45 İLÇE / İL"). The Title-case contextual person pattern
and the spelled-out address pattern could see neither, so both stayed unmasked.

Both rules rest on evidence the plan's table accepts on its own (plan §4, Faz 2):
- a labelled field value: the rest of a line that starts with a name label;
- an address marker (MAH./SK./CAD./BLV. or spelled out) together with a door number.
Both results are trimmed to the value, so the label itself stays readable.
"""
from __future__ import annotations

import re

from presidio_analyzer import Pattern, PatternRecognizer

_UP = "A-ZÇĞİÖŞÜ"
_LETTERS = f"{_UP}a-zçğıöşü"
_FLAGS = re.MULTILINE

# ------------------------------------------------------------------ person: labelled field

_NAME_LABELS = (
    "Adı Soyadı", "Adı-Soyadı", "Adı ve Soyadı", "Ad Soyad", "Ad-Soyad", "Ad ve Soyad",
    "Adınız Soyadınız", "Adı", "Soyadı", "Baba Adı", "Ana Adı", "Anne Adı", "Eşinin Adı",
    "Kızlık Soyadı", "Önceki Soyadı",
    "ADI SOYADI", "ADI-SOYADI", "ADI VE SOYADI", "AD SOYAD", "AD-SOYAD", "AD VE SOYAD",
    "ADI", "SOYADI", "BABA ADI", "ANA ADI", "ANNE ADI", "EŞİNİN ADI", "KIZLIK SOYADI",
    "ÖNCEKİ SOYADI",
)
_FIELD_LABEL = (r"^[ \t]*(?:" + "|".join(re.escape(label) for label in
                                         sorted(_NAME_LABELS, key=len, reverse=True))
                + r")[ \t]*[:：][ \t]*")
# One to four words of letters (any case: official documents write names in capitals).
_FIELD_NAME = rf"[{_LETTERS}][{_LETTERS}'’.\-]*(?:[ \t]+[{_LETTERS}][{_LETTERS}'’.\-]*){{0,3}}"
_FIELD_END = r"(?=[ \t]*$)"  # the value is the rest of the line

# ------------------------------------------------------------------ address: official notation

_WORD = rf"[0-9{_UP}][0-9{_LETTERS}'’.\-]*"
_MARKER = (r"(?:MAH\.|Mah\.|MAHALLESİ|Mahallesi|CAD\.|Cad\.|CD\.|Cd\.|CADDESİ|Caddesi|"
           r"SK\.|Sk\.|SOK\.|Sok\.|SOKAK|Sokak|SOKAĞI|Sokağı|BLV\.|Blv\.|BULVARI|Bulvarı)")
_PART = rf"(?:{_WORD}[ \t]+){{1,4}}{_MARKER}"
# "NO: 123", "NO: 12/3" or the long form "DIŞ KAPI NO: 123".
_DOOR = (r"(?:(?:DIŞ KAPI|Dış Kapı)[ \t]+)?(?:NO|No)[ \t]*[:.]?[ \t]*\d+[A-Za-z]?"
         r"(?:/\d+[A-Za-z]?)?")
_UNIT = r"(?:İÇ KAPI NO|İç Kapı No|DAİRE|Daire|KAT|Kat|NO|No|D)[ \t]*[:.]?[ \t]*\d+[A-Za-z]?"
_PLACE = rf"[{_UP}][{_LETTERS}]+(?:[ \t]+[{_UP}][{_LETTERS}]+)?"
_CITY = rf"{_PLACE}[ \t]*/[ \t]*{_PLACE}"
# Door and unit are separated by white space or a slash: "NO: 123 / NO: 45" is the e-Devlet form.
_UNIT_SEP = r"(?:\s*/\s*|\s+)"
_ADDRESS = (rf"\b{_PART}(?:\s+{_PART}){{0,3}}\s+{_DOOR}(?:{_UNIT_SEP}{_UNIT}){{0,2}}"
            rf"(?:\s+{_CITY})?")


class _TrimmedPatternRecognizer(PatternRecognizer):
    """A pattern whose match begins with evidence (a label) that the span must not include:
    each result is re-matched with a named `value` group and its start moved there."""

    def __init__(self, *, split: re.Pattern[str], **kwargs) -> None:
        super().__init__(**kwargs)
        self._split = split

    def analyze(self, text, entities, nlp_artifacts=None, regex_flags=None):
        results = super().analyze(text, entities, nlp_artifacts, regex_flags)
        for result in results or []:
            m = self._split.match(text, result.start, result.end)
            if m and m.end() == result.end:
                result.start = m.start("value")
        return results


def person_field_recognizer() -> PatternRecognizer:
    """"Adı : AYŞE NUR" → only "AYŞE NUR" is a PERSON span. Entity TR_PERSON_CTX: a structural
    person, so the statistical-NER gates do not apply and the family is PERSON."""
    return _TrimmedPatternRecognizer(
        split=re.compile(rf"{_FIELD_LABEL}(?P<value>{_FIELD_NAME}){_FIELD_END}", _FLAGS),
        supported_entity="TR_PERSON_CTX", supported_language="tr",
        patterns=[Pattern("tr_person_field", _FIELD_LABEL + _FIELD_NAME + _FIELD_END, 0.6)],
        global_regex_flags=_FLAGS,
    )


def official_address_recognizer() -> PatternRecognizer:
    """"DENEME MAH. ÖRNEK SK. NO: 123 / NO: 45 ÖRNEKİLÇE / ÖRNEKİL" — marker plus door number.
    The unit may follow the door after a space, a line break or a slash; "DIŞ KAPI NO: 123
    İÇ KAPI NO: 45" is the long form of the same thing."""
    return PatternRecognizer(
        supported_entity="TR_ADDRESS", supported_language="tr",
        patterns=[Pattern("tr_address_official", _ADDRESS, 0.6)],
        context=["adres", "ikamet", "tebligat", "yerleşim"],
        global_regex_flags=_FLAGS,
    )

# Form field captions. A statistical NER hit that is nothing but one of these names no one
# ("Adı" tagged LOCATION, "Adres Tipi" tagged PERSON on the same e-Devlet page); the gate in
# gates.py drops it. Generic form vocabulary, compared case- and İ/ı-insensitively (term_key).
FORM_LABELS = (
    *_NAME_LABELS,
    "Adres", "Adresi", "Adres Tipi", "Adres Türü", "Adres No", "Yerleşim Yeri",
    "Yerleşim Yeri Adresi", "İkamet Adresi", "Tebligat Adresi", "Diğer Adres", "Doğum Yeri",
    "Doğum Tarihi", "Kimlik No", "T.C. Kimlik No", "Kimlik Bilgileri", "Uyruğu", "Cinsiyeti",
    "Medeni Hali", "Telefon", "E-posta", "İl", "İlçe", "Mahalle", "Belge No", "Tarih",
)

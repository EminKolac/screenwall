"""Orthographic gates for statistical NER output.

spaCy gives every prediction the same 0.85, so its score carries no evidence; these gates look at
the text itself. They run BEFORE resolve_spans so that a rejected guess cannot suppress a real
structural span through overlap.
"""
from __future__ import annotations

import re

from app.anonymization.lists import term_key
from app.anonymization.recognizers.turkish_fields import FORM_LABELS
from app.anonymization.spans import EntitySpan
from app.anonymization.types import ORTHO_GATED

# Detector sources that are Presidio passes (statistical NER lives there); other sources such as
# "deny" or a context recognizer are never gated.
_NER_SOURCES = ("en", "tr")


def lowercase_initial_ner(span: EntitySpan, text: str) -> bool:
    """A proper name never starts lowercase in Turkish or English orthography.

    Measured: `xx_ent_wiki_sm` tags ordinary Turkish phrases as PERSON ("hükümleri saklıdır",
    "mutabık kalınarak"). Only statistical NER types are gated; structural recognizers (IBAN,
    e-mail, secrets) may legitimately start lowercase. Only the first character is checked.
    """
    if span.entity_type not in ORTHO_GATED:
        return False
    surface = text[span.start:span.end].lstrip()
    if not surface:
        return False
    first = surface[0]
    return first.isalpha() and first.islower()


# Document-type and business-document head nouns, nominative / 3rd-person possessive / plural
# (the plural possessive is derived). A closed list written from general knowledge of Turkish and
# English office documents — deliberately NOT taken from any benchmark or evaluation file. No
# personal name contains one of these words, so a statistical PERSON span that does is a heading
# or a phrase ("Tedarik Sözleşmesi", "Faaliyet Raporu", "Supply Agreement"), not a person.
# Words that are also given names or surnames ("Bill", "Will") are left out on purpose.
_TR_DOC_NOUNS = (
    ("sözleşme", "sözleşmesi", "sözleşmeler"), ("protokol", "protokolü", "protokoller"),
    ("rapor", "raporu", "raporlar"), ("fatura", "faturası", "faturalar"),
    ("teklif", "teklifi", "teklifler"), ("tutanak", "tutanağı", "tutanaklar"),
    ("şartname", "şartnamesi", "şartnameler"), ("dilekçe", "dilekçesi", "dilekçeler"),
    ("yönetmelik", "yönetmeliği", "yönetmelikler"), ("yönerge", "yönergesi", "yönergeler"),
    ("genelge", "genelgesi", "genelgeler"), ("karar", "kararı", "kararlar"),
    ("ek", "eki", "ekler"), ("beyanname", "beyannamesi", "beyannameler"),
    ("makbuz", "makbuzu", "makbuzlar"), ("irsaliye", "irsaliyesi", "irsaliyeler"),
    ("taahhütname", "taahhütnamesi", "taahhütnameler"),
    ("vekaletname", "vekaletnamesi", "vekaletnameler"),
    ("vekâletname", "vekâletnamesi", "vekâletnameler"),
    ("ihtarname", "ihtarnamesi", "ihtarnameler"), ("belge", "belgesi", "belgeler"),
    ("mutabakat", "mutabakatı", "mutabakatlar"), ("talimat", "talimatı", "talimatlar"),
)
_EN_DOC_NOUNS = (
    "agreement", "agreements", "contract", "contracts", "report", "reports", "invoice",
    "invoices", "memorandum", "minutes", "proposal", "proposals", "certificate", "certificates",
    "protocol", "protocols", "receipt", "receipts", "regulation", "regulations", "addendum",
    "annex", "appendix", "amendment", "amendments",
)


def _plural_possessive(plural: str) -> str:
    return plural + ("ı" if plural.endswith("lar") else "i")


_DOC_NOUN_KEYS = frozenset(term_key(w) for w in (
    *(form for forms in _TR_DOC_NOUNS for form in (*forms, _plural_possessive(forms[2]))),
    *_EN_DOC_NOUNS,
))
_WORD_EDGE = ",;:()[]\"'’.!?«»“”"


def _word_key(word: str) -> str:
    """'Sözleşmesi'nin' -> 'sözleşmesi': edge punctuation and an apostrophe suffix removed."""
    word = word.strip(_WORD_EDGE)
    for apostrophe in ("'", "’"):
        word = word.split(apostrophe, 1)[0]
    return term_key(word)


def contains_document_noun(surface: str) -> bool:
    return any(_word_key(w) in _DOC_NOUN_KEYS for w in surface.split())


def implausible_person_ner(span: EntitySpan, text: str) -> bool:
    """PERSON-only rules for Presidio NER spans (EXPERIMENTS v5; rule 4 added in v0.1.2).

    3) A span of 3+ words that crosses a line break joins separate visual items
       ('Abone Kazanımı\\nMobilde'). A real name wrapped at a line end is two words and survives.
       LOCATION is deliberately excluded: the broad variant lost 2 critical addresses (measured).
    1) A single-word statistical PERSON is noise ("Konsolide", "Tahakkuk"); single surnames are
       covered by surname propagation and labelled names by TR_PERSON_CTX.
    2) A multi-word PERSON containing a lowercase word of 3+ letters is a sentence fragment.
    4) A PERSON containing a document-type noun ("Tedarik Sözleşmesi", "Faaliyet Raporu",
       "Supply Agreement") is a heading, not a name. Seen in the app on 2026-10-11: the English
       model took a title-case DOCX heading for a person. Names next to such a word are separate
       spans ("Sözleşmeyi imzalayan Ayşe Demir") and are not affected.
    """
    if span.source not in _NER_SOURCES:
        return False
    surface = text[span.start:span.end]
    words = surface.split()
    if span.entity_type != "PERSON":
        return False
    if "\n" in surface and len(words) >= 3:
        return True
    if len(words) == 1:
        return True
    if contains_document_noun(surface):
        return True
    return any(w[0].isalpha() and w[0].islower() for w in words if len(w) >= 3)


_DATE = re.compile(r"\d{1,2}[./-]\d{1,2}[./-]\d{2,4}")
_PHONE_TYPES = frozenset({"PHONE_NUMBER", "TR_PHONE", "TR_GSM", "UK_PHONE"})


def date_shaped_phone(span: EntitySpan, text: str) -> bool:
    """A dd.mm.yyyy date is not a phone number. Presidio's phone parser accepts dates such as
    "03.01.2026" and "02.02.2026" (seen on an e-Devlet document, 2026-09-25); a real number never
    has this shape."""
    if span.entity_type not in _PHONE_TYPES:
        return False
    return _DATE.fullmatch(text[span.start:span.end].strip()) is not None


_LABEL_KEYS = frozenset(term_key(label) for label in FORM_LABELS)


def form_label_ner(span: EntitySpan, text: str) -> bool:
    """A statistical NER hit that is only a form caption ("Adı", "Adres Tipi") names no one."""
    if span.source not in _NER_SOURCES or span.entity_type not in ORTHO_GATED:
        return False
    return term_key(text[span.start:span.end]) in _LABEL_KEYS


def caps_line_ner(span: EntitySpan, text: str) -> bool:
    """In a line written in capitals, capitalisation carries no name signal and statistical NER
    turns into noise ("YERİ", "OLUP", "FIKRASI" on an e-Devlet page, 2026-09-25). Names in such
    documents come from labelled fields and propagate to the capitals from there. Structural
    recognizers (addresses, IDs) share the Presidio source, so only NER types are gated."""
    if span.source not in _NER_SOURCES or span.entity_type not in ORTHO_GATED:
        return False
    start = text.rfind("\n", 0, span.start) + 1
    end = text.find("\n", span.end)
    line = text[start:end if end != -1 else len(text)]
    # Words only: URLs, e-mails, dates and codes ("www.turkiye.gov.tr", "03.01.2026") say nothing
    # about how the sentence is capitalised.
    words = [w.strip(",;:()\"'’") for w in line.split()]
    words = [w for w in words if w.isalpha()]
    return len(words) >= 4 and sum(w.isupper() for w in words) >= 0.8 * len(words)

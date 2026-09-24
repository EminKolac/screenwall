"""Orthographic gates for statistical NER output.

spaCy gives every prediction the same 0.85, so its score carries no evidence; these gates look at
the text itself. They run BEFORE resolve_spans so that a rejected guess cannot suppress a real
structural span through overlap.
"""
from __future__ import annotations

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


def implausible_person_ner(span: EntitySpan, text: str) -> bool:
    """PERSON-only rules for Presidio NER spans (EXPERIMENTS v5).

    3) A span of 3+ words that crosses a line break joins separate visual items
       ('Abone Kazanımı\\nMobilde'). A real name wrapped at a line end is two words and survives.
       LOCATION is deliberately excluded: the broad variant lost 2 critical addresses (measured).
    1) A single-word statistical PERSON is noise ("Konsolide", "Tahakkuk"); single surnames are
       covered by surname propagation and labelled names by TR_PERSON_CTX.
    2) A multi-word PERSON containing a lowercase word of 3+ letters is a sentence fragment.
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
    return any(w[0].isalpha() and w[0].islower() for w in words if len(w) >= 3)

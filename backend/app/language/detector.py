"""Language detection (TR / EN / mixed).

Default backend is langdetect with a fixed seed for determinism. Mixed detection is block-aware:
a document is `mixed` if different blocks resolve to different languages, or a single block is
itself detected as multilingual. Per-block language is written back onto each `Block` so the
Phase-3 anonymization engine can route recognizers per block.
"""
from __future__ import annotations

from langdetect import DetectorFactory, detect_langs
from langdetect.lang_detect_exception import LangDetectException

from app.extraction.base import ExtractedContent
from app.models.document import Language

DetectorFactory.seed = 0
_MIN_CHARS = 12
_MIXED_PROB = 0.25


def _block_text(block) -> str:
    if block.text:
        return block.text
    return " ".join(c.text for c in block.cells)


def detect_language(text: str) -> Language:
    text = (text or "").strip()
    if len(text) < _MIN_CHARS:
        return Language.unknown
    try:
        langs = detect_langs(text)
    except LangDetectException:
        return Language.unknown
    probs = {l.lang: l.prob for l in langs}
    tr, en = probs.get("tr", 0.0), probs.get("en", 0.0)
    if tr >= _MIXED_PROB and en >= _MIXED_PROB:
        return Language.mixed
    top = max(probs, key=probs.get)
    if top == "tr":
        return Language.tr
    if top == "en":
        return Language.en
    return Language.unknown


def detect_content_language(content: ExtractedContent) -> Language:
    """Resolve the overall language and annotate each block with its own language."""
    tr_blocks = en_blocks = 0
    any_mixed = False
    for block in content.blocks:
        lang = detect_language(_block_text(block))
        block.language = lang  # persist tr/en/mixed/unknown — Phase 3 routes mixed/unknown to both
        if lang == Language.tr:
            tr_blocks += 1
        elif lang == Language.en:
            en_blocks += 1
        elif lang == Language.mixed:
            any_mixed = True
    if any_mixed or (tr_blocks and en_blocks):
        return Language.mixed
    if tr_blocks:
        return Language.tr
    if en_blocks:
        return Language.en
    return detect_language(content.plain_text)

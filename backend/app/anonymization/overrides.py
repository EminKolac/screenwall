"""Human review decisions for one document, applied on top of detection (engine Overrides).

Ranges are in ORIGINAL unit coordinates (unit ids as in AnonymizationOutput.edits). Most specific
first:

  mask_ranges  "mask this occurrence": forced before detection, always applied.
  keep_ranges  "leave this occurrence unmasked": beats detection and a document-wide mask.
  mask_terms   "mask this term in the whole document": forced before detection, so no allow or
               keep TERM can drop it; only a keep RANGE exempts one occurrence.
  keep_terms   "never mask this term here": a never-mask term for this document.

Keep ranges and terms suppress only what lies fully INSIDE them (containment, see lists.py). With
no overrides the engine behaves exactly as without them (parity-tested).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.anonymization.lists import contained, term_ranges
from app.anonymization.placeholders import PlaceholderMapper
from app.anonymization.spans import EditBuffer
from app.anonymization.types import user_type


@dataclass
class Overrides:
    keep_ranges: dict[str, list[tuple[int, int]]] = field(default_factory=dict)
    mask_ranges: dict[str, list[tuple[int, int, str]]] = field(default_factory=dict)  # family
    keep_terms: list[str] = field(default_factory=list)  # document-wide never-mask
    mask_terms: dict[str, str] = field(default_factory=dict)  # document-wide term -> family


def apply_forced(buf: EditBuffer, ov: Overrides, uid: str, mapper: PlaceholderMapper) -> int:
    """Land the reviewer's masks in `buf` before detection, like a pre-mask: occurrence masks and
    every occurrence of a document-wide term that is not inside a keep range. Overlapping masks
    (and a table pre-mask they touch) become ONE mask over their union, with the family of the
    longest — a later, wider mask is never dropped. Returns how many masks were applied."""
    keep = ov.keep_ranges.get(uid, [])
    wanted = [(s, e, fam) for s, e, fam in ov.mask_ranges.get(uid, [])
              if 0 <= s < e <= len(buf.original)]
    for term, fam in ov.mask_terms.items():
        wanted += [(s, e, fam) for s, e in term_ranges(buf.original, [term])
                   if not contained(s, e, keep)]
    merged = _merged(wanted)
    for start, end, fam in merged:
        start, end = buf.union_range(start, end)
        token = mapper.placeholder_for(fam, buf.original[start:end])
        buf.force_original(start, end, token, user_type(fam), "user")
    return len(merged)


def _merged(wanted: list[tuple[int, int, str]]) -> list[tuple[int, int, str]]:
    """Overlapping ranges joined; each union keeps the family of its longest member."""
    groups: list[list[tuple[int, int, str]]] = []
    for s, e, fam in sorted(wanted, key=lambda w: (w[0], -w[1])):
        if groups and s < max(w[1] for w in groups[-1]):
            groups[-1].append((s, e, fam))
        else:
            groups.append([(s, e, fam)])
    out = []
    for group in groups:
        longest = max(group, key=lambda w: w[1] - w[0])
        out.append((min(w[0] for w in group), max(w[1] for w in group), longest[2]))
    return out


def keep_in_current(buf: EditBuffer, ranges: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Keep ranges mapped onto the unit's CURRENT text (a range already replaced drops out)."""
    mapped = (buf.current_range(s, e) for s, e in ranges)
    return [r for r in mapped if r is not None]

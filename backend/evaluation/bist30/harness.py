"""Canary placement + ground-truth evaluation for the BIST-30 benchmark.

Each canary is placed in a carrier next to a unique NON-PII locator marker ("Ref0007") so we can
find its region in both the original-extracted and the anonymized text and see exactly what token
replaced it — without ever relying on fragile line offsets. The value's presence is checked
whitespace-insensitively so line-broken / extra-space variants are handled.

A placement is graded on the pipeline invariants the task enumerates and its failure (if any) is
pinned to a concrete stage:

  S3  channel not extracted            (value never entered the pipeline; a detection blind spot)
  S4  OCR page not extracted           (image page: OCR missing / low quality)
  S6  no base recognizer               (base Presidio structurally can't detect it → needs stage ②)
  S8  detected-but-not-masked          (threshold/overlap dropped an extracted, detectable value)
  S9  wrong placeholder family         (masked, but with the wrong <TYPE_> family)
  S14 export residual                  (masked in layer-3 yet reappears in the export) ← blocker
  ok  extracted → masked → correct family → absent from export
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from evaluation.bist30.canary import Canary, value_hash
from evaluation.score import overlaps

_WS = re.compile(r"\s+")
_TOKEN = re.compile(r"<([A-Z]+)_\d+>")


def norm(s: str) -> str:
    """Collapse all whitespace so line-broken / multi-space variants compare equal."""
    return _WS.sub(" ", s or "").strip()


class Markers:
    """Allocates unique, non-PII locator markers ('Ref0001', 'Ref0002', …)."""

    def __init__(self, start: int = 1) -> None:
        self._n = start

    def next(self) -> str:
        # Lowercase gibberish so the multilingual NER does not tag the marker itself as an entity
        # (a capitalized "Ref0008" gets swept into a PERSON/NRP span, eating the locator).
        m = f"anc{self._n:04d}x"
        self._n += 1
        return m


@dataclass
class Placement:
    marker: str            # unique locator, e.g. "Ref0007"
    canary_id: str
    fmt: str               # docx / xlsx / pdf
    channel: str           # body/table/header/footer/comment/hidden_sheet/merged/ocr/filename
    variant: str           # "" | line_break | case_space
    expected_family: str
    critical: bool
    base_detectable: bool
    value: str             # SYNTHETIC PII — runtime only; never written to reports

    @property
    def vhash(self) -> str:
        return value_hash(self.value)

    def carrier_text(self) -> str:
        """The text an injector writes into a text channel: '<marker> <value>'."""
        return f"{self.marker} {self.value}"

    def safe_dict(self) -> dict:
        """Report-safe view — NO raw value."""
        return {
            "marker": self.marker, "canary_id": self.canary_id, "fmt": self.fmt,
            "channel": self.channel, "variant": self.variant,
            "expected_family": self.expected_family, "critical": self.critical,
            "base_detectable": self.base_detectable, "vhash": self.vhash,
        }


@dataclass
class PlacementResult:
    marker: str
    canary_id: str
    fmt: str
    channel: str
    variant: str
    expected_family: str
    critical: bool
    base_detectable: bool
    vhash: str
    extracted: bool
    detected: bool        # some detection span overlapped the value's original position
    masked: bool          # value absent from the anonymized layer-3 text (recall; deterministic)
    family_ok: bool
    found_family: str
    residual_in_export: bool  # value survived into the exported file (the authoritative LEAK)
    token: str            # placeholder family/families observed at the value (or "")
    stage: str            # "ok" or an S* failure stage

    def safe_dict(self) -> dict:
        d = self.__dict__.copy()
        return d  # already value-free (only vhash/token/family)


def make_placement(mk: Markers, c: Canary, fmt: str, channel: str, variant: str = "") -> Placement:
    value = c.value
    if variant == "line_break":
        value = _inject_linebreak(value)
    elif variant == "case_space":
        value = _case_space(value)
    return Placement(mk.next(), c.cid, fmt, channel, variant, c.expected_family,
                     c.critical, c.base_detectable, value)


def _inject_linebreak(value: str) -> str:
    """Split the value across a newline at its first space (a line-wrapped PII)."""
    if " " in value:
        i = value.index(" ")
        return value[:i] + "\n" + value[i + 1:]
    mid = len(value) // 2
    return value[:mid] + "\n" + value[mid:]


def _case_space(value: str) -> str:
    """Upper-case letters and double the internal spaces (case/space robustness)."""
    return _WS.sub("  ", value.upper())


def _window(text: str, marker: str, width: int = 120) -> str | None:
    """Text immediately after the marker (spanning any newlines), or None if marker absent."""
    i = text.find(marker)
    if i < 0:
        return None
    j = i + len(marker)
    return text[j:j + width]


def evaluate(
    placement: Placement, original_text: str, detected_spans, anon_text: str,
    export_text: str | None,
) -> PlacementResult:
    """Grade one placement.

    Robust against the noisy multilingual NER (which masks the locator marker itself) by anchoring
    on the ORIGINAL extracted text — where the marker always survives — and judging masking by the
    value's GLOBAL absence from the anonymized/exported text (placeholder mapping is deterministic,
    so a value masked once is masked everywhere; a value that survives anywhere is a leak).

      extracted  : marker present in original + value adjacent
      detected   : a resolved detection span overlaps the value's original position
      masked     : value absent from the anonymized layer-3 text          (recall)
      residual   : value present in the exported file                     (the authoritative LEAK)
      family     : placeholder family/families produced at the value      (approx, from detection)
    """
    from app.anonymization.presidio_engine import _ph_type  # local import avoids a cycle

    val_n = norm(placement.value)
    win = _window(original_text, placement.marker, 180)
    extracted = win is not None and val_n in norm(win)

    # Family + detected: locate the value in the original text and see which spans cover it.
    families: set[str] = set()
    mi = original_text.find(placement.marker)
    if mi >= 0:
        vi = original_text.find(placement.value, mi)
        if vi < 0:  # whitespace/case drift — approximate the region right after the marker
            vi = mi + len(placement.marker)
            ve = vi + len(placement.value) + 4
        else:
            ve = vi + len(placement.value)
        families = {_ph_type(s.entity_type) for s in detected_spans
                    if overlaps(vi, ve, s.start, s.end)}
    detected = bool(families)
    found_family = "+".join(sorted(families))

    masked = extracted and (val_n not in norm(anon_text))
    residual = export_text is not None and val_n in norm(export_text)
    family_ok = masked and families == {placement.expected_family}

    stage = _classify(placement, extracted, detected, masked, family_ok, residual)
    return PlacementResult(
        marker=placement.marker, canary_id=placement.canary_id, fmt=placement.fmt,
        channel=placement.channel, variant=placement.variant,
        expected_family=placement.expected_family, critical=placement.critical,
        base_detectable=placement.base_detectable, vhash=placement.vhash,
        extracted=extracted, detected=detected, masked=masked, family_ok=family_ok,
        found_family=found_family, residual_in_export=residual, token=found_family, stage=stage,
    )


def _classify(p: Placement, extracted: bool, detected: bool, masked: bool,
              family_ok: bool, residual: bool) -> str:
    if not extracted:
        return "S4_ocr_not_extracted" if p.channel == "ocr" else f"S3_not_extracted:{p.channel}"
    if residual:  # the value reached the exported file — a real leak; classify WHY
        if not detected:
            return "S6_no_base_recognizer" if not p.base_detectable else "S8_detected_not_masked"
        return "S10_partial_or_overlap_lost"   # detected yet leaked (partial / overlap-dropped)
    if not masked:
        if not detected:
            return "S6_no_base_recognizer" if not p.base_detectable else "S8_detected_not_masked"
        return "S10_partial_or_overlap_lost"
    if not family_ok:
        # Masked but the family is wrong ONLY when a family was actually attributed; when the
        # whole-text probe attributes none (it detects per-doc, the pipeline per-block) we cannot
        # claim a wrong family — the value IS masked, so report family-unverified, not a fault.
        return "S9_wrong_family" if detected else "ok_family_unverified"
    return "ok"

"""What a decision points at: a masked span, an audit finding or a new text selection.

Targets are validated with pydantic — strict int offsets, a family that matches as a whole — so
malformed input is a 422 invalid_decision, never a 500. Span and item ids are positional within
one revision; the caller refuses a stale client (expected_revision) before resolving them.
"""
from __future__ import annotations

from dataclasses import dataclass, replace

from pydantic import BaseModel, Field, StrictInt, ValidationError

from app.anonymization.types import valid_family
from app.models.document import Document
from app.review.errors import DecisionError, invalid
from app.review.payload import ReviewUnavailable, review_parts
from app.services.repository import DocumentRepository

_MAX_VALUE = 200


class _SpanRef(BaseModel):
    span_id: str = Field(min_length=1, max_length=256)


class _ItemRef(BaseModel):
    item_id: str = Field(min_length=1, max_length=256)


class _Selection(BaseModel):
    unit_id: str = Field(min_length=1, max_length=256)
    start: StrictInt = Field(ge=0)
    end: StrictInt = Field(ge=0)
    family: str = Field(max_length=32)


@dataclass(frozen=True)
class Target:
    unit_id: str
    start: int  # ORIGINAL unit offsets
    end: int
    family: str
    value: str  # the original text there, whitespace-collapsed
    state: str  # a span's state (masked | added | kept), "item" or "selection"
    split: bool = False  # a fragment of a value split across table cells (not a term)


def parse_target(raw: object) -> _SpanRef | _ItemRef | _Selection:
    if not isinstance(raw, dict):
        raise invalid()
    model = _SpanRef if "span_id" in raw else _ItemRef if "item_id" in raw else _Selection
    try:
        ref = model.model_validate(raw)
    except ValidationError as e:
        raise invalid() from e
    if isinstance(ref, _Selection) and not valid_family(ref.family):
        raise invalid()
    return ref


def resolve_target(doc: Document, repo: DocumentRepository, raw: object) -> Target:
    ref = parse_target(raw)
    try:
        units_list, spans, items = review_parts(doc, repo)
    except ReviewUnavailable as e:  # e.g. a document without text: nothing masked to decide on
        raise DecisionError("no_content") from e
    units = {u["id"]: u for u in units_list}
    if isinstance(ref, _SpanRef):
        s = next((s for s in spans if s["id"] == ref.span_id), None)
        if s is None:
            raise invalid()
        t = _target(units, s["unit_id"], s["start"], s["end"], s["family"], s["state"])
        return replace(t, split="adjacency" in s["evidence"])
    if isinstance(ref, _ItemRef):
        i = next((i for i in items if i["id"] == ref.item_id), None)
        if i is None:
            raise invalid()
        return _target(units, i["unit_id"], i["start"], i["end"], i["family"] or "SENSITIVE",
                       "item")
    return _target(units, ref.unit_id, ref.start, ref.end, ref.family, "selection")


def _target(units: dict, uid: str, start: int, end: int, fam: str, state: str) -> Target:
    unit = units.get(uid)
    if unit is None or unit["original"] is None:
        raise invalid()
    if not 0 <= start < end <= len(unit["original"]):
        raise invalid()
    value = " ".join(unit["original"][start:end].split())
    if not value or len(value) > _MAX_VALUE:
        raise invalid()
    return Target(uid, start, end, fam, value, state)

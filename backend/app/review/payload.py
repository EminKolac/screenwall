"""Build the review screen's data (frontend/src/api/contract.ts: DocumentSummary, ReviewPayload).

Spans come straight from the engine's edit list — no text diffing. Original text is included only
in mapping mode; in destructive mode the review works on the masked text alone.
"""
from __future__ import annotations

from app.anonymization.engine import iter_units
from app.anonymization.lists import term_ranges
from app.anonymization.spans import MaskEdit
from app.anonymization.types import USER_PREFIX, family
from app.models.document import Document, DocumentStatus
from app.review import reasons as R
from app.review.findings import masked_to_original, original_to_masked
from app.services.repository import DocumentRepository


class ReviewUnavailable(Exception):
    """No masked content exists (yet) for this document."""


def document_summary(doc: Document) -> dict:
    in_review = doc.status == DocumentStatus.NEEDS_HUMAN_REVIEW
    approved = doc.status == DocumentStatus.APPROVED
    reasons = [r.model_dump() for r in doc.reasons] or [
        {"code": "review", "text": t} for t in doc.review_reason]
    return {
        "id": doc.id,
        "filename": doc.filename,
        "kind": doc.kind.value,
        "mode": doc.mode,
        "language": doc.language.value,
        "status": doc.status.api_value,
        "created_at": doc.created_at.isoformat(),
        "updated_at": doc.updated_at.isoformat(),
        "pages": doc.page_count,
        "counts": {"masked": doc.masked_count, "pending": doc.pending_count},
        "reasons": reasons,
        "can": {
            "review": in_review or approved,
            "approve": in_review and doc.pending_count == 0,
            "download": approved,
            "chat": approved,
            "decide": (in_review or approved) and doc.mode == "mapping",
        },
    }


def load_edits(repo: DocumentRepository, doc_id: str) -> dict[str, list[MaskEdit]]:
    return {uid: [MaskEdit(**e) for e in lst] for uid, lst in repo.get_edits(doc_id).items()}


def build_review(doc: Document, repo: DocumentRepository) -> dict:
    anon = repo.get_anonymized(doc.id)
    if anon is None:
        raise ReviewUnavailable
    original = repo.get_extracted(doc.id) if doc.mode == "mapping" else None
    originals = ({uid: text for uid, _b, _c, text in iter_units(original)} if original else {})
    edits = load_edits(repo, doc.id)
    decisions = repo.get_decisions(doc.id) if original else {}
    units = [_unit(uid, block, cell, masked, originals, original is not None)
             for uid, block, cell, masked in iter_units(anon)]
    spans = _mask_spans(edits) + _kept_spans(units, edits, decisions)
    items = _finding_items(repo.get_findings(doc.id), units, edits)
    return {
        "document": document_summary(doc),
        "units": units,
        "spans": spans,
        "items": items,
        "pages": page_infos(doc, repo),
    }


def _unit(uid: str, block, cell, masked: str, originals: dict[str, str], has_original: bool
          ) -> dict:
    location = R.location_label(block.location)
    if cell is not None:
        location += f" · {cell.address}" if cell.address else f" · {cell.row + 1}. satır"
    return {
        "id": uid,
        "block_id": block.block_id,
        "kind": "cell" if cell is not None else block.type.value,
        "page": block.page,
        "location": location,
        "table": ({"id": block.block_id, "row": cell.row, "col": cell.col}
                  if cell is not None else None),
        "original": originals.get(uid) if has_original else None,
        "masked": masked,
    }


def _mask_spans(edits: dict[str, list[MaskEdit]]) -> list[dict]:
    spans: list[dict] = []
    for uid, lst in edits.items():
        for i, e in enumerate(lst):
            user = e.source == "user" or e.entity_type.startswith(USER_PREFIX)
            spans.append({
                "id": f"{uid}~{i}",
                "unit_id": uid,
                "start": e.start, "end": e.end,
                "masked_start": e.masked_start, "masked_end": e.masked_end,
                "family": family(e.entity_type),
                "placeholder": e.text,
                "evidence": R.evidence(e.entity_type, e.source),
                "reason": R.reason(e.entity_type, e.source),
                "state": "added" if user else "masked",
            })
    return spans


def _kept_spans(units: list[dict], edits: dict[str, list[MaskEdit]], decisions: dict
                ) -> list[dict]:
    """Occurrences a reviewer chose to leave unmasked (this occurrence or the whole document)."""
    ranges: dict[str, set[tuple[int, int]]] = {}
    for uid, lst in (decisions.get("keep_ranges") or {}).items():
        ranges.setdefault(uid, set()).update((int(s), int(e)) for s, e in lst)
    terms = decisions.get("keep_terms") or []
    if terms:
        for u in units:
            if u["original"]:
                ranges.setdefault(u["id"], set()).update(term_ranges(u["original"], terms))
    spans: list[dict] = []
    for uid, found in ranges.items():
        unit_edits = edits.get(uid, [])
        for n, (s, e) in enumerate(sorted(found)):
            if any(x.start < e and s < x.end for x in unit_edits):
                continue  # masked after all (e.g. by a global list); not shown as kept
            ms, me = original_to_masked(unit_edits, s), original_to_masked(unit_edits, e)
            spans.append({
                "id": f"{uid}~k{n}", "unit_id": uid, "start": s, "end": e,
                "masked_start": ms, "masked_end": me, "family": "SENSITIVE",
                "placeholder": "", "evidence": ["user:keep"],
                "reason": "Sizin kararınız: açık bırakıldı", "state": "kept",
            })
    return spans


def _finding_items(findings: list[dict], units: list[dict], edits: dict[str, list[MaskEdit]]
                   ) -> list[dict]:
    masked_by_id = {u["id"]: u["masked"] for u in units}
    counts: dict[str, int] = {}
    for f in findings:
        text = masked_by_id.get(f["unit_id"], "")[f["masked_start"]:f["masked_end"]].casefold()
        counts[text] = counts.get(text, 0) + 1
    items: list[dict] = []
    for f in findings:
        uid = f["unit_id"]
        if uid not in masked_by_id:
            continue
        unit_edits = edits.get(uid, [])
        ms, me = f["masked_start"], f["masked_end"]
        text = masked_by_id[uid][ms:me].casefold()
        items.append({
            "id": f["id"], "kind": "finding", "unit_id": uid,
            "start": masked_to_original(unit_edits, ms), "end": masked_to_original(unit_edits, me),
            "masked_start": ms, "masked_end": me, "family": None,
            "reason": R.FINDING_REASON, "occurrences": counts.get(text, 1),
            "status": f.get("status", "open"),
        })
    return items


def page_infos(doc: Document, repo: DocumentRepository) -> list[dict]:
    if doc.kind.value != "pdf" or doc.mode != "mapping":
        return []
    data = repo.get_original(doc.id)
    if data is None:
        return []
    try:
        import fitz  # PyMuPDF

        with fitz.open(stream=data, filetype="pdf") as pdf:
            return [{"index": i + 1, "width": round(p.rect.width, 2),
                     "height": round(p.rect.height, 2)} for i, p in enumerate(pdf)]
    except Exception:  # noqa: BLE001 — the text view still works without page images
        return []

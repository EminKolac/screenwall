"""Human-review API — pending queue + approve / reject / manual redaction.

Codex review: approval re-audits the current anonymized artifact (recorded as an iteration) before
building the layer-5 chat context; manual redaction invalidates any existing chat context and
de-approves until a clean re-approval.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.anonymization.allowlist_tr import default_allow_list
from app.anonymization.presidio_engine import PresidioEngine
from app.audit.factory import build_auditor
from app.config import get_settings
from app.models.document import DocumentStatus, IterationRecord
from app.pipeline.runner import build_chat_context
from app.services.deps import get_repository

router = APIRouter(prefix="/api/review", tags=["review"])


class RedactionRequest(BaseModel):
    terms: list[str]


class UnmaskRequest(BaseModel):
    """Faz 3 — insan düzeltmesi: TEK bir yer tutucunun geri alınması."""
    token: str


def _effective_terms(doc, extra_deny: list[str] | None = None) -> tuple[list[str], list[str]]:
    """`runner.run_pipeline` ile AYNI deny/allow bileşimi (+ belgeye özgü insan düzeltmeleri).

    Ayrı bir yardımcıya alındı çünkü ikisinin ayrışması sessiz ve tehlikeliydi: `redact` daha önce
    YALNIZ çağrıdan gelen terimleri geçiyordu; bu (a) proje deny-list'ini düşürüyordu — yani "daha
    fazla karart" isteyen bir işlem, global deny-list'teki terimlerin maskesini KALDIRABİLİYORDU —
    ve (b) allow-list'i tamamen düşürerek aşırı-maskelemeyi geri getiriyordu.
    """
    settings = get_settings()
    deny = settings.deny_list() + list(extra_deny or [])
    allow = default_allow_list() + settings.allow_list() + list(doc.allow_terms)
    return deny, allow


def _reanonymize(repo, doc, extracted, *, extra_deny: list[str] | None = None) -> int:
    """Belgeyi güncel deny/allow bileşimiyle yeniden anonimleştirir, iterasyon kaydı düşer ve
    insan onayını sıfırlar. `redact` ve `unmask` AYNI yolu kullanır ki ikisi ayrışmasın."""
    deny, allow = _effective_terms(doc, extra_deny)
    out = PresidioEngine().anonymize(
        extracted, doc.language, extra_deny_terms=deny, extra_allow_terms=allow)
    repo.save_anonymized(doc.id, out.content)
    repo.save_mapping(doc.id, out.mapping)
    # Manuel müdahale de denetim izine girer — `approve` bunu yapıyordu, `redact` yapmıyordu ve
    # elle karartma denetim kaydında hiç görünmüyordu.
    doc.iterations.append(IterationRecord(
        iteration=len(doc.iterations) + 1,
        presidio_entities=out.entity_count,
        placeholders_used=out.placeholders_used,
        by_source=out.by_source,
    ))
    # Önceki sohbet bağlamını geçersiz kıl ve yeniden onay iste.
    repo.save_chat_context(doc.id, "")
    doc.transition(DocumentStatus.NEEDS_HUMAN_REVIEW)
    repo.save_document(doc)
    return out.entity_count


@router.get("/pending")
def pending() -> dict:
    repo = get_repository()
    return {
        "documents": [
            {"id": d.id, "filename": d.filename, "language": d.language.value,
             "status": d.status.value, "iterations": len(d.iterations)}
            for d in repo.list_documents()
            if d.status == DocumentStatus.NEEDS_HUMAN_REVIEW
        ]
    }


@router.post("/{doc_id}/approve")
def approve(doc_id: str) -> dict:
    repo = get_repository()
    doc = repo.get_document(doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="document not found")
    anon = repo.get_anonymized(doc_id)
    audit = None
    if anon is not None:  # re-audit the artifact being approved (transparency trail)
        audit = build_auditor(get_settings()).audit(anon.plain_text)
        doc.iterations.append(IterationRecord(iteration=len(doc.iterations) + 1, audit=audit))
    doc.transition(DocumentStatus.APPROVED)
    build_chat_context(repo, doc_id)  # anonymized → layer 5 only
    repo.save_document(doc)
    return {
        "id": doc.id, "status": doc.status.value, "chat_enabled": doc.chat_enabled,
        "reaudit_clean": (audit.approved if audit else None),
    }


@router.post("/{doc_id}/reject")
def reject(doc_id: str) -> dict:
    repo = get_repository()
    doc = repo.get_document(doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="document not found")
    doc.transition(DocumentStatus.NEEDS_HUMAN_REVIEW)
    repo.save_document(doc)
    return {"id": doc.id, "status": doc.status.value}


@router.post("/{doc_id}/redact")
def redact(doc_id: str, body: RedactionRequest) -> dict:
    repo = get_repository()
    doc = repo.get_document(doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="document not found")
    extracted = repo.get_extracted(doc_id)
    if extracted is None:
        if doc.mode == "destructive":
            # By design: destructive mode never persists layer 2, so a missed entity cannot be
            # corrected in place — the trade-off documented in Settings.anonymization_mode.
            raise HTTPException(
                status_code=409,
                detail="manual redaction is unavailable in destructive mode (original content "
                       "was never persisted) — re-upload the document to try again",
            )
        raise HTTPException(status_code=404, detail="extracted content not found")
    _reanonymize(repo, doc, extracted, extra_deny=body.terms)
    return {"id": doc.id, "status": doc.status.value, "applied_terms": len(body.terms)}


@router.post("/{doc_id}/unmask")
def unmask(doc_id: str, body: UnmaskRequest) -> dict:
    """Faz 3 — insan düzeltmesi: yanlış maskelenmiş TEK bir yer tutucuyu geri al.

    Güvenlik sözleşmesi:
    - Eşleme tablosunun TAMAMI asla dönmez; yalnız istenen tek token'ın değeri çözülür ve o değer
      belgenin allow-list'ine eklenerek belge yeniden anonimleştirilir. Yanıt ham değeri İÇERMEZ —
      düzeltmenin doğruluğu yeni anonim metinden görülür (dönseydi, uç bir "eşleme tablosunu tek
      tek sızdır" saldırısına dönüşürdü).
    - `destructive` modda 409: eşleme yok, geri alma fiziksel olarak mümkün değil.
    """
    repo = get_repository()
    doc = repo.get_document(doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="document not found")
    token = body.token.strip()
    if not token:
        raise HTTPException(status_code=400, detail="token is required")

    extracted = repo.get_extracted(doc_id)
    mapping = repo.get_mapping(doc_id)
    if extracted is None or mapping is None:
        if doc.mode == "destructive":
            raise HTTPException(
                status_code=409,
                detail="un-masking is unavailable in destructive mode (the mapping was never "
                       "persisted) — re-upload the document to try again",
            )
        raise HTTPException(status_code=404, detail="extracted content or mapping not found")

    value = mapping.get(token)
    if value is None:
        raise HTTPException(status_code=404, detail="token not found in this document")
    if value in doc.allow_terms:
        raise HTTPException(status_code=409, detail="token already un-masked")

    doc.allow_terms.append(value)
    _reanonymize(repo, doc, extracted)
    return {"id": doc.id, "status": doc.status.value, "token": token,
            "unmasked_total": len(doc.allow_terms)}

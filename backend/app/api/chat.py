"""Chat API — enabled ONLY for approved documents, over anonymized content only.

The hard gate lives in `ChatService` (approval + layer-5-only). This router just resolves the
document and maps errors. No external call happens for a non-approved document.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.chat.base import ChatNotAllowed
from app.chat.factory import build_chat_service
from app.config import get_settings
from app.services.deps import get_repository

router = APIRouter(prefix="/api/chat", tags=["chat"])


class ChatRequest(BaseModel):
    messages: list[dict]


@router.post("/{doc_id}")
def chat(doc_id: str, body: ChatRequest) -> dict:
    doc = get_repository().get_document(doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="document not found")
    service = build_chat_service(get_settings())
    try:
        answer = service.chat(doc, body.messages)
    except ChatNotAllowed as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except Exception as e:  # noqa: BLE001 — never leak provider internals
        raise HTTPException(
            status_code=502,
            detail=(
                f"chat provider unavailable ({type(e).__name__}). "
                "Enable a local model — run scripts/setup_macos.sh for Ollama — "
                "or set CHAT_PROVIDER + an API key in .env."
            ),
        ) from e
    return {"answer": answer}

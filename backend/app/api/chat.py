"""Chat API — enabled ONLY for approved documents, over anonymized content only.

The hard gates live in `ChatService` (approval + layer-5-only + redaction, and consent for cloud
providers). This router resolves documents/providers and maps errors to the contract
(frontend/src/api/contract.ts, "chat"):

  GET  /api/chat/providers   -> ProvidersResponse
  POST /api/chat/preview     -> ChatPreviewResponse  (no provider call)
  POST /api/chat             -> ChatResponse         (cloud: matching preview_hash required)
  POST /api/chat/{doc_id}    -> {"answer"}           (legacy single-document local chat)

Errors are {"detail": <ErrorCode>} only — never CLI stderr, provider text or exception messages.
No external call happens for a non-approved document.
"""
from __future__ import annotations

import logging
import re
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import TypeVar

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.chat import factory
from app.chat.base import ChatError, ChatNotAllowed
from app.chat.cli import CliError
from app.chat.schemas import (
    ChatPreviewRequest,
    ChatPreviewResponse,
    ChatRequest,
    ChatResponse,
    ProvidersResponse,
)
from app.config import get_settings
from app.models.document import Document
from app.services.deps import get_repository
from app.services.user_settings import load_user_settings
from app.storage.base import StorageAccessError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/chat", tags=["chat"])

T = TypeVar("T")

_DOC_ID = re.compile(r"[A-Za-z0-9_-]{1,128}")  # ids become storage paths: no "../"
_HTTP_STATUS = {
    "document_not_found": 404,
    "chat_not_allowed": 403,
    "preview_required": 409,
    "preview_mismatch": 409,
    "provider_unavailable": 503,
    "ollama_unreachable": 503,
    "model_missing": 503,
    "cli_not_found": 503,
    "cli_upgrade_required": 503,
    "cli_login_required": 503,
    "cli_timeout": 502,
    "cli_output_limit": 502,
    "cli_failed": 502,
    "cli_unsafe_output": 502,
    "invalid_citations": 502,
    "internal_error": 500,
}


def _error(code: str) -> HTTPException:
    if code not in _HTTP_STATUS:
        code = "internal_error"
    return HTTPException(status_code=_HTTP_STATUS[code], detail=code)


def _guarded(call: Callable[[], T]) -> T:
    """Run a chat operation; only fixed ErrorCodes leave, never exception text."""
    try:
        return call()
    except HTTPException:
        raise
    except (ChatNotAllowed, StorageAccessError):
        raise _error("chat_not_allowed") from None
    except (ChatError, CliError) as e:
        raise _error(e.code) from None
    except Exception as e:  # noqa: BLE001
        logger.warning("chat request failed (%s)", type(e).__name__)
        raise _error("internal_error") from None


def _documents(doc_ids: list[str]) -> list[Document]:
    repo = get_repository()
    docs = []
    for doc_id in dict.fromkeys(doc_ids):
        doc = repo.get_document(doc_id) if _DOC_ID.fullmatch(doc_id) else None
        if doc is None:
            raise _error("document_not_found")
        docs.append(doc)
    return docs


@router.get("/providers", response_model=ProvidersResponse)
def providers() -> dict:
    def call() -> dict:
        settings = get_settings()
        built = [factory.build_provider(pid, settings) for pid in factory.PROVIDER_IDS]
        # CLI checks spawn a few short local processes each; run the three probes side by side.
        with ThreadPoolExecutor(max_workers=len(built)) as pool:
            statuses = list(pool.map(lambda provider: provider.status(), built))
        # The user's choice in Settings wins over the environment default.
        default = load_user_settings(settings).chat_default_provider
        return {"default": default, "providers": statuses}

    return _guarded(call)


@router.post("/preview", response_model=ChatPreviewResponse)
def preview(body: ChatPreviewRequest) -> dict:
    def call() -> dict:
        settings = get_settings()
        docs = _documents(body.doc_ids)
        provider = factory.build_provider(body.provider, settings)
        return factory.build_chat_service(settings).preview(docs, body.question, provider)

    return _guarded(call)


@router.post("", response_model=ChatResponse)
def ask(body: ChatRequest) -> dict:
    def call() -> dict:
        settings = get_settings()
        docs = _documents(body.doc_ids)
        provider = factory.build_provider(body.provider, settings)
        return factory.build_chat_service(settings).ask(
            docs,
            body.question,
            provider,
            preview_hash=body.preview_hash,
            history=[m.model_dump() for m in body.history],
        )

    return _guarded(call)


class LegacyChatRequest(BaseModel):
    messages: list[dict]


@router.post("/{doc_id}")
def chat(doc_id: str, body: LegacyChatRequest) -> dict:
    """Legacy single-document chat for the old UI: always the local Ollama provider."""
    def call() -> dict:
        [doc] = _documents([doc_id])
        answer = factory.build_chat_service(get_settings()).chat(doc, body.messages)
        return {"answer": answer}

    return _guarded(call)

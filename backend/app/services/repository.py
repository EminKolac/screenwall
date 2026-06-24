"""Document repository — the seam between the pipeline/API and storage.

Phase 4 ships an in-memory implementation; Phase 5 adds a storage-backed one over the 5 layers
(this Protocol is the contract both honor). Mapping (layer 2) and original/extracted are never
returned to the API; only anonymized content (layer 3) and PII-safe metadata/reports are.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.extraction.base import ExtractedContent
from app.models.document import Document


@runtime_checkable
class DocumentRepository(Protocol):
    def save_document(self, doc: Document) -> None: ...
    def get_document(self, doc_id: str) -> Document | None: ...
    def list_documents(self) -> list[Document]: ...
    def save_original(self, doc_id: str, data: bytes, filename: str) -> None: ...
    def get_original(self, doc_id: str) -> bytes | None: ...
    def save_extracted(self, doc_id: str, content: ExtractedContent) -> None: ...
    def get_extracted(self, doc_id: str) -> ExtractedContent | None: ...
    def save_anonymized(self, doc_id: str, content: ExtractedContent) -> None: ...
    def get_anonymized(self, doc_id: str) -> ExtractedContent | None: ...
    def save_mapping(self, doc_id: str, mapping: dict[str, str]) -> None: ...
    def save_chat_context(self, doc_id: str, text: str) -> None: ...
    def get_chat_context(self, doc_id: str) -> str | None: ...
    def delete(self, doc_id: str, *, secure: bool = True) -> None: ...


class InMemoryDocumentRepository:
    def __init__(self) -> None:
        self._docs: dict[str, Document] = {}
        self._original: dict[str, bytes] = {}
        self._extracted: dict[str, ExtractedContent] = {}
        self._anon: dict[str, ExtractedContent] = {}
        self._mapping: dict[str, dict[str, str]] = {}
        self._chat: dict[str, str] = {}

    def save_document(self, doc: Document) -> None:
        self._docs[doc.id] = doc

    def get_document(self, doc_id: str) -> Document | None:
        return self._docs.get(doc_id)

    def list_documents(self) -> list[Document]:
        return list(self._docs.values())

    def save_original(self, doc_id: str, data: bytes, filename: str) -> None:
        self._original[doc_id] = data

    def get_original(self, doc_id: str) -> bytes | None:
        return self._original.get(doc_id)

    def save_extracted(self, doc_id: str, content: ExtractedContent) -> None:
        self._extracted[doc_id] = content

    def get_extracted(self, doc_id: str) -> ExtractedContent | None:
        return self._extracted.get(doc_id)

    def save_anonymized(self, doc_id: str, content: ExtractedContent) -> None:
        self._anon[doc_id] = content

    def get_anonymized(self, doc_id: str) -> ExtractedContent | None:
        return self._anon.get(doc_id)

    def save_mapping(self, doc_id: str, mapping: dict[str, str]) -> None:
        self._mapping[doc_id] = mapping

    def save_chat_context(self, doc_id: str, text: str) -> None:
        self._chat[doc_id] = text

    def get_chat_context(self, doc_id: str) -> str | None:
        return self._chat.get(doc_id)

    def delete(self, doc_id: str, *, secure: bool = True) -> None:
        for store in (self._docs, self._original, self._extracted, self._anon, self._mapping, self._chat):
            store.pop(doc_id, None)

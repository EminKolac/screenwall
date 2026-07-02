"""Storage-backed DocumentRepository over the 5 layers (Phase 5).

Layer map: original→1, extracted text + mapping→2, anonymized→3, document meta/reports→4 (PII-safe),
chat context→5. Same contract as the in-memory repo; swapped in via `services.deps`.
"""
from __future__ import annotations

from app.extraction.base import ExtractedContent
from app.models.document import Document
from app.storage.base import StorageLayer
from app.storage.local import LocalStorageBackend


class StorageDocumentRepository:
    def __init__(self, backend: LocalStorageBackend) -> None:
        self.backend = backend

    # --- document meta (layer 4, PII-safe: mapping/raw_terms excluded by the models) ---
    def save_document(self, doc: Document) -> None:
        self.backend.write_json(StorageLayer.VALIDATION, doc.id, "document.json", doc.model_dump(mode="json"))

    def get_document(self, doc_id: str) -> Document | None:
        if not self.backend.exists(StorageLayer.VALIDATION, doc_id, "document.json"):
            return None
        return Document.model_validate(self.backend.read_json(StorageLayer.VALIDATION, doc_id, "document.json"))

    def list_documents(self) -> list[Document]:
        base = self.backend.root / StorageLayer.VALIDATION.value
        out: list[Document] = []
        if base.exists():
            for d in sorted(base.iterdir()):
                if (d / "document.json").exists():
                    doc = self.get_document(d.name)
                    if doc:
                        out.append(doc)
        return out

    # --- original (layer 1) ---
    def save_original(self, doc_id: str, data: bytes, filename: str) -> None:
        self.backend.write_bytes(StorageLayer.ORIGINAL, doc_id, "original.bin", data)

    def get_original(self, doc_id: str) -> bytes | None:
        if not self.backend.exists(StorageLayer.ORIGINAL, doc_id, "original.bin"):
            return None
        return self.backend.read_bytes(StorageLayer.ORIGINAL, doc_id, "original.bin")

    # --- extracted + mapping (layer 2, local-only) ---
    def save_extracted(self, doc_id: str, content: ExtractedContent) -> None:
        self.backend.write_json(StorageLayer.EXTRACTED, doc_id, "extracted.json", content.model_dump(mode="json"))

    def get_extracted(self, doc_id: str) -> ExtractedContent | None:
        if not self.backend.exists(StorageLayer.EXTRACTED, doc_id, "extracted.json"):
            return None
        return ExtractedContent.model_validate(self.backend.read_json(StorageLayer.EXTRACTED, doc_id, "extracted.json"))

    def save_mapping(self, doc_id: str, mapping: dict[str, str]) -> None:
        self.backend.write_json(StorageLayer.EXTRACTED, doc_id, "mapping.json", mapping)

    def get_mapping(self, doc_id: str) -> dict[str, str] | None:
        if not self.backend.exists(StorageLayer.EXTRACTED, doc_id, "mapping.json"):
            return None
        return self.backend.read_json(StorageLayer.EXTRACTED, doc_id, "mapping.json")

    # --- anonymized (layer 3) ---
    def save_anonymized(self, doc_id: str, content: ExtractedContent) -> None:
        self.backend.write_json(StorageLayer.ANONYMIZED, doc_id, "anonymized.json", content.model_dump(mode="json"))

    def get_anonymized(self, doc_id: str) -> ExtractedContent | None:
        if not self.backend.exists(StorageLayer.ANONYMIZED, doc_id, "anonymized.json"):
            return None
        return ExtractedContent.model_validate(self.backend.read_json(StorageLayer.ANONYMIZED, doc_id, "anonymized.json"))

    # --- chat context (layer 5) ---
    def save_chat_context(self, doc_id: str, text: str) -> None:
        self.backend.write_bytes(StorageLayer.CHAT_CONTEXT, doc_id, "context.txt", text.encode("utf-8"))

    def get_chat_context(self, doc_id: str) -> str | None:
        if not self.backend.exists(StorageLayer.CHAT_CONTEXT, doc_id, "context.txt"):
            return None
        return self.backend.read_bytes(StorageLayer.CHAT_CONTEXT, doc_id, "context.txt").decode("utf-8")

    def delete(self, doc_id: str, *, secure: bool = True) -> None:
        self.backend.delete_document(doc_id, secure=secure)

"""Storage-backed DocumentRepository over the 5 layers (Phase 5).

Layer map: original→1, extracted text + mapping + decisions + audit terms→2, anonymized→3,
document meta/reports→4 (PII-safe), chat context→5. Swapped in via `services.deps`.
"""
from __future__ import annotations

import logging

from app.extraction.base import ExtractedContent
from app.models.document import Document, upgrade_stored
from app.storage.base import StorageLayer
from app.storage.local import LocalStorageBackend

logger = logging.getLogger(__name__)
_VAL, _EXT, _ANON = StorageLayer.VALIDATION, StorageLayer.EXTRACTED, StorageLayer.ANONYMIZED


class StorageDocumentRepository:
    def __init__(self, backend: LocalStorageBackend) -> None:
        self.backend = backend

    # --- document meta (layer 4, PII-safe: mapping/raw_terms excluded by the models) ---
    def save_document(self, doc: Document) -> None:
        self.backend.write_json(_VAL, doc.id, "document.json", doc.model_dump(mode="json"))

    def get_document(self, doc_id: str) -> Document | None:
        if not self.backend.exists(_VAL, doc_id, "document.json"):
            return None
        stored = self.backend.read_json(_VAL, doc_id, "document.json")
        return Document.model_validate(upgrade_stored(stored))

    def list_documents(self) -> list[Document]:
        """Every readable document. An unreadable document.json (torn write, bad JSON, invalid
        fields) is skipped and logged by id and error TYPE only — never its content — so one broken
        file cannot make the listing fail or block startup recovery."""
        base = self.backend.root / _VAL.value
        out: list[Document] = []
        if base.exists():
            for d in sorted(base.iterdir()):
                if not (d / "document.json").exists():
                    continue
                try:
                    doc = self.get_document(d.name)
                except Exception as e:  # noqa: BLE001 — any broken file: skip it, log the type
                    logger.warning("skipping unreadable document %s: %s", d.name, type(e).__name__)
                    continue
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
        self.backend.write_json(_EXT, doc_id, "extracted.json", content.model_dump(mode="json"))

    def get_extracted(self, doc_id: str) -> ExtractedContent | None:
        if not self.backend.exists(_EXT, doc_id, "extracted.json"):
            return None
        return ExtractedContent.model_validate(
            self.backend.read_json(_EXT, doc_id, "extracted.json"))

    def save_mapping(self, doc_id: str, mapping: dict[str, str]) -> None:
        self.backend.write_json(StorageLayer.EXTRACTED, doc_id, "mapping.json", mapping)

    def get_mapping(self, doc_id: str) -> dict[str, str] | None:
        if not self.backend.exists(StorageLayer.EXTRACTED, doc_id, "mapping.json"):
            return None
        return self.backend.read_json(StorageLayer.EXTRACTED, doc_id, "mapping.json")

    # --- anonymized (layer 3) ---
    def save_anonymized(self, doc_id: str, content: ExtractedContent) -> None:
        self.backend.write_json(_ANON, doc_id, "anonymized.json", content.model_dump(mode="json"))

    def get_anonymized(self, doc_id: str) -> ExtractedContent | None:
        if not self.backend.exists(_ANON, doc_id, "anonymized.json"):
            return None
        return ExtractedContent.model_validate(
            self.backend.read_json(_ANON, doc_id, "anonymized.json"))

    # --- edit positions (layer 3, PII-safe: offsets, placeholders and types only) ---
    def save_edits(self, doc_id: str, edits: dict[str, list[dict]]) -> None:
        self.backend.write_json(StorageLayer.ANONYMIZED, doc_id, "edits.json", edits)

    def get_edits(self, doc_id: str) -> dict[str, list[dict]]:
        if not self.backend.exists(StorageLayer.ANONYMIZED, doc_id, "edits.json"):
            return {}
        return self.backend.read_json(StorageLayer.ANONYMIZED, doc_id, "edits.json")

    # --- residual findings (layer 4, PII-safe: positions in the masked text + type code) ---
    def save_findings(self, doc_id: str, findings: list[dict]) -> None:
        self.backend.write_json(StorageLayer.VALIDATION, doc_id, "findings.json", findings)

    def get_findings(self, doc_id: str) -> list[dict]:
        if not self.backend.exists(StorageLayer.VALIDATION, doc_id, "findings.json"):
            return []
        return self.backend.read_json(StorageLayer.VALIDATION, doc_id, "findings.json")

    # --- human decisions (layer 2, local-only: they reference original values) ---
    def save_decisions(self, doc_id: str, decisions: dict) -> None:
        self.backend.write_json(StorageLayer.EXTRACTED, doc_id, "decisions.json", decisions)

    def get_decisions(self, doc_id: str) -> dict:
        if not self.backend.exists(StorageLayer.EXTRACTED, doc_id, "decisions.json"):
            return {}
        return self.backend.read_json(StorageLayer.EXTRACTED, doc_id, "decisions.json")

    # --- the auditor's residual terms (layer 2, local-only: raw values; mapping mode only) ---
    def save_audit_terms(self, doc_id: str, terms: list[dict]) -> None:
        self.backend.write_json(_EXT, doc_id, "audit_terms.json", terms)

    def get_audit_terms(self, doc_id: str) -> list[dict]:
        if not self.backend.exists(_EXT, doc_id, "audit_terms.json"):
            return []
        return self.backend.read_json(_EXT, doc_id, "audit_terms.json")

    # --- chat context (layer 5) ---
    def save_chat_context(self, doc_id: str, text: str) -> None:
        self.backend.write_bytes(StorageLayer.CHAT_CONTEXT, doc_id, "context.txt",
                                 text.encode("utf-8"))

    def get_chat_context(self, doc_id: str) -> str | None:
        if not self.backend.exists(StorageLayer.CHAT_CONTEXT, doc_id, "context.txt"):
            return None
        raw = self.backend.read_bytes(StorageLayer.CHAT_CONTEXT, doc_id, "context.txt")
        return raw.decode("utf-8")

    def delete(self, doc_id: str, *, secure: bool = True) -> None:
        self.backend.delete_document(doc_id, secure=secure)

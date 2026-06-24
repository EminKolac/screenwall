"""Chat gating + service: only approved documents, only anonymized layer-5 content."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.chat.base import ChatNotAllowed
from app.chat.service import ChatService
from app.config import get_settings
from app.main import app
from app.models.document import Document, DocumentStatus, FileKind
from app.services.deps import get_repository
from app.storage.base import StorageLayer
from app.storage.local import LocalStorageBackend

client = TestClient(app)


def test_chat_blocked_for_non_approved_document():
    get_repository().save_document(Document(
        id="c1", filename="f.docx", kind=FileKind.docx, status=DocumentStatus.EXTRACTED))
    r = client.post("/api/chat/c1", json={"messages": [{"role": "user", "content": "hi"}]})
    assert r.status_code == 403  # gate triggers before any provider call


def test_chat_unknown_document_404():
    assert client.post("/api/chat/none", json={"messages": []}).status_code == 404


class _StubProvider:
    name = "stub"

    def chat(self, system_prompt, messages, model):
        assert "ANONYMIZED CONTEXT" in system_prompt  # only anonymized context is sent out
        assert "<PERSON_1>" in system_prompt
        return "stub answer"


def test_chat_service_success_reads_only_layer5(tmp_path):
    backend = LocalStorageBackend(tmp_path)
    backend.write_bytes(StorageLayer.CHAT_CONTEXT, "c2", "context.txt",
                        "Anonymized doc with <PERSON_1>.".encode())
    svc = ChatService(_StubProvider(), backend, get_settings())
    doc = Document(id="c2", filename="f.docx", kind=FileKind.docx, status=DocumentStatus.APPROVED)
    assert svc.chat(doc, [{"role": "user", "content": "who signed?"}]) == "stub answer"


def test_chat_service_blocks_when_no_context(tmp_path):
    svc = ChatService(_StubProvider(), LocalStorageBackend(tmp_path), get_settings())
    doc = Document(id="c3", filename="f.docx", kind=FileKind.docx, status=DocumentStatus.APPROVED)
    with pytest.raises(ChatNotAllowed):
        svc.chat(doc, [{"role": "user", "content": "hi"}])

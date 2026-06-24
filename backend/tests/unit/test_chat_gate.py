import pytest

from app.chat.base import ChatNotAllowed, ensure_chat_allowed
from app.chat.service import ChatService
from app.config import get_settings
from app.models.document import Document, DocumentStatus, FileKind


def _doc(status: DocumentStatus) -> Document:
    return Document(id="x", filename="f.docx", kind=FileKind.docx, status=status)


def test_gate_blocks_non_approved():
    with pytest.raises(ChatNotAllowed):
        ensure_chat_allowed(_doc(DocumentStatus.NEEDS_HUMAN_REVIEW))
    with pytest.raises(ChatNotAllowed):
        ensure_chat_allowed(_doc(DocumentStatus.EXTRACTED))


def test_gate_allows_approved():
    ensure_chat_allowed(_doc(DocumentStatus.APPROVED))  # must not raise


class _Provider:
    name = "dummy"

    def chat(self, system_prompt, messages, model):
        return "answer"


class _Store:
    def write_bytes(self, *a, **k):
        return ""

    def read_bytes(self, *a, **k):
        return b"anonymized context with <PERSON_1>"

    def write_json(self, *a, **k):
        return ""

    def read_json(self, *a, **k):
        return {}

    def exists(self, *a, **k):
        return True

    def delete_document(self, *a, **k):
        return None


def test_service_blocks_non_approved():
    svc = ChatService(_Provider(), _Store(), get_settings())
    with pytest.raises(ChatNotAllowed):
        svc.chat(_doc(DocumentStatus.EXTRACTED), [{"role": "user", "content": "hi"}])


def test_service_allows_approved():
    svc = ChatService(_Provider(), _Store(), get_settings())
    assert svc.chat(_doc(DocumentStatus.APPROVED), [{"role": "user", "content": "hi"}]) == "answer"

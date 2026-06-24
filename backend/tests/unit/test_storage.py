"""Storage layer isolation, round-trip, and secure deletion (Phase 5)."""
from __future__ import annotations

import pytest

from app.models.document import Document, FileKind
from app.services.storage_repository import StorageDocumentRepository
from app.storage.base import StorageAccessError, StorageLayer, assert_shareable
from app.storage.local import LocalStorageBackend


def test_write_read_roundtrip(tmp_path):
    b = LocalStorageBackend(tmp_path)
    b.write_bytes(StorageLayer.ANONYMIZED, "d1", "a.txt", b"hello")
    assert b.read_bytes(StorageLayer.ANONYMIZED, "d1", "a.txt") == b"hello"
    assert b.exists(StorageLayer.ANONYMIZED, "d1", "a.txt")


def test_secure_delete_removes_all_layers(tmp_path):
    b = LocalStorageBackend(tmp_path)
    for layer in StorageLayer:
        b.write_bytes(layer, "d1", "f.bin", b"sensitive")
    b.delete_document("d1", secure=True)
    for layer in StorageLayer:
        assert not b.exists(layer, "d1", "f.bin")


def test_assert_shareable_blocks_local_only_layers():
    assert_shareable(StorageLayer.CHAT_CONTEXT)  # ok
    for layer in (StorageLayer.ORIGINAL, StorageLayer.EXTRACTED,
                  StorageLayer.ANONYMIZED, StorageLayer.VALIDATION):
        with pytest.raises(StorageAccessError):
            assert_shareable(layer)


def test_storage_repository_roundtrip(tmp_path):
    repo = StorageDocumentRepository(LocalStorageBackend(tmp_path))
    doc = Document(id="x", filename="f.docx", kind=FileKind.docx)
    repo.save_document(doc)
    repo.save_original("x", b"rawbytes", "f.docx")
    repo.save_chat_context("x", "anon ctx")
    assert repo.get_document("x").id == "x"
    assert repo.get_original("x") == b"rawbytes"
    assert repo.get_chat_context("x") == "anon ctx"
    assert any(d.id == "x" for d in repo.list_documents())
    repo.delete("x")
    assert repo.get_document("x") is None
    assert repo.get_chat_context("x") is None

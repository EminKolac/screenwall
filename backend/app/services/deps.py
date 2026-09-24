"""Shared singletons (FastAPI dependency providers).

Tests point STORAGE_ROOT at a temp dir and clear these caches for isolation.
"""
from __future__ import annotations

from functools import lru_cache

from app.config import get_settings
from app.services.repository import DocumentRepository
from app.services.storage_repository import StorageDocumentRepository
from app.storage.local import LocalStorageBackend


@lru_cache
def get_repository() -> DocumentRepository:
    settings = get_settings()
    return StorageDocumentRepository(LocalStorageBackend(settings.storage_root))


@lru_cache
def get_worker():
    from app.pipeline.queue import Worker

    return Worker(get_settings, get_repository)

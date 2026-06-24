"""The five isolated storage layers (Architecture.md §6, SECURITY.md §3).

Codex Phase-1 review (CRITICAL): isolation must be more than declarative. `assert_shareable` is
the runtime guard that every outbound path (chat / external provider) MUST call before exposing
content; local-only layers raise. The local backend (Phase 5) additionally enforces that
provider-facing services receive a read-only handle limited to CHAT_CONTEXT.
"""
from __future__ import annotations

from enum import Enum
from typing import Protocol, runtime_checkable


class StorageLayer(str, Enum):
    ORIGINAL = "1_original"          # raw uploaded bytes
    EXTRACTED = "2_extracted"        # text/tables/metadata + placeholder↔original mapping
    ANONYMIZED = "3_anonymized"      # anonymized artifact (downloadable)
    VALIDATION = "4_validation"      # audit reports + iteration history (PII-safe)
    CHAT_CONTEXT = "5_chat_context"  # approved anonymized context for chat


# Never leave the machine / never exposed to clients or providers.
LOCAL_ONLY_LAYERS = frozenset({StorageLayer.ORIGINAL, StorageLayer.EXTRACTED})
# The ONLY layer an external chat provider may ever read.
EXTERNALLY_SHAREABLE_LAYERS = frozenset({StorageLayer.CHAT_CONTEXT})


class StorageAccessError(PermissionError):
    """Raised when a caller attempts to expose a local-only layer outside the trust boundary."""


def assert_shareable(layer: StorageLayer) -> None:
    """Single guard for outbound paths. Raises unless `layer` may leave the trust boundary."""
    if layer not in EXTERNALLY_SHAREABLE_LAYERS:
        raise StorageAccessError(
            f"Layer '{layer.value}' is not externally shareable; only "
            f"{[l.value for l in EXTERNALLY_SHAREABLE_LAYERS]} may be sent to a provider."
        )


@runtime_checkable
class StorageBackend(Protocol):
    def write_bytes(self, layer: StorageLayer, document_id: str, name: str, data: bytes) -> str: ...
    def read_bytes(self, layer: StorageLayer, document_id: str, name: str) -> bytes: ...
    def write_json(self, layer: StorageLayer, document_id: str, name: str, obj: object) -> str: ...
    def read_json(self, layer: StorageLayer, document_id: str, name: str) -> object: ...
    def exists(self, layer: StorageLayer, document_id: str, name: str) -> bool: ...
    def delete_document(self, document_id: str, *, secure: bool = True) -> None: ...

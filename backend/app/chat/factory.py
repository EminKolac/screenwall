"""Build the local chat provider + a wired ChatService (post-approval, layer-5 only)."""
from __future__ import annotations

from app.chat.providers import OllamaChatProvider
from app.chat.service import ChatService
from app.config import Settings
from app.storage.local import LocalStorageBackend


def build_chat_provider(settings: Settings) -> OllamaChatProvider:
    return OllamaChatProvider(settings.ollama_base_url, settings.chat_ollama_model)


def build_chat_service(settings: Settings) -> ChatService:
    backend = LocalStorageBackend(settings.storage_root)
    return ChatService(build_chat_provider(settings), backend, settings)

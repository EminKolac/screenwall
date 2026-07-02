"""Build the configured chat provider + a wired ChatService (post-approval, layer-5 only)."""
from __future__ import annotations

from app.chat.providers import (
    AnthropicProvider,
    AzureOpenAIProvider,
    OllamaChatProvider,
    OpenAIProvider,
)
from app.chat.service import ChatService
from app.config import Settings
from app.storage.local import LocalStorageBackend


def build_chat_provider(settings: Settings):
    p = settings.chat_provider
    if p == "ollama":
        return OllamaChatProvider(settings.ollama_base_url, settings.chat_ollama_model)
    if p == "anthropic":
        return AnthropicProvider(settings.anthropic_api_key)
    if p == "openai":
        return OpenAIProvider(settings.openai_api_key)
    if p == "azure":
        return AzureOpenAIProvider(
            settings.azure_openai_api_key,
            settings.azure_openai_endpoint,
            settings.azure_openai_deployment,
        )
    raise ValueError(f"unknown chat provider: {p}")


def build_chat_service(settings: Settings) -> ChatService:
    backend = LocalStorageBackend(settings.storage_root)
    return ChatService(build_chat_provider(settings), backend, settings)

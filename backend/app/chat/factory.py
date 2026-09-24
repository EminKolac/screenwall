"""Build chat providers by id + a wired ChatService (post-approval, layer-5 only)."""
from __future__ import annotations

from app.chat.base import ChatError
from app.chat.providers import ClaudeCliProvider, CodexCliProvider, OllamaChatProvider
from app.chat.service import ChatService
from app.config import Settings
from app.storage.local import LocalStorageBackend

# Contract ProviderId, in the order the UI lists them.
PROVIDER_IDS: tuple[str, ...] = ("ollama", "claude_cli", "codex_cli")


def build_provider(
    provider_id: str, settings: Settings
) -> OllamaChatProvider | ClaudeCliProvider | CodexCliProvider:
    if provider_id == "ollama":
        return build_chat_provider(settings)
    timeout = min(max(settings.chat_cli_timeout_s, 5), 600)  # a typo must not disable the bound
    if provider_id == "claude_cli":
        return ClaudeCliProvider(settings.chat_claude_model, timeout)
    if provider_id == "codex_cli":
        return CodexCliProvider(settings.chat_codex_model, timeout)
    raise ChatError("provider_unavailable")


def build_chat_provider(settings: Settings) -> OllamaChatProvider:
    """The local default (also what the legacy single-document route uses)."""
    return OllamaChatProvider(settings.ollama_base_url, settings.chat_ollama_model)


def build_chat_service(settings: Settings) -> ChatService:
    backend = LocalStorageBackend(settings.storage_root)
    return ChatService(build_chat_provider(settings), backend, settings)

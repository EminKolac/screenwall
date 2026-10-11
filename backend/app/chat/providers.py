"""Post-approval chat providers: local Ollama (default) + Claude / Codex through their CLIs.

Ollama runs on this machine. Claude and Codex run in the cloud under the user's OWN CLI login
(`claude auth login`, `codex login`); Fable stores no API key and the SDK-based cloud providers
stay removed — the CLI path (chat/cli.py) is the only cloud route, and ChatService reaches it
only through the consent gate (preview_hash, plan §5.6).

Every provider keeps the original interface `chat(system_prompt, messages, model) -> str` and adds
  - `render(...)`: the exact text `chat` sends for the same inputs (the consent preview);
  - `status()`: contract ProviderStatus; never raises, never returns account identifiers.
Failures surface only as fixed contract codes (ChatError / cli.CliError).

On Windows the Claude and Codex providers are unavailable (status problem "unsupported_os"):
chat/cli_process.py relies on POSIX process groups and selectable pipes. Ollama is unaffected.
"""
from __future__ import annotations

import json

import httpx

from app.chat import cli, cli_process
from app.chat.base import ChatError
from app.security import ollama

# ProviderStatus.problem of a CLI provider on Windows, where chat/cli_process.py cannot run a
# CLI safely. A status reason only: requests to such a provider fail as provider_unavailable.
UNSUPPORTED_OS = "unsupported_os"


def _status(provider, **fields) -> dict:
    """Contract ProviderStatus with every key present."""
    base = {
        "id": provider.id,
        "label": provider.label,
        "local": provider.local,
        "available": False,
        "installed": None,
        "compatible": None,
        "authenticated": None,
        "version": None,
        "model": provider.model or None,
        "login_command": None,
        "problem": None,
    }
    base.update(fields)
    base["available"] = base["problem"] is None
    return base


class OllamaChatProvider:
    """Chat via Ollama — no external API or key. Requires Ollama running with the model pulled
    (see scripts/setup_macos.sh). Local means this computer (security/ollama.py): a remote
    OLLAMA_BASE_URL is unavailable unless `ollama_allow_remote`, and even then it is not `local`,
    so the consent preview applies and names the host. Ollama cloud models are unavailable."""
    id = "ollama"
    name = "ollama"
    label = "Lokal LLM (Ollama)"
    local = True
    destination = ollama.LOCAL_DESTINATION
    # Tests inject an httpx.MockTransport here; None = the real Ollama.
    transport: httpx.BaseTransport | None = None

    def __init__(self, base_url: str, model: str, allow_remote: bool = False) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        # None = usable; otherwise nothing is ever sent (no preview either).
        self.refusal = ollama.refusal(base_url, model, allow_remote)
        self.local = ollama.is_loopback_url(base_url)
        self.destination = ollama.destination(base_url)
        if not self.local:
            self.label = "Uzak Ollama"

    def _client(self, timeout: float) -> httpx.Client:
        # trust_env=False: HTTP(S)_PROXY must never route document text through a proxy.
        return httpx.Client(timeout=timeout, trust_env=False, transport=self.transport)

    def render(self, system_prompt: str, messages: list[dict], model: str = "") -> str:
        if self.refusal is not None:
            raise ChatError("provider_unavailable")
        payload = {
            "model": self.model or model,
            "stream": False,
            "think": False,  # bkz. audit/ollama_provider.py — Qwen3 kuşağında zorunlu
            "options": {"temperature": 0.2},
            "messages": [{"role": "system", "content": system_prompt}, *messages],
        }
        return json.dumps(payload, ensure_ascii=False)

    def chat(self, system_prompt: str, messages: list[dict], model: str) -> str:
        body = self.render(system_prompt, messages, model).encode("utf-8")
        try:
            with self._client(180.0) as client:
                r = client.post(
                    f"{self.base_url}/api/chat",
                    content=body,
                    headers={"Content-Type": "application/json"},
                )
        except (httpx.HTTPError, httpx.InvalidURL):
            raise ChatError("ollama_unreachable") from None
        if r.status_code == 404:  # Ollama: model "<name>" not found, try pulling it first
            raise ChatError("model_missing")
        if r.status_code != 200:
            raise ChatError("provider_unavailable")
        try:
            content = r.json().get("message", {}).get("content", "")
        except (ValueError, AttributeError):
            raise ChatError("provider_unavailable") from None
        if not isinstance(content, str):
            raise ChatError("provider_unavailable")
        return content

    def status(self) -> dict:
        """GET /api/tags (2 s): reachable, and the configured model is pulled."""
        if self.refusal is not None:
            return _status(self, problem="provider_unavailable")
        try:
            with self._client(2.0) as client:
                r = client.get(f"{self.base_url}/api/tags")
            r.raise_for_status()
            names = {
                name
                for entry in r.json().get("models", [])
                for name in (entry.get("name"), entry.get("model"))
                if name
            }
        except Exception:  # noqa: BLE001 — any failure means "not reachable"
            return _status(self, problem="ollama_unreachable")
        if not self.model or not ({self.model, f"{self.model}:latest"} & names):
            return _status(self, problem="model_missing")
        return _status(self)


class _CliChatProvider:
    """Cloud chat through an installed CLI (chat/cli.py). Content goes only via stdin."""
    id = ""
    label = ""
    destination = ""
    login_command = ""
    local = False

    def __init__(self, model: str = "", timeout: float = 60) -> None:
        self.model = model  # "" = the CLI's own default model
        self.timeout = timeout

    @property
    def name(self) -> str:
        return self.id

    def render(self, system_prompt: str, messages: list[dict], model: str = "") -> str:
        if not cli_process.supported():  # no consent preview for a send that cannot happen
            raise ChatError("provider_unavailable")
        return cli.envelope(system_prompt, messages)

    def chat(self, system_prompt: str, messages: list[dict], model: str) -> str:
        if not cli_process.supported():
            raise ChatError("provider_unavailable")
        config = {"provider": self.id, "model": self.model or model, "timeout": self.timeout}
        try:
            return cli.complete(config, system_prompt, messages)
        except cli.CliError:
            raise
        except Exception:  # noqa: BLE001 — only fixed codes may leave the provider
            raise cli.CliError("cli_failed") from None

    def status(self) -> dict:
        if not cli_process.supported():  # Windows: no CLI is looked up or started at all
            return _status(self, problem=UNSUPPORTED_OS)
        try:
            found = cli.status(self.id)
        except cli.CliError as e:
            return _status(self, login_command=self.login_command, problem=e.code)
        except Exception:  # noqa: BLE001
            return _status(self, login_command=self.login_command, problem="cli_failed")
        installed = bool(found.get("installed"))
        compatible = bool(found.get("compatible")) if installed else None
        authenticated = bool(found.get("authenticated")) if installed else None
        if not installed:
            problem = "cli_not_found"
        elif not compatible:
            problem = "cli_upgrade_required"
        elif not authenticated:
            problem = "cli_login_required"
        else:
            problem = None
        return _status(
            self,
            installed=installed,
            compatible=compatible,
            authenticated=authenticated,
            version=found.get("version"),
            login_command=self.login_command,
            problem=problem,
        )


class ClaudeCliProvider(_CliChatProvider):
    id = "claude_cli"
    label = "Claude"
    destination = "Anthropic (Claude)"
    login_command = "claude auth login"


class CodexCliProvider(_CliChatProvider):
    id = "codex_cli"
    label = "ChatGPT (Codex CLI)"
    destination = "OpenAI (ChatGPT)"
    login_command = "codex login"

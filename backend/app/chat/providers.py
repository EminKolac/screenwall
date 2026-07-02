"""External chat providers (OpenAI / Anthropic / Azure OpenAI).

SDKs are imported lazily inside `chat()` so this module imports even without the [chat] extra
installed. Providers are only ever reached through `ChatService` (post-approval, anonymized-only).
"""
from __future__ import annotations


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    def chat(self, system_prompt: str, messages: list[dict], model: str) -> str:
        import anthropic

        client = anthropic.Anthropic(api_key=self.api_key)
        resp = client.messages.create(
            model=model, system=system_prompt, max_tokens=1024, messages=messages
        )
        return "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")


class OpenAIProvider:
    name = "openai"

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key

    def chat(self, system_prompt: str, messages: list[dict], model: str) -> str:
        import openai

        client = openai.OpenAI(api_key=self.api_key)
        resp = client.chat.completions.create(
            model=model, messages=[{"role": "system", "content": system_prompt}, *messages]
        )
        return resp.choices[0].message.content or ""


class OllamaChatProvider:
    """Fully local chat via Ollama — no external API or key. Requires Ollama running with the
    model pulled (see scripts/setup_macos.sh)."""
    name = "ollama"

    def __init__(self, base_url: str, model: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model

    def chat(self, system_prompt: str, messages: list[dict], model: str) -> str:
        import httpx

        payload = {
            "model": self.model or model,
            "stream": False,
            "options": {"temperature": 0.2},
            "messages": [{"role": "system", "content": system_prompt}, *messages],
        }
        r = httpx.post(f"{self.base_url}/api/chat", json=payload, timeout=180.0)
        r.raise_for_status()
        return r.json().get("message", {}).get("content", "")


class AzureOpenAIProvider:
    name = "azure"

    def __init__(self, api_key: str, endpoint: str, deployment: str) -> None:
        self.api_key = api_key
        self.endpoint = endpoint
        self.deployment = deployment

    def chat(self, system_prompt: str, messages: list[dict], model: str) -> str:
        import openai

        client = openai.AzureOpenAI(
            api_key=self.api_key, azure_endpoint=self.endpoint, api_version="2024-06-01"
        )
        resp = client.chat.completions.create(
            model=self.deployment or model,
            messages=[{"role": "system", "content": system_prompt}, *messages],
        )
        return resp.choices[0].message.content or ""

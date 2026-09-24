"""Post-approval chat provider.

Yalnız YEREL Ollama. OpenAI/Anthropic/Azure sağlayıcıları kaldırıldı: üçü de yalnızca
onaylanmış anonim metin (katman 5) üzerinde çalışıyordu, yani model kalitesi kritik
değildi — buna karşılık üç bulut SDK'sı, anahtar yönetimi ve "%100 yerel" iddiasıyla
çelişen bir yüzey getiriyorlardı. Bulut sağlayıcı gerekirse bu dosyaya yeni bir sınıf
eklenir; `chat` imzası aynı kalır.
"""
from __future__ import annotations


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
            "think": False,  # bkz. audit/ollama_provider.py — Qwen3 kuşağında zorunlu
            "options": {"temperature": 0.2},
            "messages": [{"role": "system", "content": system_prompt}, *messages],
        }
        r = httpx.post(f"{self.base_url}/api/chat", json=payload, timeout=180.0)
        r.raise_for_status()
        return r.json().get("message", {}).get("content", "")

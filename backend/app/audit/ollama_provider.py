"""Local Qwen auditor via Ollama (LLMAuditProvider). Runs entirely on-device — no external call.

Availability is probed cheaply; `complete` requests strict JSON. Any transport error propagates
to `PrivacyAuditor`, which fails closed.
"""
from __future__ import annotations

import httpx


class OllamaProvider:
    name = "ollama"

    def __init__(self, base_url: str, model: str, timeout: float = 120.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    def is_available(self) -> bool:
        try:
            r = httpx.get(f"{self.base_url}/api/tags", timeout=3.0)
            if r.status_code != 200:
                return False
            models = [m.get("name", "") for m in r.json().get("models", [])]
            # available if the server is up; model presence is best-effort (pull may be pending)
            return True if models is not None else False
        except Exception:  # noqa: BLE001
            return False

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        payload = {
            "model": self.model,
            "stream": False,
            "format": "json",
            "options": {"temperature": 0},
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        r = httpx.post(f"{self.base_url}/api/chat", json=payload, timeout=self.timeout)
        r.raise_for_status()
        return r.json().get("message", {}).get("content", "")

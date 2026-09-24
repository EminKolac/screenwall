"""Local Qwen auditor via Ollama (LLMAuditProvider). Runs entirely on-device — no external call.

Availability is probed cheaply; `complete` requests strict JSON. Any transport error propagates
to `PrivacyAuditor`, which fails closed.

The text it sends is masked but not yet approved, so it must stay on this machine: a remote
OLLAMA_BASE_URL (without `ollama_allow_remote`) or an Ollama cloud model is refused before any
request (`refusal`, see security/ollama.py), and HTTP(S)_PROXY is never used (`trust_env=False`),
not even for localhost.
"""
from __future__ import annotations

import httpx

from app.security import ollama


class OllamaProvider:
    name = "ollama"
    # Tests may inject an httpx.MockTransport here; None = the real Ollama.
    transport: httpx.BaseTransport | None = None

    def __init__(self, base_url: str, model: str, timeout: float = 120.0,
                 allow_remote: bool = False) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        # None = usable; otherwise why this endpoint must never be contacted.
        self.refusal = ollama.refusal(base_url, model, allow_remote)

    def _client(self, timeout: float) -> httpx.Client:
        # trust_env=False: HTTP(S)_PROXY (or a system proxy) must never see document text.
        return httpx.Client(timeout=timeout, trust_env=False, transport=self.transport)

    def is_available(self) -> bool:
        if self.refusal is not None:
            return False
        try:
            with self._client(3.0) as client:
                r = client.get(f"{self.base_url}/api/tags")
            if r.status_code != 200:
                return False
            names = [m.get("name", "") for m in r.json().get("models", [])]
            # Available only if the configured model is actually pulled — otherwise the auditor
            # falls back to the deterministic heuristic instead of erroring on a missing model.
            return self.model in names or f"{self.model}:latest" in names
        except Exception:  # noqa: BLE001
            return False

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        if self.refusal is not None:  # PrivacyAuditor fails closed on any provider error
            raise PermissionError(f"ollama endpoint refused: {self.refusal}")
        payload = {
            "model": self.model,
            "stream": False,
            "format": "json",
            # Qwen3 kuşağı modeller VARSAYILAN OLARAK "thinking" modunda çalışır ve JSON
            # gövdesinden önce uzun bir akıl yürütme üretir. Ölçüldü (qwen3.5:4b, M4):
            # "tek kelime OK yaz" isteği düşünmeyle 753 token / 55 sn, think=false ile
            # 2 token / 0.1 sn. Denetim promptunda bu fark 180 sn timeout demek oluyordu.
            # Düşünmeyen modellerde (qwen2.5) alan sessizce yok sayılır — koşulsuz güvenli.
            "think": False,
            "options": {"temperature": 0},
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        with self._client(self.timeout) as client:
            r = client.post(f"{self.base_url}/api/chat", json=payload)
        r.raise_for_status()
        return r.json().get("message", {}).get("content", "")

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
            names = [m.get("name", "") for m in r.json().get("models", [])]
            # Available only if the configured model is actually pulled — otherwise the auditor
            # falls back to the deterministic heuristic instead of erroring on a missing model.
            return self.model in names or f"{self.model}:latest" in names
        except Exception:  # noqa: BLE001
            return False

    def complete(self, system_prompt: str, user_prompt: str) -> str:
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
        r = httpx.post(f"{self.base_url}/api/chat", json=payload, timeout=self.timeout)
        r.raise_for_status()
        return r.json().get("message", {}).get("content", "")

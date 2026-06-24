"""Local privacy-auditor provider interface.

Providers MUST run locally (no external calls): Ollama (default), MLX, or llama.cpp. The provider
only does text-in/text-out; prompt construction and strict JSON parsing live in `auditor.py`.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class LLMAuditProvider(Protocol):
    name: str
    def is_available(self) -> bool: ...
    def complete(self, system_prompt: str, user_prompt: str) -> str: ...

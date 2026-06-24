"""Application settings (pydantic-settings). Values come from environment / .env.

Secrets (API keys) are loaded here but consumed ONLY by the chat module, and ONLY after a
document is approved. Nothing in this module triggers an external call.

Codex Phase-1 review: provider fields are constrained (Literal) and `max_iterations` is bounded
to the PRD's 1..3 so config cannot silently drift (MEDIUM).
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Core
    app_env: Literal["development", "production", "test"] = "development"
    storage_root: Path = Path("./data")
    max_upload_mb: int = 50
    max_iterations: int = 3

    # Local privacy auditor (never external)
    auditor_provider: Literal["ollama", "mlx", "llamacpp"] = "ollama"
    auditor_model: str = "qwen2.5:7b-instruct-q4_K_M"
    ollama_base_url: str = "http://localhost:11434"
    auditor_risk_approve: Literal["low", "medium", "high"] = "low"
    # If True, the local LLM auditor is REQUIRED: when Ollama is unavailable, documents route to
    # human review instead of auto-approving on the heuristic alone (no silent fail-open).
    require_llm_auditor: bool = False

    # NLP / recognizers
    # en_core_web_sm runs out of the box; en_core_web_lg is the production-accuracy upgrade.
    spacy_en_model: str = "en_core_web_sm"
    spacy_multilingual_model: str = "xx_ent_wiki_sm"  # Turkish/other NER baseline (no torch)
    tr_ner_model: str = "savasy/bert-base-turkish-ner-cased"  # optional transformers upgrade ([tr] extra)
    use_transformers_tr: bool = False
    anonymizer_score_threshold: float = 0.4
    lang_detector: Literal["langdetect", "fasttext"] = "langdetect"

    # External chat (post-approval only)
    chat_provider: Literal["openai", "anthropic", "azure"] = "anthropic"
    chat_model: str = "claude-sonnet-4-6"
    chat_max_message_chars: int = 4000
    cors_allow_origins: str = "http://localhost:5173"  # comma-separated
    openai_api_key: str = ""
    anthropic_api_key: str = ""
    azure_openai_api_key: str = ""
    azure_openai_endpoint: str = ""
    azure_openai_deployment: str = ""

    @field_validator("max_iterations")
    @classmethod
    def _bound_iterations(cls, v: int) -> int:
        if not 1 <= v <= 3:
            raise ValueError("max_iterations must be between 1 and 3 (PRD requirement)")
        return v

    @field_validator("max_upload_mb")
    @classmethod
    def _positive_upload(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("max_upload_mb must be positive")
        return v

    def layer_path(self, layer_dir: str) -> Path:
        return self.storage_root / layer_dir


@lru_cache
def get_settings() -> Settings:
    return Settings()

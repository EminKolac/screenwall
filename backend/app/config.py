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
    tr_ner_model: str = "savasy/bert-base-turkish-ner-cased"  # optional transformers upgrade
    use_transformers_tr: bool = False
    anonymizer_score_threshold: float = 0.4
    lang_detector: Literal["langdetect", "fasttext"] = "langdetect"
    # Always-mask terms for THIS project/data room (fund, portfolio-company, brand names that NER
    # can't reliably catch, e.g. "e2vc"). Comma-separated; applied deterministically every run.
    deny_terms: str = ""

    # OpenAI Privacy Filter — optional LOCAL (on-device) contextual PII detector: a 2nd detection
    # stage unioned with Presidio. Needs the [privacy] extra (transformers+torch) and the model
    # PRE-DOWNLOADED once (scripts/setup_macos.sh with PRIVACY_FILTER=1); runtime loading is
    # local_files_only — zero network. Off by default so the platform runs torch-free by default.
    use_privacy_filter: bool = False
    privacy_filter_model: str = "OpenMed/privacy-filter-multilingual"  # multilingual (TR+EN)
    privacy_filter_threshold: float = 0.5
    require_privacy_filter: bool = False  # if unavailable → fail-closed to human review
    # Model labels to IGNORE (comma-separated, model taxonomy names). Defaults drop the noisy,
    # non-identifying classes that would over-mask business documents (contract dates, amounts,
    # currencies, job titles, "Visa" as card issuer); anything NOT listed is masked (fail-safe).
    privacy_filter_exclude_labels: str = (
        "AMOUNT,CREDITCARDISSUER,CURRENCY,CURRENCYCODE,CURRENCYNAME,CURRENCYSYMBOL,DATE,"
        "JOBDEPARTMENT,JOBTITLE,OCCUPATION,ORDINALDIRECTION,PREFIX,TIME"
    )

    # Chat (post-approval only). Default 'ollama' = fully local, no external API/key required.
    chat_provider: Literal["openai", "anthropic", "azure", "ollama"] = "ollama"
    chat_model: str = "claude-sonnet-4-6"
    chat_ollama_model: str = "qwen2.5:3b"  # small + fast for local chat (~2GB)
    chat_max_message_chars: int = 4000
    cors_allow_origins: str = "http://localhost:5173,http://localhost:5174"  # comma-separated
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

    def deny_list(self) -> list[str]:
        return [t.strip() for t in self.deny_terms.split(",") if t.strip()]

    def privacy_filter_excluded(self) -> frozenset[str]:
        labels = self.privacy_filter_exclude_labels.split(",")
        return frozenset(t.strip().upper() for t in labels if t.strip())


@lru_cache
def get_settings() -> Settings:
    return Settings()

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
    max_iterations: int = 2
    # Two anonymization modes, overridable per upload (see api/documents.py `mode` form field):
    #   "mapping"     — today's behaviour. Original + extracted-text + placeholder<->original map
    #                   are persisted (layers 1-2). Reversible by whoever holds the map. This is
    #                   PSEUDONYMIZATION, not anonymization — under KVKK/GDPR the output is still
    #                   personal data as long as the map exists. Lets a reviewer compare against
    #                   the source and lets a missed entity be corrected without re-uploading.
    #   "destructive" — layers 1-2 (original bytes, extracted text, the map) are NEVER written.
    #                   Only the anonymized text (layer 3) and PII-safe audit reports (layer 4)
    #                   are persisted. Irreversible: a missed entity cannot be recovered from
    #                   storage, and the reviewer cannot compare against the source — the document
    #                   must be re-uploaded. This is the only mode where "anonymized" is accurate.
    anonymization_mode: Literal["mapping", "destructive"] = "mapping"

    # Local privacy auditor (never external)
    auditor_provider: Literal["ollama", "mlx", "llamacpp"] = "ollama"
    auditor_model: str = "qwen3.5:4b"
    ollama_base_url: str = "http://localhost:11434"
    # OLLAMA_BASE_URL is used only when it is this computer (localhost, 127.0.0.0/8, ::1). A
    # remote host receives the auditor's masked-but-unapproved text and chat's questions, over
    # plain HTTP unless the URL says https: without this opt-in the auditor fails closed (every
    # document goes to review) and Ollama chat is unavailable; with it, Ollama chat is a remote
    # destination behind the same consent preview as the cloud CLIs (security/ollama.py).
    # Ollama "cloud" models (names ending in -cloud / :cloud) proxy to ollama.com: always refused.
    ollama_allow_remote: bool = False
    auditor_risk_approve: Literal["low", "medium", "high"] = "low"
    # If True, the local LLM auditor is REQUIRED: when Ollama is unavailable, documents route to
    # human review instead of auto-approving on the heuristic alone (no silent fail-open).
    require_llm_auditor: bool = False

    # NLP / recognizers
    # en_core_web_sm runs out of the box; en_core_web_lg is the production-accuracy upgrade.
    spacy_en_model: str = "en_core_web_sm"
    spacy_multilingual_model: str = "xx_ent_wiki_sm"  # Turkish/other NER baseline (no torch)
    anonymizer_score_threshold: float = 0.4
    # Always-mask terms for THIS project/data room (fund, portfolio-company, brand names that NER
    # can't reliably catch, e.g. "e2vc"). Comma-separated; applied deterministically every run.
    deny_terms: str = ""
    # Never-mask terms — the deny_terms mirror. GoldBench measured over-masking at 100% (24/24
    # ordinary business terms wrongly masked: "Genel Kurul", "Fatura Dönemi", "Sayfa"...); this is
    # the primary lever against it that carries ZERO recall risk (unlike discounting a whole NER
    # label, an allow-list only suppresses the SPECIFIC terms listed, never a real entity that
    # happens to share a label). `allowlist_tr.py` is the seeded Turkish business/legal/accounting
    # dictionary; this field is for project-specific ADDITIONS on top of it.
    allow_terms: str = ""
    # Master switch for every always-mask / never-mask list (`pipeline.terms.effective_terms`).
    # False = the engine receives NO list: not the seeded Turkish allow-list, not ALLOW_TERMS /
    # DENY_TERMS, not the user's Settings lists. The app keeps it on; the evaluation scorecard
    # turns it off, because every reported number is measured without lists (plan rule).
    term_lists: bool = True

    # The optional OpenAI Privacy Filter stage was moved to archive/privacy_filter/ (off by
    # default, ~38x slower per document, and no measurement used it).


    # Chat (post-approval only, layer 5 only). Default 'ollama' = fully local, no key. Claude and
    # Codex run through the user's own CLI login (Fable stores no API key); every cloud question
    # needs a send preview + consent (preview_hash) — see chat/service.py and plan §5.6.
    chat_default_provider: Literal["ollama", "claude_cli", "codex_cli"] = "ollama"
    # Aynı model denetçide de kullanılıyor: tek ağırlık kümesi bellekte kalır (3.4 GB yerine
    # 4.7 + 1.9 GB) ve qwen2.5:3b'nin ticari kullanıma kapalı Qwen Research lisansından çıkılır.
    chat_ollama_model: str = "qwen3.5:4b"
    chat_claude_model: str = ""  # "" = the CLI's own default model
    chat_codex_model: str = ""
    chat_cli_timeout_s: int = 60  # per CLI call; the process group is killed on expiry
    chat_max_message_chars: int = 4000
    # The UI's own origins, and nothing else (comma-separated). Every origin listed gets
    # credentialed API access and can read the CSRF token through CORS, so no host or port is
    # added implicitly: another local dev server (a different Vite project on 5173) is foreign.
    # The UI runs on 5174 with strictPort (frontend/vite.config.ts, start.sh).
    cors_allow_origins: str = "http://localhost:5174,http://127.0.0.1:5174"

    # Local web security (security/web.py). The app binds to 127.0.0.1; these stop other sites and
    # other local processes from driving it (DNS rebinding, CSRF).
    allowed_hosts: str = "localhost,127.0.0.1"  # comma-separated Host header values (port stripped)
    session_required: bool = True  # tests switch it off; production never should
    # Tests process uploads inside the request; the app uses the background worker.
    process_inline: bool = False

    def host_allowlist(self) -> set[str]:
        return {h.strip().lower() for h in self.allowed_hosts.split(",") if h.strip()}

    def origin_allowlist(self) -> set[str]:
        """Exactly the configured UI origins (see `cors_allow_origins`)."""
        return {o.strip() for o in self.cors_allow_origins.split(",") if o.strip()}

    @field_validator("max_iterations")
    @classmethod
    def _bound_iterations(cls, v: int) -> int:
        if not 1 <= v <= 2:
            raise ValueError("max_iterations must be between 1 and 2")
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

    def allow_list(self) -> list[str]:
        """Proje-özel ek allow-terimleri. Sabit sözlük (`allowlist_tr.py:TR_ALLOWLIST`) buna
        DAHİL DEĞİLDİR — o, dile ait sabit bir liste; bu alan yalnız proje-özel eklemeler içindir.
        İkisi `PresidioEngine.anonymize`'da birleştirilir (bkz. `pipeline/runner.py` deseni)."""
        return [t.strip() for t in self.allow_terms.split(",") if t.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()

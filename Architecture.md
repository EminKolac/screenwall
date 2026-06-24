# Architecture — Bilingual (TR/EN) Document Anonymization Platform

> Status: **Phase 1 (Scaffold + Architecture)**. This document is the design of record and
> the subject of the first Codex *Architecture Review*. Subsequent phases implement it.

## 1. Goals & Non-Goals

**Goals**
- Anonymize PDF / DOCX / XLSX documents in **Turkish, English, and mixed** content.
- Detect PII with **Microsoft Presidio** (universal + TR-specific + EN-specific recognizers).
- **Validate** anonymization with a **local** LLM privacy auditor (Qwen via Ollama).
- Enforce an **iterative loop (max 3)**; escalate to **human review** on failure.
- Allow **external LLM chat only after approval**, over **anonymized content only**.
- **Local-first**: raw documents never leave the machine before approval.

**Non-Goals**
- Reconstructing or de-anonymizing content (explicitly forbidden in the auditor prompt).
- Cloud storage of raw documents.
- OCR quality guarantees for scanned PDFs (best-effort; flagged for human review).

## 2. Core Principles

1. **Privacy by design** — separate storage layers; mapping tables never exposed; PII-safe logs.
2. **Local-only before approval** — zero external API calls until `status == APPROVED`.
3. **Deterministic placeholders** — same entity → same token across the whole document.
4. **Provider abstraction** — auditor (Ollama/MLX/llama.cpp) and chat (OpenAI/Anthropic/Azure)
   sit behind interfaces; swappable via config.
5. **Fail-closed** — anything uncertain (low confidence, parse error, scanned doc) routes to
   human review rather than silently approving.

## 3. High-Level Flow

```
Upload ─▶ Extract ─▶ Detect Language ─┐
                                      ▼
                  ┌──────── Iteration loop (max 3) ────────┐
                  │  Presidio anonymize ─▶ Qwen audit (JSON) │
                  │        ▲                     │            │
                  │        └── new rules ◀── not approved ────┤
                  └──────────────┬───────────────────────────┘
                       approved? │
                 ┌───────────────┴───────────────┐
              yes▼                              no▼ (after 3)
           APPROVED                       NEEDS_HUMAN_REVIEW
              │                                   │
   LLM chat enabled (anon only)        Human reviewer decides
```

## 4. Component Map (`backend/app/`)

| Module | Responsibility |
|---|---|
| `api/` | FastAPI routers: documents (upload/status/download), review, chat. |
| `extraction/` | `pdf.py` (PyMuPDF), `docx.py` (python-docx), `xlsx.py` (openpyxl) → `ExtractedContent`. |
| `language/` | TR/EN/mixed detection (langdetect default; fastText optional). |
| `anonymization/` | Presidio orchestration: `nlp.py` (EN spaCy + TR transformers NER), `recognizers/` (TR+EN custom), `placeholders.py` (deterministic mapping), `engine.py`. |
| `audit/` | Privacy auditor: `base.py` (LLM provider protocol), `ollama_provider.py`, `mlx_provider.py` (stub), `auditor.py` (prompt + strict JSON parse). |
| `pipeline/` | `orchestrator.py` — the iteration loop + status state machine. |
| `chat/` | Post-approval chat: provider protocol + OpenAI/Anthropic/Azure + gated `service.py`. |
| `storage/` | The 5 isolated storage layers + secure deletion. |
| `security/` | PII-safe logging filter, secure deletion helpers. |
| `models/` | Pydantic domain models + schemas (document, findings, chat). |
| `config.py` | Settings (pydantic-settings), provider selection, paths, limits. |

## 5. Data Model & State Machine

`DocumentStatus` (exact UI labels):
`UPLOADED → EXTRACTED → PRESIDIO_PASS_1 → QWEN_AUDIT_1 → PRESIDIO_PASS_2 → QWEN_AUDIT_2 →
PRESIDIO_PASS_3 → QWEN_AUDIT_3 → {APPROVED | NEEDS_HUMAN_REVIEW}`

A `Document` record tracks: `id`, `filename`, `mime`, `language`, `status`, `iterations[]`,
`current_iteration`, timestamps. Each `IterationRecord` holds the Presidio stats and the
`AuditResult` (the Qwen JSON) for that pass. Mapping tables live **only** in the extracted/
anonymized layer, never in API responses or logs.

## 6. The Five Storage Layers (isolated)

| # | Layer | Contents | Lifecycle |
|---|---|---|---|
| 1 | `original` | Raw uploaded bytes | Securely deletable; never sent to any external API. |
| 2 | `extracted` | Plain text, tables, metadata, **placeholder↔original map** | Local only. |
| 3 | `anonymized` | Anonymized text/tables (download artifact) | The only data chat may read. |
| 4 | `validation` | Qwen audit reports + iteration history | PII-safe. |
| 5 | `chat_context` | Approved anonymized context for chat | Built only post-approval. |

Each layer is addressed by `document_id`; layers never cross-reference raw PII outward.
`StorageLayer` is an interface; the Phase-1 impl is local filesystem under `data/`.

## 7. Anonymization Design

- **NLP engines**: English via spaCy (`en_core_web_lg`); **Turkish via a transformers NER**
  model (e.g. `savasy/bert-base-turkish-ner-cased`) wired through Presidio's
  `TransformersNlpEngine`. Presidio runs with a per-language engine selected from detection.
- **Custom recognizers** (regex + checksum):
  - TR: TCKN (11-digit + checksum), VKN (10-digit), GSM (+90 5xx), landline, TR-IBAN,
    vehicle plates, passport, SGK; address & company-name patterns.
  - EN: SSN, US/UK phone, passport, driver-license, address patterns.
- **Deterministic placeholders**: a per-document `PlaceholderMapper` assigns `<TYPE_n>` and
  reuses the same token for repeated values (normalized match). Mapping persists in layer 2.

## 8. Privacy Auditor (local)

- `LLMAuditProvider` protocol → `OllamaProvider` (default, Qwen2.5-7B-Instruct Q4).
  `MLXProvider`/`llama.cpp` pluggable later.
- The auditor prompt forbids de-anonymization and requires **strict JSON**:
  `{approved, risk_level, remaining_sensitive_items[], summary, recommended_next_action}`.
- Robust JSON parsing (extract first JSON object, schema-validate, fail-closed on parse error).

## 9. Iteration Loop

`max_iterations = 3`. Each iteration: anonymize → audit → parse. If `approved` → stop. Else
derive **additional rules** from `remaining_sensitive_items` (deny-list terms / new patterns)
and re-run. After 3 unapproved audits → `NEEDS_HUMAN_REVIEW`, processing stops, chat disabled.

## 10. Chat Module (gated)

Enabled **iff** `status == APPROVED`. Reads **only** layer 5 (approved anonymized context).
Never reads layers 1–2. Providers (OpenAI/Anthropic/Azure) behind a `ChatProvider` interface,
selected by config. A hard guard rejects chat calls for non-approved documents.

## 11. Security Model (summary; see SECURITY.md)

- No external calls before approval (enforced centrally).
- PII-safe logging: a logging filter redacts emails/phones/IDs; logs reference `document_id` only.
- Secure deletion of all layers on request.
- Storage isolation; mapping tables never serialized to clients.

## 12. Tech Stack

Backend: Python 3.11, FastAPI, Presidio, spaCy, transformers/torch (TR), PyMuPDF, python-docx,
openpyxl, langdetect, httpx, pydantic-settings. Auditor: Ollama. Frontend: React + Vite + TS.

## 13. Phased Roadmap & Codex Review Gates

| Phase | Deliverable | Codex review(s) |
|---|---|---|
| 1 | Scaffold + this architecture | **Architecture** |
| 2 | Extraction + language detection | (in Privacy/Backend) |
| 3 | Presidio engine + TR/EN recognizers + placeholders | **Presidio**, **TR Recognizer** |
| 4 | Qwen auditor + iteration loop + human-review escalation | **Qwen Auditor**, **Privacy** |
| 5 | Storage layers + secure deletion + PII-safe logging | **Security** |
| 6 | Chat (post-approval, anon-only, configurable) | **Backend** |
| 7 | React dashboard | **Frontend** |
| 8 | Tests + docs + production readiness | **Testing**, **Production Readiness** |

A phase does not advance until its Codex review feedback is incorporated.

## 14. Phase 1 — Codex Review Incorporated

The Codex *Architecture Review* produced 4 Critical / 9 High findings. Incorporated in Phase 1:

- **Central chat choke point** (`chat/service.py`): all external calls go through `ChatService`,
  which enforces approval + reads only storage layer 5. Direct `ChatProvider` use is disallowed.
- **Storage access policy** (`storage/base.py`): `assert_shareable()` guard + `LOCAL_ONLY_LAYERS`
  / `EXTERNALLY_SHAREABLE_LAYERS` make isolation enforceable, not just declarative.
- **Approval predicate** (`findings.AuditResult.is_clean_approval`, used by the orchestrator):
  approval requires `approved` **and** risk ≤ threshold **and** no remaining items **and**
  `next_action == approve`. Fail-closed otherwise.
- **Mapping isolation**: the placeholder↔original map is a separate artifact, excluded from
  serialization (`exclude=True`), persisted only to layer 2.
- **Span/overlap contract** (`EntitySpan` + `resolve_spans`) for deterministic replacement.
- **Richer extraction model** (stable `block_id`, page/sheet, typed `TableCell`, per-block
  `language`) + `validate_upload` (MIME/magic/size, fail-closed).
- **Per-block language routing** for mixed TR/EN documents.
- **Hardened PII logging** (formatted-message redaction; VKN/SSN/plate/spaced-IBAN/passport).
- **Config validation** (`Literal` providers, `max_iterations` bounded 1–3).
- **Persistence seam** (`PersistenceHook`) + centralized `Document.transition()`.

Deferred to their phases (tracked): per-entity canonicalizers & name-collision policy (P3),
prompt-injection-resistant auditor + deterministic residual-PII backstop (P4), atomic
crash-safe persistence impl (P5), at-rest encryption / crypto-shredding (P5).

### TR NER plan (Phase 3 benchmark, per review)
Before wiring `savasy/bert-base-turkish-ner-cased` via Presidio's `TransformersNlpEngine`:
benchmark load/latency/memory alongside Qwen on a 16GB M4; define entity-label mapping to
Presidio types; set confidence thresholds; evaluate on a TR/EN/mixed golden corpus. If memory
is tight, prefer lazy load / sequential model residency over keeping NER + Qwen hot together.

### Testing seams (start Phase 2, per review)
Golden fixtures land with extraction (P2), not P8: TR/EN/mixed PDF/DOCX/XLSX, overlap cases,
log-redaction cases, and a "no external call before approval" integration test.

## 15. Phase 2 — Codex Review Incorporated

Phase 2 (extraction + language detection) review: 0 Critical / 5 High. Incorporated:

- **Fail-closed extraction** (`ExtractionFailed`); empty/scanned output → human review, not a
  silent success (H2).
- **Bounded upload read** (413 before full buffering) + **OOXML package-part validation** +
  **zip-bomb guards** (entry count / uncompressed size / compression ratio) (H1, H3).
- **Per-block language** persists tr/en/**mixed/unknown**; Phase 3 routes mixed/unknown blocks
  through both recognizer sets (H5).
- **PDF reading order** (blocks merged + sorted by y,x) with **bbox** captured; table-finder
  failures recorded as sanitized `warnings` on the output, never logged (H4 partial, L3).
- **Sparse table rendering** (no dense-grid allocation) (M3); typed reject codes → 413/415/400/422 (L1).
- **32 tests** incl. negative cases: corrupt OOXML, empty/scanned PDF, sparse XLSX, API rejects.

Deferred to the reconstruction phase (the `Block` model already carries bbox + cell addresses so
these need no re-extraction): full in-place PDF/DOCX edit fidelity, merged-cell span tracking,
XLSX formula/format retention (H4-reconstruction, M1, M2).

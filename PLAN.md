# Project Plan — Bilingual (TR/EN) Document Anonymization Platform

## Context

This platform anonymizes Turkish/English legal & financial documents (PDF/DOCX/XLSX) locally,
validates the result, and only enables external LLM chat after approval. It began as ad-hoc
Presidio anonymization of a legal due-diligence report and was built into a **production-grade,
local-first platform** across 8 phases. The system is **built and verified**: 54 backend tests
pass, the frontend builds, a live end-to-end run is proven, and 3 Codex reviews were incorporated.

This document is the **canonical plan / blueprint of the whole project** — what it is, how it is
structured, how it runs, what was verified, and what remains for hardened deployment. It is the
single onboarding/handoff reference.

---

## 1. Goals & Scope

**In scope (delivered):** PDF/DOCX/XLSX upload → structure-preserving extraction → TR/EN/mixed
language detection → Microsoft Presidio anonymization (universal + TR + EN recognizers,
deterministic `<TYPE_n>` placeholders) → iterative validate/anonymize loop (max 3) with a local
auditor → human-review escalation → external LLM chat **only after approval, over anonymized
content only** → React dashboard. Local-first, privacy-by-design.

**Out of scope / deferred:** multi-tenant auth, at-rest encryption/crypto-shredding, rate limiting,
background job queue (documented in `SECURITY.md §7` as required before network-exposed deployment).

---

## 2. Architecture

```
Upload ─▶ Validate (magic/size/OOXML/zip-bomb) ─▶ Extract (struct-preserving) ─▶ Detect lang ─┐
                                                                                              ▼
                          ┌──────── Iteration loop (max 3) ────────────────────────┐
                          │  Presidio anonymize (EN+TR, deterministic placeholders) │
                          │            │                                            │
                          │            ▼                                            │
                          │  Audit = Heuristic backstop  AND  (Qwen/Ollama if up)   │
                          │            │ clean? ──no──▶ feed raw_terms, re-anonymize │
                          └────────────┼────────────────────────────────────────────┘
                               clean?  │
                       ┌───────────────┴───────────────┐
                    yes▼                              no▼ (after 3)
                  APPROVED                     NEEDS_HUMAN_REVIEW ─▶ reviewer approve/reject/redact
                     │                                                        │ approve
            chat (anonymized only) ◀───────────────────────────────────────────┘
```

**Core principles:** privacy-by-design · local-only before approval (zero external calls) ·
deterministic placeholders · provider abstraction (auditor + chat) · **fail-closed** (any
uncertainty → human review).

### State machine (`app/models/document.py`)
`UPLOADED → EXTRACTED → PRESIDIO_PASS_1 → QWEN_AUDIT_1 → … _2 → … _3 → {APPROVED | NEEDS_HUMAN_REVIEW}`
(enum values are machine-stable codes; UI labels are a separate display map).

### Five isolated storage layers (`app/storage/base.py`, `app/storage/local.py`)
1 `original` (raw) · 2 `extracted` (+ placeholder↔original mapping) · 3 `anonymized` · 4 `validation`
(PII-safe reports) · 5 `chat_context`. Layers 1–2 are local-only (`LOCAL_ONLY_LAYERS`); only layer
5 is `EXTERNALLY_SHAREABLE`. `assert_shareable()` guards every outbound path.

### Security model (`SECURITY.md`)
No external call before approval · raw docs never leave the machine · chat reads layer 5 only
(single choke point `app/chat/service.py`, user messages length-capped + PII-redacted) · PII-safe
logging (`app/security/logging.py`) · mapping excluded from all serialization · secure deletion of
all layers.

---

## 3. Tech Stack

- **Backend:** Python 3.11/3.12 (uv), FastAPI, Presidio (analyzer+anonymizer), spaCy
  (`en_core_web_sm` + `xx_ent_wiki_sm`), PyMuPDF, python-docx, openpyxl, langdetect, httpx,
  pydantic-settings. Optional extras: `[tr]` (transformers+torch), `[chat]` (openai+anthropic).
- **Local auditor:** Ollama + Qwen2.5-7B-Instruct-Q4 (optional; heuristic backstop runs without it).
- **Frontend:** React 18 + Vite 5 + TypeScript (no heavy UI lib; dark CSS dashboard).

---

## 4. Phase Plan (delivered) & Codex review gates

| Phase | Deliverable | Codex review |
|---|---|---|
| 1 | Scaffold + architecture (interfaces, 5-layer storage, state machine, config, PII logging) | **Architecture** ✓ (4 CRIT/9 HIGH → fixed: chat choke point, storage guard, clean-approval predicate, mapping isolation, span contract, richer extraction model) |
| 2 | Extraction (PDF/DOCX/XLSX) + language detection + golden fixtures/tests | **Phase-2** ✓ (5 HIGH → fixed: fail-closed extraction, bounded read + zip-bomb, per-block mixed/unknown lang, PDF reading order+bbox, sparse-table DoS) |
| 3 | Presidio engine + TR/EN custom recognizers + deterministic placeholders + per-block routing | (covered by prod review) |
| 4 | Local Qwen auditor (Ollama) + heuristic backstop + composite + iteration loop + human review | (covered by prod review) |
| 5 | 5 storage layers + secure deletion + storage-backed repository + PII-safe logging wired | (covered by prod review) |
| 6 | Chat module (post-approval, anonymized-only, OpenAI/Anthropic/Azure configurable) | (covered by prod review) |
| 7 | React dashboard (upload, status flow, findings, anonymized preview, review, chat) | (covered by prod review) |
| 8 | Docs (API/TESTING/DEPLOYMENT) + production-readiness review + fixes | **Production-Readiness** ✓ (CRIT/HIGH privacy+correctness → fixed; deployment hardening documented) |

---

## 5. Component / File Map (critical files)

**Pipeline & models**
- `app/pipeline/orchestrator.py` — the max-3 anonymize/audit loop + `PipelineResult`.
- `app/pipeline/runner.py` — ingest → loop → persist; chat context built only on approval; fail-closed.
- `app/models/document.py` — `Document`, `DocumentStatus` (+display), `transition()`.
- `app/models/findings.py` — `AuditResult.is_clean_approval()`, fail-closed JSON parse, PII-safe snippets, excluded `raw_terms`.

**Anonymization (`app/anonymization/`)**
- `nlp.py` — cached Presidio `AnalyzerEngine` (EN sm + multilingual; NER label mapping).
- `presidio_engine.py` — per-block EN+TR analysis, `resolve_spans` overlap resolution, deterministic placeholder application (analyzer access locked).
- `placeholders.py` — `PlaceholderMapper` (NFKC-normalized, deterministic).
- `recognizers/turkish.py` — TCKN (checksum), VKN, GSM, landline, TR-IBAN, plate, passport.
- `recognizers/english.py` — UK phone, passport, context-gated SSN/DL.
- `engine.py` — interface + `EntitySpan` + `resolve_spans` (priority-based, prevents partial-PII leak).

**Audit (`app/audit/`)** — `factory.py` (composite: heuristic AND clean LLM; `require_llm_auditor`),
`heuristic.py` (deterministic residual-PII scan, fail-closed), `ollama_provider.py`, `auditor.py`, `base.py`.

**Extraction (`app/extraction/`)** — `base.py` (typed `Block`/`TableCell`, `validate_upload`),
`dispatcher.py`, `pdf.py`, `docx.py`, `xlsx.py` (cell-capped). `app/language/detector.py` (TR/EN/mixed).

**Storage & services** — `app/storage/base.py` (+`assert_shareable`), `app/storage/local.py` (atomic
writes, secure delete), `app/services/storage_repository.py` (5-layer repo),
`app/services/repository.py` (seam + in-memory), `app/services/ingest.py`, `app/services/deps.py`.

**Chat (`app/chat/`)** — `service.py` (single choke point), `base.py` (gate), `providers.py` (lazy
SDKs), `factory.py`.

**API (`app/api/`)** — `documents.py` (upload/list/detail/anonymized/findings/delete),
`review.py` (pending/approve/reject/redact), `chat.py` (gated). `app/main.py` (routers, CORS from
settings, lifespan + PII logging). `app/config.py` (validated settings).

**Frontend (`frontend/src/`)** — `App.tsx`, `api.ts`, `types.ts`, `components/{UploadPanel,
DocumentList, DocumentDetail, ChatPanel, StatusBadge, StatusFlow}.tsx`, `styles.css`.

---

## 6. API Surface (see `docs/API.md`)
`GET /health` · `GET /api/statuses` · `POST /api/documents` (full pipeline) · `GET /api/documents` ·
`GET /api/documents/{id}` · `GET /api/documents/{id}/anonymized` (approved-only) ·
`GET /api/documents/{id}/findings` · `DELETE /api/documents/{id}` · `GET /api/review/pending` ·
`POST /api/review/{id}/{approve|reject|redact}` · `POST /api/chat/{id}` (approved-only).

---

## 7. Testing & Verification

- **54 backend tests** (`uv run pytest -q`): extraction, language, anonymization (incl. TCKN
  checksum, IBAN no-partial-leak, determinism), storage isolation/secure-delete, chat gate, ingest,
  pipeline API, review API, chat API, robustness (corrupt OOXML, empty PDF, sparse XLSX, rejects).
  Isolated temp `STORAGE_ROOT` per test (`tests/conftest.py`).
- **Frontend:** `npm run build` (tsc typecheck + vite) clean.
- **Live E2E (proven):** mixed TR+EN upload → `approved` → output fully masked
  (`<PERSON_>/<TCKN_>/<EMAIL_>/<IBAN_>/<PHONE_>`), zero PII leak on grep check.

**To re-verify end-to-end:**
```bash
cd ~/anonymizer-platform/backend && uv run pytest -q          # 54 passed
cd ~/anonymizer-platform/frontend && npm run build            # builds
# live: uvicorn app.main:app & ; POST a .docx to /api/documents ; GET /{id}/anonymized
```

---

## 8. Run & Optional Upgrades (see `docs/DEPLOYMENT.md`)

```bash
# Backend (works out of the box: heuristic auditor + multilingual NER, no LLM/torch needed)
cd ~/anonymizer-platform/backend && uv sync
uv run python -m spacy download en_core_web_sm && uv run python -m spacy download xx_ent_wiki_sm
uv run uvicorn app.main:app --reload
# Frontend
cd ~/anonymizer-platform/frontend && npm install && npm run dev
```
Optional full-power: `bash scripts/setup_macos.sh` (Ollama + Qwen) · `uv sync --extra tr` +
`USE_TRANSFORMERS_TR=true` (Turkish BERT NER) · `SPACY_EN_MODEL=en_core_web_lg` ·
`uv sync --extra chat` + API key.

---

## 9. Deferred — Production Hardening (before multi-tenant / exposed deployment)
Auth/authz on all routes · at-rest encryption + crypto-shredding (layers 1–2) · rate limiting +
chat token caps · durable signed audit trail · background job queue + transactional manifest.
(Tracked in `SECURITY.md §7`.)

---

## 10. Definition of Done — status
PDF/DOCX/XLSX ✓ · TR/EN/mixed anonymization ✓ · Presidio ✓ · auditor + max-3 iterations ✓ ·
human review ✓ · approved download ✓ · chat anonymized-only ✓ · 54 tests pass ✓ · docs complete ✓ ·
production-readiness review run, code-level criticals fixed, deployment items documented ✓.
**Optional upgrades (Ollama Qwen, transformers TR) are one-command and documented.**

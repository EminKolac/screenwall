# Security Model

> **Note (2026-10-07):** most of this document was written for v1 and is kept as a record. The
> guarantees in §2 still hold, but several details changed; where this file and the code
> disagree, the code wins. Current state:
>
> - **Single user, one computer.** The server binds to `127.0.0.1`. Every `/api` route except
>   session and health needs a session cookie, every mutating request a CSRF token, and Host and
>   Origin must be on allow-lists (`backend/app/security/web.py`). This keeps other web pages
>   out; it is not a multi-user login. Never expose the port on a network.
> - **Other accounts on the same computer.** `127.0.0.1` is shared by every account. In the
>   packaged app the launcher writes a per-start launch token to `SCREENWALL_HOME/launch-token`
>   (owner-only) and the server issues a new session only with it (`X-Launch-Token`,
>   `backend/app/api/system.py`, `config.py` `launch_token`), so another account cannot open a
>   session. Programs running as the same user can read that file and the data folder, so they
>   are not kept out. Development mode (`start.sh`) has no launch token.
> - **Approval needs the local LLM.** A document is approved only after a successful audit by
>   the local Qwen model through Ollama; without it every document waits in review and manual
>   approval returns 503 (`pipeline/runner.py` `route`, `review/approval.py`).
> - **Chat providers:** local Ollama (default) and, optionally, the user's own Claude Code or Codex
>   CLI login. There are no OpenAI/Anthropic/Azure SDK providers and **Screenwall stores no API
>   key**. Every cloud question shows the exact outgoing text first and is sent only with the
>   user's consent (`preview_hash`); each send is logged without content in
>   `STORAGE_ROOT/chat_dispatches.jsonl` (`backend/app/chat/service.py`, `chat/dispatches.py`).
>   The CLI providers are disabled on Windows.
> - The optional OpenAI Privacy Filter stage is retired (`archive/privacy_filter/`).
> - The v1 review endpoints (`/api/review/*`) are gone; see `docs/API.md`.
>
> Current documentation: `README.md`, `docs/DEPLOYMENT.md`, `docs/API.md`, `docs/SCORECARD.md`.

Privacy-by-design is the central requirement of this platform. This document is the subject of
the Codex **Security** and **Privacy** reviews.

## 1. Threat model

- **Primary risk**: PII / confidential data leaking off the machine, into logs, into an external
  LLM, or to another user's document context.
- **Trust boundary**: the local machine. External LLM providers are *untrusted* and only ever
  receive **approved, anonymized** content.

## 2. Hard guarantees

1. **No external API calls before approval.** A central guard blocks all outbound provider calls
   unless the document's `status == APPROVED`. Every detection/audit model runs **on-device**:
   spaCy and the auditor (Qwen via Ollama on this computer). A remote `OLLAMA_BASE_URL` is refused
   unless `OLLAMA_ALLOW_REMOTE=true`; Ollama cloud models are always refused
   (`backend/app/security/ollama.py`). (The optional Privacy Filter stage described here before
   is retired to `archive/privacy_filter/`.)
2. **Raw documents never leave the machine.** Layers 1–2 (original + extracted, incl. mapping
   tables) are local-only and never serialized to clients or sent to any provider.
3. **Chat reads anonymized content only** (storage layer 5), never layers 1–2. Enforced
   centrally by `chat.service.ChatService` (the single outbound choke point) plus
   `storage.assert_shareable()`; application code may not call a chat provider directly.
4. **PII-safe logging.** A logging filter redacts emails, phone numbers, national IDs, IBANs and
   similar before any log line is written. Logs reference `document_id`, never raw values.
5. **Secure deletion.** Every storage layer for a document can be deleted on request. Note: on
   SSD/APFS, overwriting files is **not** a reliable erase primitive — the production guarantee is
   **crypto-shredding** (sensitive layers encrypted at rest; deletion destroys the key). Planned
   in Phase 5; until then, deletion unlinks all layers for a document id.

## 2a. Two anonymization modes — pseudonymization vs. anonymization

The system offers two modes, selectable per upload (`mode` field on `POST /api/documents`,
default from `Settings.anonymization_mode`):

| | `mapping` (default) | `destructive` |
|---|---|---|
| Layers 1–2 (original + extracted/mapping) | **persisted** | **never written** |
| Reversible by whoever holds layer 2? | **Yes** | **No** |
| Human review can compare against source? | Yes | No |
| A missed entity can be corrected in place? | Yes (redact + re-audit) | No — re-upload required |

**Terminology matters here.** In `mapping` mode the placeholder↔original map exists on disk, so the
output is **pseudonymized**, not anonymized: under KVKK/GDPR it remains personal data for as long as
that map exists, because it is reversible by anyone who can read layer 2. Only `destructive` mode —
where layers 1–2 are never written at all, not written-then-deleted — produces output that can
accurately be called anonymized. `mapping` mode is not a weaker security posture; it is a different,
explicit product choice (reversibility for review/correction), and it must not be described as
"anonymization" in user-facing copy or reports.

`destructive` mode's trade-off: because nothing to compare against is ever persisted, a human
reviewer sees only the anonymized text (never the source), and a false negative discovered later
cannot be patched through review decisions — `POST /api/documents/{id}/decisions` needs layer 2 and
returns 409 `original_not_stored` in destructive mode. The remedy is re-uploading the original file, which the user must still hold
themselves.

## 3. Storage isolation (5 layers)

| Layer | Sensitivity | Leaves machine? |
|---|---|---|
| 1 original | Highest (raw) | Never |
| 2 extracted (+ mapping) | Highest | Never |
| 3 anonymized | Low (de-identified) | Download only |
| 4 validation reports | Low (PII-safe) | Never (internal) |
| 5 chat context | Low (anonymized) | To chat provider **after approval only** |

## 4. Auditor safety

The Qwen auditor prompt **forbids de-anonymization**: it must only *report* residual PII, never
reconstruct or guess hidden values. Output is strict JSON; parse failures **fail closed**
(treated as not-approved → human review).

## 5. Secrets

Screenwall stores no provider API key. Cloud chat runs through the user's own Claude Code or Codex
CLI login (`claude auth login`, `codex login`), and only for approved documents, one consented
question at a time. `backend/.env` (git-ignored) holds settings, not secrets; never put
credentials in code, logs or the repository.

## 6. Open items (tracked through later phases)

- At-rest encryption for layers 1–2 + **crypto-shredding** as the deletion guarantee (Phase 5).
- Audit trail signing for human-review actions.
- Configurable retention / auto-purge policy.
- Prompt-injection-resistant auditor prompt + deterministic residual-PII backstop scan (Phase 4).
- Per-entity canonicalizers and a documented name-collision policy for placeholders (Phase 3).

## 7. Production-readiness review — fixed vs. deferred

A Codex production-readiness + security review was run on the completed build.

**Fixed in code:**
- Composite auditor requires the LLM's full clean-approval predicate (not just `approved=true`),
  and `REQUIRE_LLM_AUDITOR=true` removes the silent fail-open when Ollama is down.
- Anonymized output is **not downloadable before approval** (403); audit findings store only a
  non-identifying length hint, never raw snippets.
- User chat messages are length-capped and PII-redacted before any external call.
- Anonymization/auditor failures **fail closed** to human review (no under-anonymized approvals);
  manual approval re-audits, and redaction invalidates the chat context + de-approves.
- Atomic storage writes (temp + `os.replace`); analyzer access serialized with a lock; heavy
  pipeline runs in a threadpool; CORS origins are configurable; XLSX extraction is cell-capped.

**Deferred — required before multi-tenant / network-exposed deployment (this is a local,
single-user tool by design):**
- **Authentication & authorization** on all routes (review/delete/chat especially) + per-document
  ownership and a reviewer role.
- **Encryption at rest** for layers 1–2 with per-document keys in the OS keychain/KMS, enabling
  **crypto-shredding** as the true deletion guarantee (SSD overwrite is best-effort).
- **Rate limiting**, upload concurrency caps, and chat token caps (provider-cost / DoS protection).
- **Durable, signed audit trail** for review decisions and external chat calls (actor, reason,
  context hash, provider metadata).
- A background **job queue** for processing and a transactional **manifest** across the 5 layers.

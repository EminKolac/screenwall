# Security Model

Privacy-by-design is the central requirement of this platform. This document is the subject of
the Codex **Security** and **Privacy** reviews.

## 1. Threat model

- **Primary risk**: PII / confidential data leaking off the machine, into logs, into an external
  LLM, or to another user's document context.
- **Trust boundary**: the local machine. External LLM providers are *untrusted* and only ever
  receive **approved, anonymized** content.

## 2. Hard guarantees

1. **No external API calls before approval.** A central guard blocks all outbound provider calls
   unless the document's `status == APPROVED`. The auditor (Qwen) runs **locally** (Ollama).
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

Provider API keys live in `.env` (git-ignored) / environment, never in code or logs. Keys are
loaded only by the chat module and only used post-approval.

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

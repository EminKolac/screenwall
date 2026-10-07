# API reference (v2)

The authoritative contract is [`frontend/src/api/contract.ts`](../frontend/src/api/contract.ts):
the backend (`backend/app/api/`, `backend/app/chat/schemas.py`) mirrors those shapes. This page
is a short map of it, checked against the code on 2026-10-07. The v1 API described here before
(`/api/statuses`, `/findings`, `/api/review/*`, a synchronous upload) no longer exists.

The API is for the app's own UI on the same computer. It is not a public or network API.

## Conventions

- Base URL: the server's own origin. Development: `http://127.0.0.1:8000` (the UI on 5174
  proxies `/api`). Packaged app: `http://127.0.0.1:8765`.
- JSON everywhere, except the upload (multipart), page images (PNG), the masked text
  (`text/plain`) and the download (PDF).
- Errors: an HTTP 4xx/5xx status with the body `{"detail": "<ErrorCode>"}`. The codes are the
  `ErrorCode` union in `contract.ts`; the UI maps them to Turkish sentences. Error bodies never
  echo request input, exception text or CLI output. A malformed body gives `422` with
  `{"detail": [{"loc": [...], "type": "..."}]}` (positions and types only, no values).
- No endpoint returns the placeholder-to-value mapping. Original text is returned only by the
  review payload, only in `mapping` mode.
- `/api/*` responses carry `Cache-Control: no-store`.

## Security handshake (do this first)

Every request is checked by `backend/app/security/web.py` before routing:

1. The `Host` header must be in `ALLOWED_HOSTS` (default `localhost`, `127.0.0.1`; port ignored),
   otherwise `403 host_not_allowed`.
2. A present `Origin` header must be in `CORS_ALLOW_ORIGINS`, otherwise `403 origin_not_allowed`.
   `Sec-Fetch-Site: cross-site` is refused with `403 cross_site_not_allowed`.
3. `GET /api/session` returns `{"csrf_token": "..."}` and sets the HttpOnly, SameSite=Strict
   cookie `fable_session` (path `/api`, 12 hours). When the server has a launch token (the
   packaged app, `LAUNCH_TOKEN_FILE`), a new session also needs the header
   `X-Launch-Token: <token>`, otherwise `401 launch_token_required`; a request with a live
   session cookie keeps its session without it. The launcher puts the token in the address it
   opens (`/#k=<token>`) and the UI sends it from there.
4. Every other `/api/*` route needs that cookie, otherwise `401 session_required`.
5. Every POST, PUT, PATCH and DELETE also needs the header `X-CSRF-Token: <csrf_token>`,
   otherwise `403 csrf_failed`.
6. Bodies are capped before parsing: uploads at `MAX_UPLOAD_MB` + 1 MB, other bodies at 256 KB
   (`413 file_too_large`).

`/health`, `/api/health` and `/api/session` need no session.

## System

| Method | Path | Result |
|---|---|---|
| GET | `/health` | `{status: "ok"}` (liveness only) |
| GET | `/api/health` | `{status, auditor: {provider, model, reachable}, ocr: {available}, worker: {alive}}` |
| GET | `/api/session` | `{csrf_token}` + session cookie |
| GET | `/api/settings` | `AppSettings`: `default_mode`, `chat_default_provider`, `always_mask`, `never_mask` |
| PUT | `/api/settings` | partial update, returns `AppSettings` |

## Documents

Processing is asynchronous: an upload is queued and a background worker moves it through
`queued → extracting → masking → auditing →` `approved` or `needs_review` (or `failed`).
`rejected` is a reviewer's decision. Poll `GET /api/documents/{id}`.

| Method | Path | Result |
|---|---|---|
| GET | `/api/documents` | `{documents: DocumentSummary[]}`, newest first |
| POST | `/api/documents` | multipart `file`, optional `mode` (`mapping` or `destructive`) → `202 DocumentSummary`. `413 file_too_large`, `415 unsupported_file_type`, `400 invalid_file` |
| GET | `/api/documents/{id}` | `DocumentSummary` |
| DELETE | `/api/documents/{id}` | `204`; removes every storage layer. `409 document_busy` while extracting, masking or auditing |
| GET | `/api/documents/{id}/masked` | masked plain text; `needs_review` or `approved` only (`409 not_in_review`) |
| GET | `/api/documents/{id}/download` | PDF rendered from the masked text only; `approved` only (`403 not_approved`) |

`DocumentSummary` carries `status`, `revision`, `counts.masked`, `counts.pending`, `reasons`
(code + Turkish text, e.g. `auditor_unavailable`) and `can.{review, approve, download, chat,
decide}`.

## Review

| Method | Path | Result |
|---|---|---|
| GET | `/api/documents/{id}/review` | `ReviewPayload`: `document`, `units`, `spans`, `items`, `pages` |
| GET | `/api/documents/{id}/pages/{n}` | page image (PNG); PDF in `mapping` mode only (`409 original_not_stored`) |
| GET | `/api/documents/{id}/pages/{n}/marks` | span rectangles for that page |
| POST | `/api/documents/{id}/decisions` | `{op, target, scope, expected_revision}` → `ReviewPayload` |
| POST | `/api/documents/{id}/approve` | `{expected_revision}` → `DocumentSummary` |
| POST | `/api/documents/{id}/reject` | `{reason}` → `DocumentSummary`; the reason is masked before it is stored |

Decisions: `op` is `mask`, `unmask` or `keep`; `scope` is `occurrence`, `document` or `global`
(the global lists in Ayarlar); `target` is a span id, an item id or a new selection
`{unit_id, start, end, family}`. Offsets are Unicode code point indices. A stale
`expected_revision` gives `409 stale_revision`.

Approval is fail-closed (`backend/app/review/approval.py`):

- `409 not_in_review`, `409 stale_revision`, `409 no_content`
- `409 unresolved_items`: open items remain (also when a fresh audit just located a residual)
- `409 audit_not_clean`: a fresh audit found something; look again, then approve again
- `503 ollama_unreachable`: the content has not been audited by a working LLM in its current
  form and Ollama is not available; nothing is approved

## Chat

Chat works only for `approved` documents and reads only their masked chat context.

| Method | Path | Result |
|---|---|---|
| GET | `/api/chat/providers` | `{default, providers: ProviderStatus[]}` (`ollama`, `claude_cli`, `codex_cli`) |
| POST | `/api/chat/preview` | `{doc_ids, question, provider, history}` → `{provider, preview_hash, destination, sources, sent_text, context_chars}`; no provider is called |
| POST | `/api/chat` | the same body plus `preview_hash` → `{answer, citations}` |

For the cloud providers (`claude_cli`, `codex_cli`) `POST /api/chat` needs the `preview_hash`
of a preview with exactly the same provider, model, documents and text: `409 preview_required`
or `409 preview_mismatch` otherwise. `sent_text` is the exact text that would leave the
computer. Other errors: `403 chat_not_allowed` (not approved), `404 document_not_found`, `503`
for an unavailable provider (`provider_unavailable`, `ollama_unreachable`, `model_missing`,
`cli_not_found`, `cli_login_required`, `cli_upgrade_required`), `502` for a failed call
(`cli_timeout`, `cli_failed`, `cli_output_limit`, `cli_unsafe_output`, `invalid_citations`).
Screenwall is released for macOS only; should the backend run on Windows (from source), the CLI
providers report the status problem `unsupported_os` and refuse requests with
`503 provider_unavailable`.

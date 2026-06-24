# API Reference

Base URL: `http://localhost:8000`. All payloads are JSON unless noted. Responses are PII-safe:
the original file, extracted text, and the placeholder mapping are never returned.

## Health & metadata

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Service health + auditor/config summary |
| GET | `/api/statuses` | Processing state machine: `[{value, label}]` |

## Documents

### `POST /api/documents`
Upload a file (multipart `file`). Runs the full pipeline: validate → extract → detect language →
anonymize/audit loop (max 3). Returns a summary.

- **413** file too large · **415** unsupported type · **400** invalid/corrupt · **422** unparsable.
- **200** body:
```json
{ "id": "…", "filename": "x.docx", "kind": "docx", "language": "mixed",
  "status": "approved", "status_label": "Approved", "iterations": 1,
  "approved": true, "chat_enabled": true, "risk_level": "low", "has_anonymized": true }
```

| Method | Path | Description |
|---|---|---|
| GET | `/api/documents` | List all documents (summaries) |
| GET | `/api/documents/{id}` | Full detail: status, iterations, audit findings (PII-safe) |
| GET | `/api/documents/{id}/anonymized` | Anonymized plain text (download) |
| GET | `/api/documents/{id}/findings` | Iteration history + audit findings |
| DELETE | `/api/documents/{id}` | Securely delete all 5 storage layers for the document |

## Human review

| Method | Path | Description |
|---|---|---|
| GET | `/api/review/pending` | Documents in `needs_human_review` |
| POST | `/api/review/{id}/approve` | Approve → builds anonymized chat context (layer 5) |
| POST | `/api/review/{id}/reject` | Keep in human review |
| POST | `/api/review/{id}/redact` | Re-anonymize with extra deny terms: `{ "terms": ["…"] }` |

## Chat (gated)

### `POST /api/chat/{id}`
Enabled **only** when the document is `approved`. Reads only the anonymized chat context.
- Body: `{ "messages": [{ "role": "user", "content": "…" }] }`
- **403** if the document is not approved · **404** unknown · **502** provider error.
- **200**: `{ "answer": "…" }`

# Testing

> **Note (2026-10-07):** the coverage table below describes an earlier version (93 tests, v1
> API). Two of the files it names (`integration/test_review_api.py`, `integration/test_chat_api.py`)
> no longer exist. Current state: 879 backend tests pass, 2 skipped (`uv run pytest -q`), and 79
> frontend tests pass in 11 files (`npx vitest run`), measured on 2026-10-07. For what the
> numbers in the README mean, see [SCORECARD.md](SCORECARD.md); for the code under test, read
> `backend/tests/` and `frontend/src/**/*.test.ts(x)` directly.
>
> Current commands, from the repository root:
>
> ```bash
> make test                                  # backend pytest + frontend vitest
> cd frontend && npm run typecheck           # tsc
> cd frontend && npm run e2e                 # Playwright + axe against a mock backend
> PARITY=1 uv run pytest tests/parity        # in backend/: detection parity (slow, see below)
> ```
>
> Two tests are skipped by default: the parity test (needs `PARITY=1`; it also reads the local
> benchmark corpus `FABLE_BENCH_CORPUS` and real documents that are not in the repository) and
> RedactionBench (needs its downloaded data). Tests that depend on POSIX file modes or the fake
> CLI are marked in `backend/tests/posix_only.py` and skip on Windows (kept, although Screenwall
> is released for macOS only). CI (`.github/workflows/ci.yml`) runs the backend suite on Ubuntu
> and macOS and the frontend typecheck, vitest and build. Ruff is not clean yet and is not part
> of CI. The release zip is smoke-tested separately on Apple Silicon and Intel macOS runners
> (`.github/workflows/release.yml`, `packaging/smoke_test.py`).

## Run

```bash
cd backend
uv run pytest -q            # full suite
uv run pytest tests/unit    # unit only
uv run ruff check app       # lint
```

Each test runs against an isolated temp `STORAGE_ROOT` (autouse fixture in `tests/conftest.py`),
so the suite never touches `./data`.

## Coverage (93 tests)

| Area | File | What it verifies |
|---|---|---|
| Extraction | `unit/test_extraction.py` | DOCX headings/tables, XLSX cells+addresses, PDF text+page |
| Upload validation | `unit/test_upload_validation.py` | extension/magic/size, OOXML, fail-closed |
| Language | `unit/test_language.py` | TR / EN / mixed, per-block annotation |
| Anonymization | `unit/test_anonymization.py` | TCKN checksum, span overlap trust-tiering (pattern beats statistical NER — no partial IBAN/phone leak), determinism, deny terms, mapping-not-serialized, per-stage `by_source` |
| Privacy Filter (retired, `archive/privacy_filter/`) | `archive/privacy_filter/test_privacy_filter.py` | label folding (54-label + original taxonomy → platform types), exclude-list, threshold, SENSITIVE fallback, degrade vs fail-closed load paths, `<PERSON_n>` family unity through the engine |
| Eval seam | `unit/test_eval.py` | detection precision/recall scoring harness |
| PDF render | `unit/test_render_pdf.py` | layer-3-only PDF, Turkish glyphs, OCR fallback behavior |
| Storage | `unit/test_storage.py` | 5-layer round-trip, secure delete, outbound guard |
| Chat gate | `unit/test_chat_gate.py` | approval gate, layer-5-only |
| API surface | `integration/test_api.py` | routes, error codes |
| Ingest | `integration/test_ingest.py` | validate→extract→detect end-to-end |
| Pipeline API | `integration/test_pipeline_api.py` | upload→anonymize→download/findings/delete, no PII leak |
| Download PDF | `integration/test_download_pdf.py` | layer-3-only export, RFC 5987 filename, 403 before approval |
| Review API | `integration/test_review_api.py` | pending → approve (chat context) / reject |
| Chat API | `integration/test_chat_api.py` | 403 for non-approved, success reads only anonymized |
| Robustness | `integration/test_robustness.py` | corrupt OOXML, empty/scanned PDF, sparse XLSX, API rejects |

## Fixtures

`tests/conftest.py` synthesizes TR / EN / mixed DOCX & XLSX (full Unicode) and English PDFs.
(Synthetic PDFs use base-14 fonts which cannot embed Turkish glyphs; real Turkish PDFs extract
fine, so TR/mixed detection is exercised via DOCX/XLSX.)

## Frontend

```bash
cd frontend
npm run build      # tsc typecheck + vite production build
```

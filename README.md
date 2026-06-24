# Bilingual Document Anonymization Platform

Production-grade platform that anonymizes **PDF / DOCX / XLSX** documents in **Turkish, English,
and mixed** content using **Microsoft Presidio**, validates the result with a **local Qwen**
privacy auditor, and only enables **external LLM chat after approval** — over anonymized content.

> **Local-first & privacy-by-design.** Raw documents never leave the machine before approval.

## Status

Built in phases, each gated by a **Codex** review. See [Architecture.md](Architecture.md) §13.
Current: **Phase 1 — Scaffold + Architecture**.

## How it works

```
Upload → Extract → Detect language → [Presidio anonymize → Qwen audit] ×(max 3)
       → Approved → LLM chat (anonymized only)   |   Needs Human Review → reviewer decides
```

## Repository layout

```
backend/        FastAPI service (extraction, anonymization, audit, pipeline, chat, storage)
frontend/       React + Vite dashboard (Phase 7)
data/           Runtime storage — 5 isolated layers (git-ignored)
docs/           API.md, TESTING.md, DEPLOYMENT.md
scripts/        setup_macos.sh (Ollama, model pull, env)
Architecture.md / SECURITY.md
```

## Quick start (MacBook Air M4 16GB)

Works out of the box with lightweight models (no LLM required — a deterministic heuristic auditor
runs the loop). Optional upgrades (Ollama Qwen, transformers TR NER) in [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).

```bash
# Backend
cd backend
uv sync
uv run python -m spacy download en_core_web_sm
uv run python -m spacy download xx_ent_wiki_sm
uv run uvicorn app.main:app --reload          # http://localhost:8000

# Frontend (new terminal)
cd frontend
npm install && npm run dev                     # http://localhost:5173

# Optional: enable the local Qwen auditor
bash scripts/setup_macos.sh                    # installs Ollama + pulls the Qwen model
```

Health: `curl localhost:8000/health`. API: [docs/API.md](docs/API.md). Security: [SECURITY.md](SECURITY.md).
Testing: [docs/TESTING.md](docs/TESTING.md).

## Configuration

Copy `.env.example` → `.env`. Key settings: auditor provider/model, chat provider + API keys
(used **only after approval**), storage root, max upload size, `MAX_ITERATIONS=3`.

# Deployment & Setup (MacBook Air M4 16GB)

The platform runs **locally** by default. It works out of the box with lightweight models; the
heavy LLM/NER pieces are opt-in upgrades.

## Prerequisites

- **Python 3.11–3.12** via [uv](https://docs.astral.sh/uv/)
- **Node.js 18+** (for the frontend)
- **Ollama** (optional, for the local Qwen auditor) — https://ollama.com/download

## 1. Backend

```bash
cd backend
uv sync                                   # base deps (FastAPI, Presidio, spaCy, …)
uv run python -m spacy download en_core_web_sm
uv run python -m spacy download xx_ent_wiki_sm
uv run uvicorn app.main:app --reload      # http://localhost:8000
```

Out of the box: bilingual anonymization (English spaCy + multilingual NER + custom TR/EN
recognizers) and the **deterministic heuristic auditor** (no LLM required). The iteration loop,
human review, storage layers, and gated chat all work.

## 2. Frontend

```bash
cd frontend
npm install
npm run dev                               # http://localhost:5173 (proxies /api → :8000)
```

## 3. Full-power upgrades (optional)

| Upgrade | Why | How |
|---|---|---|
| **Local Qwen auditor** | LLM-grade residual-PII detection on top of the heuristic | `bash scripts/setup_macos.sh` (installs Ollama, pulls `qwen2.5:7b-instruct-q4_K_M`) |
| **Turkish transformers NER** | Higher TR name/org accuracy than the multilingual baseline | `uv sync --extra tr` then set `USE_TRANSFORMERS_TR=true` |
| **`en_core_web_lg`** | Higher English NER accuracy | `uv run python -m spacy download en_core_web_lg` then `SPACY_EN_MODEL=en_core_web_lg` |
| **External chat** | Q&A over approved docs | `uv sync --extra chat`, set `CHAT_PROVIDER` + API key |

### Memory budget (16GB M4)
Qwen2.5-7B-Q4 ≈ 5 GB resident. The transformers TR model (≈ 0.5 GB) + Qwen together are tight;
prefer not to keep both hot. The heuristic auditor needs no extra memory.

## 4. Configuration

Copy `.env.example` → `.env`. Key vars:

| Var | Default | Notes |
|---|---|---|
| `MAX_ITERATIONS` | 3 | bounded 1–3 |
| `AUDITOR_PROVIDER` | ollama | falls back to heuristic if Ollama is down |
| `AUDITOR_MODEL` | qwen2.5:7b-instruct-q4_K_M | |
| `AUDITOR_RISK_APPROVE` | low | max risk auto-approvable |
| `SPACY_EN_MODEL` | en_core_web_sm | `en_core_web_lg` for production |
| `CHAT_PROVIDER` | anthropic | openai / anthropic / azure |
| `STORAGE_ROOT` | ./data | the 5 isolated layers |
| `MAX_UPLOAD_MB` | 50 | |

## 5. Security / ops

- **No external API calls before approval.** The Qwen auditor is local (Ollama); chat is gated.
- **5 isolated storage layers** under `STORAGE_ROOT`; layers 1–2 (original/extracted/mapping)
  never leave the machine. `DELETE /api/documents/{id}` securely removes all layers.
- **PII-safe logging** is enabled at startup. On SSD, secure deletion is best-effort — see
  [SECURITY.md](../SECURITY.md) (crypto-shredding is the production target).

## 6. Production build

```bash
cd frontend && npm run build              # static assets in frontend/dist
cd ../backend && uv run uvicorn app.main:app --host 0.0.0.0 --port 8000
```
Serve `frontend/dist` behind your reverse proxy; point `/api` to the backend.

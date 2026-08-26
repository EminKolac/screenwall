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

## Benchmark — iki bağımsız sistem, aynı sınav

Fable'ın ölçüm altyapısı (GoldBench holdout · 72'lik stres korpusu · kanarya/aşırı-maskeleme
probları, hepsi hash-pinli) bağımsız geliştirilmiş ikinci bir sistemle (Sol/Codex) aynı
kurallar altında koşuldu; skorlayıcı bağımsız ve yeniden koşturulabilir.

| Test | Fable | Sol |
|---|---|---|
| Kritik recall (gold) | 1.00* | 0.68 (kural-eşitlenmiş: 0.86) |
| Aşırı-maskeleme (gold) | 0/90 | 0/90 |
| Stres kritik yanlış onay | 0/72 | 9/72 (çoğu mimari: aynı-format sevkiyatta metadata) |
| Kanarya kaçışı | 0/16 | 1/16 |
| Gereksiz maskeleme probu | 11/40 | **3/40 — Sol daha iyi** |

*Mühürlü holdout alt-kümesi; ayrıntı ve tüm dürüstlük notları: `thoughts/EXPERIMENTS.md`,
`docs/CALIBRATION.md`. Sunumlar: `Fable-Sunum-B2C.pptx` (bireysel kullanıcı odaklı) ve
`Fable-Sunum-Rapor.pptx` (teknik rapor). Tanıtım videosu: `fable-promo.mp4`.

#!/usr/bin/env bash
# Setup for MacBook Air M4 16GB: Ollama + Qwen auditor model, Python env, spaCy EN model.
# Idempotent and safe to re-run. Does not install Homebrew automatically.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MODEL="${AUDITOR_MODEL:-qwen3.5:4b}"
CHAT_MODEL="${CHAT_OLLAMA_MODEL:-qwen3.5:4b}"  # same model: auditor + post-approval chat

echo "==> 1/4 Ollama"
if ! command -v ollama >/dev/null 2>&1; then
  if command -v brew >/dev/null 2>&1; then
    brew install ollama
  else
    echo "   Ollama not found and Homebrew unavailable."
    echo "   Install from https://ollama.com/download then re-run."
    exit 1
  fi
fi
# Start server if not running, then pull the auditor model.
if ! curl -sf http://localhost:11434/api/tags >/dev/null 2>&1; then
  echo "   Starting ollama serve (background)…"; (ollama serve >/tmp/ollama.log 2>&1 &) ; sleep 3
fi
echo "==> 2/4 Pull models: auditor ($MODEL) + chat ($CHAT_MODEL)"
ollama pull "$MODEL"
ollama pull "$CHAT_MODEL"

echo "==> 3/4 Tesseract OCR (image/scanned PDFs; Turkish + English)"
if ! command -v tesseract >/dev/null 2>&1; then
  if command -v brew >/dev/null 2>&1; then
    brew install tesseract tesseract-lang
  else
    echo "   Tesseract missing; install 'tesseract' + 'tesseract-lang' (tur,eng), then re-run."
  fi
fi

echo "==> 4/4 Backend Python env (uv)"
cd "$ROOT/backend"
uv sync
# The spaCy models are pinned in pyproject.toml, so `uv sync` installs them; `spacy download`
# would need pip, which a uv environment does not have.
uv run python -c "import en_core_web_sm, xx_ent_wiki_sm" \
  && echo "   spaCy models present (en_core_web_sm, xx_ent_wiki_sm)."

echo "==> Done"
echo "   Run: cd backend && uv run uvicorn app.main:app --reload"
echo "   Health: curl localhost:8000/health"

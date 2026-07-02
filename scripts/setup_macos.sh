#!/usr/bin/env bash
# Setup for MacBook Air M4 16GB: Ollama + Qwen auditor model, Python env, spaCy EN model.
# Idempotent and safe to re-run. Does not install Homebrew automatically.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MODEL="${AUDITOR_MODEL:-qwen2.5:7b-instruct-q4_K_M}"
CHAT_MODEL="${CHAT_OLLAMA_MODEL:-qwen2.5:3b}"  # local post-approval chat (config default)

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

echo "==> 3/5 Tesseract OCR (image/scanned PDFs; Turkish + English)"
if ! command -v tesseract >/dev/null 2>&1; then
  if command -v brew >/dev/null 2>&1; then
    brew install tesseract tesseract-lang
  else
    echo "   Tesseract missing; install 'tesseract' + 'tesseract-lang' (tur,eng), then re-run."
  fi
fi

echo "==> 4/5 Backend Python env (uv)"
cd "$ROOT/backend"
uv sync --extra tr --extra chat
echo "   Downloading spaCy English model…"
uv run python -m spacy download en_core_web_lg

echo "==> 5/5 Done"
echo "   Run: cd backend && uv run uvicorn app.main:app --reload"
echo "   Health: curl localhost:8000/health"

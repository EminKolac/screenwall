#!/usr/bin/env bash
# Start the whole platform (Ollama + backend + frontend) detached, so it survives terminal close.
# Usage:  bash ~/anonymizer-platform/start.sh   then open http://localhost:5174
set -u
# Private by default: the log files the redirects below create, and whatever the three services
# write, are readable by this user only.
umask 077
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOGS="$ROOT/.logs"; mkdir -p "$LOGS"
# A log from an earlier run keeps its old mode (0644) across `>`: tighten those too.
chmod 700 "$LOGS"; chmod 600 "$LOGS"/*.log 2>/dev/null || true
UV="$(command -v uv || echo "$HOME/.local/bin/uv")"
NPM="$(command -v npm || echo npm)"
OLLAMA="$(command -v ollama || echo "/opt/homebrew/bin/ollama")"

up() { curl -sf -o /dev/null --max-time 2 "$1" 2>/dev/null; }

# 1) Ollama (free local chat)
if ! up http://localhost:11434/api/tags; then
  echo "→ ollama serve"
  nohup "$OLLAMA" serve >"$LOGS/ollama.log" 2>&1 & disown
fi
# Wait for Ollama to bind, THEN ensure the local model (config default qwen3.5:4b) is present.
# Same model serves the auditor and post-approval chat.
for _ in $(seq 1 15); do up http://localhost:11434/api/tags && break; sleep 1; done
if up http://localhost:11434/api/tags && ! "$OLLAMA" list 2>/dev/null | grep -q "qwen3.5:4b"; then
  echo "→ pulling qwen3.5:4b (first run, background)"
  nohup "$OLLAMA" pull qwen3.5:4b >"$LOGS/ollama-pull.log" 2>&1 & disown
fi

# 2) Backend :8000
if ! up http://localhost:8000/health; then
  echo "→ backend (uvicorn :8000)"
  ( cd "$ROOT/backend" && nohup "$UV" run uvicorn app.main:app --host 127.0.0.1 --port 8000 \
      >"$LOGS/backend.log" 2>&1 & disown )
fi

# 3) Frontend :5174
if ! up http://localhost:5174/; then
  echo "→ frontend (vite :5174)"
  ( cd "$ROOT/frontend" && nohup "$NPM" run dev -- --host 127.0.0.1 --port 5174 --strictPort \
      >"$LOGS/frontend.log" 2>&1 & disown )
fi

echo ""
echo "Başlatılıyor… ~10 sn sonra:  http://localhost:5174"
echo "Loglar: $LOGS/  (sorun olursa: tail -f $LOGS/*.log)"
echo "Durdurmak için: bash $ROOT/stop.sh"

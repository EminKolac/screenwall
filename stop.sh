#!/usr/bin/env bash
# Stop backend + frontend (leaves Ollama running; stop it with: brew services stop ollama).
for p in 8000 5174; do
  pid=$(lsof -ti tcp:$p 2>/dev/null)
  [ -n "$pid" ] && kill $pid 2>/dev/null && echo "stopped :$p (PID $pid)" || echo ":$p already free"
done

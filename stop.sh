#!/usr/bin/env bash
# Stop backend + frontend (leaves Ollama running; stop it with: brew services stop ollama).
# Only the processes LISTENING on the ports: a plain `lsof -ti tcp:PORT` also lists every client
# connected to them, such as the browser's network process.
for p in 8000 5174; do
  pid=$(lsof -ti tcp:$p -sTCP:LISTEN 2>/dev/null)
  [ -n "$pid" ] && kill $pid 2>/dev/null && echo "stopped :$p (PID $pid)" || echo ":$p already free"
done

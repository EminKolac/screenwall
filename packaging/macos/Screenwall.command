#!/bin/bash
# Screenwall launcher for macOS.
#
# Double-click it in Finder (it opens in Terminal) or run it from a terminal. The window stays open
# while the app runs; Ctrl+C or closing the window stops the server.
#
# Steps:
#   1. uv: found on PATH or in ~/.local/bin, otherwise installed with the official installer
#      (UV_NO_MODIFY_PATH=1: shell profiles are not touched).
#   2. "uv sync --frozen --no-dev --python 3.12" installs the locked backend dependencies into
#      $SCREENWALL_HOME/venv (the first run downloads them; later runs only check).
#   3. Ollama and the auditor model, needed to approve documents. If the Ollama API does not
#      answer, Ollama is started when installed; otherwise the download page is shown and the app
#      starts anyway (documents are masked but nothing can be approved). A missing model is pulled.
#   4. The server on 127.0.0.1:$SCREENWALL_PORT serves the API and the built UI. If that port
#      already answers /health, only the browser is opened.
#   5. Every server start gets a new random launch token in $SCREENWALL_HOME/launch-token (this
#      user only). The server reads it from that file (LAUNCH_TOKEN_FILE) and the browser gets it
#      in the address (http://127.0.0.1:PORT/#k=<token>); without it no session is issued, so
#      other accounts on this computer cannot use the app (backend config.py `launch_token`).
#
# Optional environment:
#   SCREENWALL_HOME           base folder (default: ~/Library/Application Support/Screenwall)
#                             with data/ (documents), venv/ (Python) and logs/
#   SCREENWALL_PORT           port (default 8765)
#   SCREENWALL_NO_BROWSER=1   do not open the browser
#   SCREENWALL_SKIP_OLLAMA=1  skip the Ollama checks (CI)
#   AUDITOR_MODEL             auditor model (default qwen3.5:4b); the backend reads it too
#   OLLAMA_BASE_URL           Ollama API (default http://127.0.0.1:11434); the backend reads it too
#
# Inside Screenwall.app (Screenwall-macOS.dmg) this file is Contents/Resources/Screenwall/
# Screenwall.command and the app's Contents/MacOS/Screenwall opens it in Terminal. The bundle stays
# read-only there: everything written goes to $SCREENWALL_HOME as above, and Python's bytecode
# cache too ($SCREENWALL_HOME/pycache, PYTHONPYCACHEPREFIX). From the zip nothing changes.
#
# Written for the bash 3.2 that ships with macOS. Every path is quoted: the default home contains
# a space ("Application Support").
set -u
umask 077 # documents, venv and logs are readable by this user only

APP_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$APP_ROOT/app/backend"
UI_DIST_DIR="$APP_ROOT/app/frontend/dist"
VERSION="$(cat "$APP_ROOT/VERSION" 2>/dev/null || echo '?')"

SCREENWALL_HOME="${SCREENWALL_HOME:-$HOME/Library/Application Support/Screenwall}"
PORT="${SCREENWALL_PORT:-8765}"
AUDITOR_MODEL="${AUDITOR_MODEL:-qwen3.5:4b}"
OLLAMA_URL="${OLLAMA_BASE_URL:-http://127.0.0.1:11434}"
OLLAMA_URL="${OLLAMA_URL%/}"
APP_URL="http://127.0.0.1:$PORT"

DATA_DIR="$SCREENWALL_HOME/data"
VENV_DIR="$SCREENWALL_HOME/venv"
LOG_DIR="$SCREENWALL_HOME/logs"
TOKEN_FILE="$SCREENWALL_HOME/launch-token"
SERVER_LOG="$LOG_DIR/server.log"
SERVER_PID=""

# Inside Screenwall.app: nothing may be written next to the code (see the header).
case "$APP_ROOT" in
  */Contents/Resources/Screenwall)
    REINSTALL_HINT="Screenwall'ı Screenwall-macOS.dmg dosyasından yeniden kurun."
    export PYTHONPYCACHEPREFIX="$SCREENWALL_HOME/pycache"
    ;;
  *)
    REINSTALL_HINT="Zip'i yeniden açın."
    ;;
esac

# Homebrew (Apple silicon and Intel) and uv's own folder: a Finder launch may not have them on
# PATH. tesseract (optional OCR) is found through these too.
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"

say() { printf '%s\n' "$*"; }
fail() {
  say ""
  say "HATA: $*"
  exit 1
}
# True when the URL answers with a 2xx status within a few seconds.
up() { curl -sf -o /dev/null --max-time 3 "$1" 2>/dev/null; }

open_browser() {
  if [ "${SCREENWALL_NO_BROWSER:-0}" = "1" ]; then
    return 0
  fi
  open "$1" >/dev/null 2>&1 || say "Tarayıcıda şu adresi açın: $1"
}

# The address to open: with the running server's launch token in the fragment when this home
# holds one. A fragment never reaches the server or its log; the UI sends it once to /api/session.
app_link() {
  local token=""
  if [ -r "$TOKEN_FILE" ]; then
    token="$(head -n 1 "$TOKEN_FILE" 2>/dev/null | tr -cd 'A-Za-z0-9_-')"
  fi
  if [ -n "$token" ]; then
    printf '%s/#k=%s\n' "$APP_URL" "$token"
  else
    printf '%s\n' "$APP_URL"
  fi
}

# Stop the server this window started (the uv process forwards the signal to uvicorn).
stop_server() {
  if [ -n "$SERVER_PID" ] && kill -0 "$SERVER_PID" 2>/dev/null; then
    say ""
    say "Screenwall durduruluyor..."
    kill -TERM "$SERVER_PID" 2>/dev/null
    local i=0
    while kill -0 "$SERVER_PID" 2>/dev/null && [ $i -lt 20 ]; do
      sleep 0.5
      i=$((i + 1))
    done
    if kill -0 "$SERVER_PID" 2>/dev/null; then
      kill -KILL "$SERVER_PID" 2>/dev/null
    fi
  fi
  SERVER_PID=""
}

case "$PORT" in
  '' | *[!0-9]*) fail "SCREENWALL_PORT bir sayı olmalı (şu an: '$PORT')." ;;
esac

say "Screenwall $VERSION"
say "Veri klasörü: $SCREENWALL_HOME"
say ""

mkdir -p "$DATA_DIR" "$VENV_DIR" "$LOG_DIR" || fail "Klasör oluşturulamadı: $SCREENWALL_HOME"
chmod 700 "$SCREENWALL_HOME" "$DATA_DIR" "$LOG_DIR" 2>/dev/null || true
[ -f "$BACKEND_DIR/uv.lock" ] || fail "Uygulama dosyaları eksik: $BACKEND_DIR. $REINSTALL_HINT"
[ -f "$UI_DIST_DIR/index.html" ] || fail "Arayüz dosyaları eksik: $UI_DIST_DIR. $REINSTALL_HINT"

# Already running (another window, or an earlier start): just show it.
if up "$APP_URL/health"; then
  say "Screenwall zaten çalışıyor: $APP_URL"
  open_browser "$(app_link)"
  exit 0
fi

# ---------------------------------------------------------------- 1) uv

find_uv() {
  if command -v uv >/dev/null 2>&1; then
    command -v uv
    return 0
  fi
  local candidate
  for candidate in "$HOME/.local/bin/uv" "$HOME/.cargo/bin/uv"; do
    if [ -x "$candidate" ]; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done
  return 1
}

UV="$(find_uv)"
if [ -z "$UV" ]; then
  say "uv bulunamadı; resmî kurulum betiğiyle ~/.local/bin klasörüne kuruluyor..."
  curl -LsSf https://astral.sh/uv/install.sh |
    env UV_NO_MODIFY_PATH=1 UV_INSTALL_DIR="$HOME/.local/bin" sh ||
    fail "uv kurulamadı. İnternet bağlantınızı kontrol edip tekrar deneyin."
  UV="$(find_uv)" || fail "uv kuruldu ama bulunamadı (~/.local/bin/uv)."
fi

# ---------------------------------------------------------------- 2) Python environment

export UV_PROJECT_ENVIRONMENT="$VENV_DIR"
say "Python ortamı hazırlanıyor (ilk açılışta paketler indirilir, birkaç dakika sürebilir)..."
(cd "$BACKEND_DIR" && "$UV" sync --frozen --no-dev --python 3.12) ||
  fail "Python paketleri kurulamadı. İnternet bağlantınızı kontrol edip tekrar deneyin."

# ---------------------------------------------------------------- 3) Ollama + auditor model

find_ollama() {
  if command -v ollama >/dev/null 2>&1; then
    command -v ollama
    return 0
  fi
  local candidate
  for candidate in /opt/homebrew/bin/ollama /usr/local/bin/ollama \
    "/Applications/Ollama.app/Contents/Resources/ollama" \
    "$HOME/Applications/Ollama.app/Contents/Resources/ollama"; do
    if [ -x "$candidate" ]; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done
  return 1
}

# The model list from /api/tags contains "name":"<model>" for every pulled model.
has_model() {
  curl -sf --max-time 5 "$OLLAMA_URL/api/tags" 2>/dev/null | grep -Fq "\"name\":\"$AUDITOR_MODEL\""
}

ensure_ollama() {
  local ollama i
  ollama="$(find_ollama)"
  if ! up "$OLLAMA_URL/api/tags"; then
    if [ -d /Applications/Ollama.app ] || [ -d "$HOME/Applications/Ollama.app" ]; then
      say "Ollama başlatılıyor..."
      open -g -a Ollama >/dev/null 2>&1
    elif [ -n "$ollama" ]; then
      say "Ollama başlatılıyor (ollama serve)..."
      # Detached: Ollama keeps running for other apps after this window closes.
      nohup "$ollama" serve >>"$LOG_DIR/ollama.log" 2>&1 </dev/null &
    else
      say "Ollama bulunamadı."
      say "Screenwall açılacak ve belgeleri maskeleyecek, ama Ollama ve $AUDITOR_MODEL modeli"
      say "kurulana kadar hiçbir belge onaylanamaz. Ollama'yı https://ollama.com/download"
      say "adresinden kurun, sonra Screenwall'ı yeniden başlatın."
      open_browser "https://ollama.com/download"
      return 0
    fi
    i=0
    while ! up "$OLLAMA_URL/api/tags" && [ $i -lt 30 ]; do
      sleep 1
      i=$((i + 1))
    done
    if ! up "$OLLAMA_URL/api/tags"; then
      say "Ollama yanıt vermiyor ($OLLAMA_URL). Belgeler onaylanamaz; log: $LOG_DIR/ollama.log"
      return 0
    fi
  fi
  if has_model; then
    say "Denetçi modeli hazır: $AUDITOR_MODEL"
    return 0
  fi
  if [ -z "$ollama" ]; then
    say "$AUDITOR_MODEL modeli yok ve ollama komutu bulunamadı."
    say "Bir terminalde 'ollama pull $AUDITOR_MODEL' çalıştırın."
    return 0
  fi
  say "Denetçi modeli indiriliyor: $AUDITOR_MODEL (yaklaşık 3,4 GB, yalnızca bir kez)..."
  if ! OLLAMA_HOST="$OLLAMA_URL" "$ollama" pull "$AUDITOR_MODEL"; then
    say "Model indirilemedi. Belgeler onaylanamaz; daha sonra 'ollama pull $AUDITOR_MODEL' deneyin."
  fi
  return 0
}

if [ "${SCREENWALL_SKIP_OLLAMA:-0}" = "1" ]; then
  say "Ollama denetimi atlandı (SCREENWALL_SKIP_OLLAMA=1)."
else
  ensure_ollama
fi

# ---------------------------------------------------------------- 4) server

# PyMuPDF finds Tesseract's language data through TESSDATA_PREFIX; the backend sets the Apple
# silicon Homebrew path itself, this covers Intel Homebrew.
if [ -z "${TESSDATA_PREFIX:-}" ] && [ ! -d /opt/homebrew/share/tessdata ] &&
  [ -d /usr/local/share/tessdata ]; then
  export TESSDATA_PREFIX=/usr/local/share/tessdata
fi

trap 'stop_server; exit 130' INT
trap 'stop_server; exit 143' TERM
trap 'stop_server; exit 129' HUP
trap 'stop_server' EXIT

# A new launch token for this start (umask 077: the file is readable by this user only).
new_token="$(head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n')"
[ "${#new_token}" -eq 64 ] || fail "Başlatma anahtarı üretilemedi."
{ printf '%s\n' "$new_token" >"$TOKEN_FILE" && chmod 600 "$TOKEN_FILE"; } ||
  fail "Başlatma anahtarı yazılamadı: $TOKEN_FILE"

say "Sunucu başlatılıyor: $APP_URL"
printf '\n--- %s Screenwall %s, port %s ---\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$VERSION" "$PORT" \
  >>"$SERVER_LOG"
cd "$BACKEND_DIR" || fail "Klasöre geçilemedi: $BACKEND_DIR"
STORAGE_ROOT="$DATA_DIR" \
  UI_DIST="$UI_DIST_DIR" \
  CORS_ALLOW_ORIGINS="$APP_URL,http://localhost:$PORT" \
  LAUNCH_TOKEN_FILE="$TOKEN_FILE" \
  AUDITOR_MODEL="$AUDITOR_MODEL" \
  "$UV" run --frozen --no-dev uvicorn app.main:app --host 127.0.0.1 --port "$PORT" \
  >>"$SERVER_LOG" 2>&1 </dev/null &
SERVER_PID=$!

started=$SECONDS
until up "$APP_URL/health"; do
  if ! kill -0 "$SERVER_PID" 2>/dev/null; then
    SERVER_PID=""
    say ""
    say "Sunucu başlamadı. Son kayıtlar ($SERVER_LOG):"
    tail -n 25 "$SERVER_LOG"
    say ""
    say "Port $PORT başka bir program tarafından kullanılıyorsa başka bir port deneyin:"
    say "  SCREENWALL_PORT=8766 \"$APP_ROOT/Screenwall.command\""
    exit 1
  fi
  if [ $((SECONDS - started)) -ge 90 ]; then
    say ""
    say "Sunucu 90 saniyede hazır olmadı. Son kayıtlar ($SERVER_LOG):"
    tail -n 25 "$SERVER_LOG"
    say ""
    say "İlk açılış yavaş bir bilgisayarda uzun sürebilir; Screenwall'ı bir kez daha başlatın."
    exit 1
  fi
  sleep 1
done

say ""
say "Screenwall hazır ($((SECONDS - started)) sn): $APP_URL"
say "Kullanırken bu pencereyi açık tutun. Durdurmak için Ctrl+C'ye basın veya pencereyi kapatın."
open_browser "$APP_URL/#k=$new_token"

wait "$SERVER_PID"
status=$?
SERVER_PID=""
say "Sunucu kapandı (çıkış kodu $status). Kayıtlar: $SERVER_LOG"
exit "$status"

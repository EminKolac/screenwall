#!/usr/bin/env bash
# End-to-end smoke test of the release assets in dist/, started the way a user starts them, but
# with no browser, no Ollama and no Terminal window. The release workflow runs it on an Apple
# Silicon and an Intel Mac (.github/workflows/release.yml, smoke job); "make smoke-release" runs
# it on this Mac after "make release".
#
#   bash packaging/smoke_release.sh zip|dmg|all
#
#   zip  Unpack dist/Screenwall-macOS.zip with ditto (what Archive Utility uses) into a folder
#        whose name has a space and start Screenwall/Screenwall.command, with SCREENWALL_HOME set
#        to another such folder.
#   dmg  HOME points at a new empty folder, so the default data folder
#        (~/Library/Application Support/Screenwall) is used and the real home is not touched.
#        Mount dist/Screenwall-macOS.dmg read-only and out of Finder's sight and check what it
#        holds (Screenwall.app, the Applications link, OKU-BENI.txt). Started from the image
#        (SCREENWALL_APP_DRY_RUN=1: messages are printed, no dialog, no Terminal), the app must
#        only ask to be moved to Applications. Copy Screenwall.app out with ditto (as dragging it
#        to Applications does), detach the image, lint Info.plist. Run Contents/MacOS/Screenwall
#        of the copy in dry-run mode: it writes the Terminal starter and prints the open command
#        instead of opening Terminal. Then run that starter as Terminal would; it runs the
#        launcher inside the app. Afterwards no file or folder in Screenwall.app may be new or
#        changed, and Python's bytecode cache must be in the data folder.
#   all  zip, then dmg.
#
#   Then, for both: wait for /health (300 s; if the launcher gives up first, start it once more,
#   as its own message tells users to), run packaging/smoke_test.py with the Python environment
#   the launcher built, stop the launcher with TERM (what closing its window does) and check that
#   the server is gone.
#
# Environment:
#   SCREENWALL_PORT       port (default 8765); it must be free
#   SMOKE_DIR             work folder (default: a new folder from mktemp -d); kept afterwards
#   SMOKE_EXPECT_AUDITOR  passed to smoke_test.py --expect-auditor (default unavailable). Ollama
#                         is skipped by the launcher, but the server still asks OLLAMA_BASE_URL:
#                         when an Ollama runs on this Mac, point OLLAMA_BASE_URL at an unused port
#                         (e.g. http://127.0.0.1:9) or use SMOKE_EXPECT_AUDITOR=any.
#
# On GitHub Actions errors become annotations and the results go to the step summary. Exit 0
# when every check passed. Nothing is deleted. Written for bash 3.2 (macOS).
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DIST="$REPO/dist"
KIND="${1:-}"

say() { printf '%s\n' "$*"; }
note_error() {
  if [ "${GITHUB_ACTIONS:-}" = "true" ]; then
    say "::error::smoke ($KIND): $*"
  else
    say "smoke ($KIND): ERROR: $*" >&2
  fi
}
fail() {
  note_error "$*"
  exit 1
}
summary() {
  if [ -n "${GITHUB_STEP_SUMMARY:-}" ]; then
    printf '%s\n' "$@" >>"$GITHUB_STEP_SUMMARY"
  fi
}
up() { curl -sf -o /dev/null --max-time 3 "$1" 2>/dev/null; }

case "$KIND" in
  zip | dmg) ;;
  all)
    status=0
    SMOKE_DIR="${SMOKE_DIR:+$SMOKE_DIR/zip}" bash "${BASH_SOURCE[0]}" zip || status=1
    SMOKE_DIR="${SMOKE_DIR:+$SMOKE_DIR/dmg}" bash "${BASH_SOURCE[0]}" dmg || status=1
    exit "$status"
    ;;
  *)
    say "usage: bash packaging/smoke_release.sh zip|dmg|all" >&2
    exit 2
    ;;
esac

[ "$(uname -s)" = "Darwin" ] || fail "macOS only"
for tool in curl ditto; do
  command -v "$tool" >/dev/null 2>&1 || fail "$tool is required"
done

PORT="${SCREENWALL_PORT:-8765}"
URL="http://127.0.0.1:$PORT"
EXPECT_AUDITOR="${SMOKE_EXPECT_AUDITOR:-unavailable}"
if [ -n "${SMOKE_DIR:-}" ]; then
  WORK="$SMOKE_DIR"
  mkdir -p "$WORK"
else
  WORK="$(mktemp -d "${TMPDIR:-/tmp}/screenwall-smoke-$KIND.XXXXXX")"
fi
WORK="$(cd "$WORK" && pwd -P)"
say "smoke ($KIND): work folder $WORK"

# An answer here before anything started would make the test pass against another server.
if up "$URL/health"; then
  fail "$URL already answers; stop that server or set SCREENWALL_PORT"
fi

LAUNCHER_PID=""
MOUNTED=""
cleanup() {
  if [ -n "$LAUNCHER_PID" ] && kill -0 "$LAUNCHER_PID" 2>/dev/null; then
    kill -TERM "$LAUNCHER_PID" 2>/dev/null || true
    for _ in $(seq 1 30); do
      kill -0 "$LAUNCHER_PID" 2>/dev/null || break
      sleep 1
    done
  fi
  if [ -n "$MOUNTED" ]; then
    hdiutil detach -quiet "$MOUNTED" 2>/dev/null || hdiutil detach -quiet -force "$MOUNTED" ||
      say "warning: could not detach $MOUNTED"
    MOUNTED=""
  fi
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

export SCREENWALL_NO_BROWSER=1 SCREENWALL_SKIP_OLLAMA=1 SCREENWALL_PORT="$PORT"
# Python writes its bytecode cache, as on a user's Mac, so the dmg test sees where it goes (some
# developer shells turn it off).
unset PYTHONDONTWRITEBYTECODE PYTHONPYCACHEPREFIX

# ---------------------------------------------------------------- prepare: zip

prepare_zip() {
  local zip="$DIST/Screenwall-macOS.zip" app_dir="$WORK/Screenwall app"
  [ -f "$zip" ] || fail "$zip is missing; build it first (make release)"
  mkdir -p "$app_dir"
  ditto -x -k "$zip" "$app_dir"
  [ -x "$app_dir/Screenwall/Screenwall.command" ] ||
    fail "Screenwall.command is missing or not executable after unzip"
  export SCREENWALL_HOME="$WORK/Screenwall home"
  DATA_HOME="$SCREENWALL_HOME"
  LAUNCH="$app_dir/Screenwall/Screenwall.command"
}

# ---------------------------------------------------------------- prepare: dmg

APP=""
MARKER=""
prepare_dmg() {
  local dmg="$DIST/Screenwall-macOS.dmg" mnt="$WORK/mnt" entries out version
  [ -f "$dmg" ] || fail "$dmg is missing; build it on a Mac first (make release)"
  for tool in hdiutil plutil; do
    command -v "$tool" >/dev/null 2>&1 || fail "$tool is required"
  done

  # A new, empty home: the app's defaults are tested, the real home is not touched.
  export HOME="$WORK/home"
  mkdir -p "$HOME"
  unset SCREENWALL_HOME
  DATA_HOME="$HOME/Library/Application Support/Screenwall"

  mkdir -p "$mnt"
  hdiutil attach -quiet -nobrowse -readonly -noautoopen -mountpoint "$mnt" "$dmg" ||
    fail "the dmg does not mount"
  MOUNTED="$mnt"
  entries="$(cd "$mnt" && ls -A | grep -v '^\.' | tr '\n' ' ' || true)"
  [ "$entries" = "Applications OKU-BENI.txt Screenwall.app " ] ||
    fail "unexpected dmg contents: $entries"
  [ -L "$mnt/Applications" ] && [ "$(readlink "$mnt/Applications")" = /Applications ] ||
    fail "Applications in the dmg is not a link to /Applications"
  # Mounted read-only, as Finder mounts a downloaded image.
  if [ -w "$mnt/Screenwall.app" ]; then
    fail "the mounted dmg is writable"
  fi
  # Opened straight from the image, the app only asks to be moved to Applications.
  out="$(SCREENWALL_APP_DRY_RUN=1 "$mnt/Screenwall.app/Contents/MacOS/Screenwall" 2>&1)" ||
    fail "Contents/MacOS/Screenwall failed when started from the image"
  if ! printf '%s\n' "$out" | grep -q "Uygulamalar klasörüne taşıyın" ||
    printf '%s\n' "$out" | grep -q '^would run:' || [ -e "$DATA_HOME/launcher" ]; then
    say "$out"
    fail "started from the mounted image, the app did not ask to be moved to Applications"
  fi
  say "from the mounted image: $(printf '%s\n' "$out" | head -n 1)"
  mkdir -p "$WORK/Applications copy"
  ditto "$mnt/Screenwall.app" "$WORK/Applications copy/Screenwall.app"
  hdiutil detach -quiet "$mnt" || hdiutil detach -quiet -force "$mnt" || fail "could not detach the dmg"
  MOUNTED=""
  APP="$WORK/Applications copy/Screenwall.app"

  plutil -lint "$APP/Contents/Info.plist" || fail "Info.plist is not valid"
  version="$(cat "$APP/Contents/Resources/Screenwall/VERSION")"
  [ "$(plutil -extract CFBundleShortVersionString raw "$APP/Contents/Info.plist")" = "$version" ] ||
    fail "CFBundleShortVersionString is not the app's VERSION ($version)"
  [ "$(plutil -extract CFBundleExecutable raw "$APP/Contents/Info.plist")" = "Screenwall" ] ||
    fail "CFBundleExecutable is not Screenwall"
  [ "$(plutil -extract LSArchitecturePriority.0 raw "$APP/Contents/Info.plist")" = "arm64" ] ||
    fail "LSArchitecturePriority does not start with arm64 (the script would run under Rosetta)"
  [ -x "$APP/Contents/MacOS/Screenwall" ] || fail "Contents/MacOS/Screenwall is not executable"
  [ -f "$APP/Contents/Resources/AppIcon.icns" ] || fail "AppIcon.icns is missing"

  # Everything the app writes from here on must land outside the bundle.
  MARKER="$WORK/started-at"
  : >"$MARKER"
  sleep 1

  out="$(SCREENWALL_APP_DRY_RUN=1 "$APP/Contents/MacOS/Screenwall")" ||
    fail "Contents/MacOS/Screenwall failed in dry-run mode"
  say "$out"
  printf '%s\n' "$out" | grep -q '^would run: open -b com.apple.Terminal ' ||
    fail "Contents/MacOS/Screenwall did not get as far as opening Terminal"
  LAUNCH="$DATA_HOME/launcher/Screenwall.command"
  [ -x "$LAUNCH" ] || fail "the Terminal starter $LAUNCH is missing or not executable"
  bash -n "$LAUNCH" || fail "the Terminal starter is not valid bash"
}

if [ "$KIND" = zip ]; then
  prepare_zip
else
  prepare_dmg
fi

# ---------------------------------------------------------------- start and wait for /health

start_launcher() { # start_launcher <attempt>
  "$LAUNCH" >"$WORK/launcher-$1.log" 2>&1 </dev/null &
  LAUNCHER_PID=$!
}
show_logs() {
  local log
  for log in "$WORK"/launcher-*.log "$DATA_HOME/logs/server.log"; do
    [ -f "$log" ] || continue
    say "----- $log (last 60 lines)"
    tail -n 60 "$log"
  done
}
# 0: /health answered; 1: the launcher exited first; 2: no answer in 300 s.
wait_health() {
  local deadline=$((SECONDS + 300))
  while [ "$SECONDS" -lt "$deadline" ]; do
    up "$URL/health" && return 0
    kill -0 "$LAUNCHER_PID" 2>/dev/null || return 1
    sleep 2
  done
  return 2
}

started=$SECONDS
start_launcher 1
result=0
wait_health || result=$?
if [ "$result" = 1 ]; then
  if [ "${GITHUB_ACTIONS:-}" = "true" ]; then
    say "::warning::smoke ($KIND): the launcher exited before /health answered (after $((SECONDS - started)) s); starting it a second time, as its message tells users to."
  else
    say "warning: the launcher exited before /health answered; starting it a second time"
  fi
  show_logs
  sleep 3
  start_launcher 2
  result=0
  wait_health || result=$?
fi
if [ "$result" != 0 ]; then
  show_logs
  if [ "$result" = 1 ]; then
    fail "the launcher exited before /health answered"
  fi
  fail "/health did not answer within 300 s"
fi
health_s=$((SECONDS - started))
say "smoke ($KIND): /health answered $health_s s after the first launcher start"

# ---------------------------------------------------------------- smoke_test.py

python_bin="$DATA_HOME/venv/bin/python"
[ -x "$python_bin" ] || fail "no Python environment at $DATA_HOME/venv"
smoke_status=0
"$python_bin" "$REPO/packaging/smoke_test.py" --base-url "$URL" --wait 60 \
  --expect-auditor "$EXPECT_AUDITOR" --launch-token-file "$DATA_HOME/launch-token" \
  >"$WORK/smoke-summary.json" || smoke_status=$?
cat "$WORK/smoke-summary.json"

# ---------------------------------------------------------------- stop

stop_status=0
kill -TERM "$LAUNCHER_PID" 2>/dev/null || true
for _ in $(seq 1 30); do
  kill -0 "$LAUNCHER_PID" 2>/dev/null || break
  sleep 1
done
if kill -0 "$LAUNCHER_PID" 2>/dev/null; then
  note_error "the launcher did not exit within 30 s of TERM"
  stop_status=1
else
  LAUNCHER_PID=""
fi
for _ in $(seq 1 10); do
  up "$URL/health" || break
  sleep 1
done
if up "$URL/health"; then
  note_error "the server still answers after the launcher stopped"
  stop_status=1
fi
cp "$DATA_HOME/logs/server.log" "$WORK/server.log" 2>/dev/null || true

# ---------------------------------------------------------------- the bundle stayed read-only

bundle_status=0
bundle_note=""
if [ "$KIND" = dmg ]; then
  changed="$(find "$APP" -newer "$MARKER" -print | head -n 20)"
  if [ -n "$changed" ]; then
    note_error "Screenwall.app was written to while it ran:"
    say "$changed"
    bundle_status=1
  fi
  if [ -n "$(find "$APP" -name __pycache__ -print | head -n 1)" ]; then
    note_error "Screenwall.app holds a __pycache__ folder"
    bundle_status=1
  fi
  if [ ! -d "$DATA_HOME/pycache" ]; then
    note_error "no bytecode cache in $DATA_HOME/pycache (PYTHONPYCACHEPREFIX not used)"
    bundle_status=1
  fi
  if [ "$bundle_status" = 0 ]; then
    bundle_note="Screenwall.app unchanged after the run; "
  fi
fi

# ---------------------------------------------------------------- result

status=0
[ "$smoke_status" = 0 ] || status=1
[ "$stop_status" = 0 ] || status=1
[ "$bundle_status" = 0 ] || status=1
summary "### Smoke test, $KIND, $(uname -m) (exit $status)" "" \
  "/health answered $health_s s after the first launcher start. ${bundle_note}smoke_test.py exit $smoke_status." \
  "" '```json' "$(cat "$WORK/smoke-summary.json")" '```'
if [ "$status" = 0 ]; then
  say "smoke ($KIND): PASS (/health after $health_s s, smoke_test.py exit 0, server stopped${bundle_note:+, ${bundle_note%; }})"
else
  [ "$smoke_status" = 0 ] || note_error "smoke_test.py exited $smoke_status"
  show_logs
  say "smoke ($KIND): FAIL"
fi
exit "$status"

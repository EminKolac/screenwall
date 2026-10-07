#!/usr/bin/env bash
# Build the Screenwall release assets into dist/ at the repository root.
#
#   bash packaging/build_release.sh [VERSION]        e.g. 0.1.0   (make release VERSION=0.1.0)
#
# Assets (no version in the names, so .../releases/latest/download/<asset> links stay stable):
#   Screenwall-macOS.zip     Screenwall/Screenwall.command
#   Screenwall-Windows.zip   Screenwall/Screenwall.bat + Screenwall/launcher.ps1
#                            both: Screenwall/OKU-BENI.txt, Screenwall/VERSION,
#                                  Screenwall/app/backend/{app/, pyproject.toml, uv.lock},
#                                  Screenwall/app/frontend/dist/ (prebuilt UI)
#   install-macos.sh, install-windows.ps1, SHA256SUMS.txt
#
# The backend files are the ones git knows (tracked, or new and not ignored), so caches and stray
# local files never ship. The backend reads nothing at run time outside backend/app (the PDF fonts
# are in app/export/fonts). The UI comes from frontend/dist when that is newer than every frontend
# source; otherwise it is built with "npm run build" into this run's staging folder, so
# frontend/dist itself is never rewritten. SCREENWALL_BUILD_UI=1 always builds.
#
# Nothing is deleted: assets from an earlier run are moved to dist/.previous/<time>/, and each run
# stages in its own dist/.work/<time>/ folder. dist/ is gitignored; dot folders stay out of a
# "dist/*" upload glob.
#
# Runs on macOS (bash 3.2) and Linux (the CI build job). Needs zip, perl and sha256sum or shasum;
# npm only when the UI has to be built, uv only for the lock check.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PACKAGING="$REPO/packaging"
DIST="$REPO/dist"
ASSETS="Screenwall-macOS.zip Screenwall-Windows.zip install-macos.sh install-windows.ps1 SHA256SUMS.txt"

say() { printf '%s\n' "$*"; }
fail() {
  say "build_release: ERROR: $*" >&2
  exit 1
}

# ---------------------------------------------------------------- version and tools

VERSION="${1:-}"
if [ -z "$VERSION" ]; then
  VERSION="$(git -C "$REPO" describe --tags --always --dirty 2>/dev/null || echo dev)"
fi
VERSION="${VERSION#v}"
case "$VERSION" in
  '' | *[!0-9A-Za-z.+_-]*) fail "invalid version '$VERSION' (letters, digits and . + _ - only)" ;;
esac

for tool in zip perl; do
  command -v "$tool" >/dev/null 2>&1 || fail "$tool is required"
done
if command -v sha256sum >/dev/null 2>&1; then
  sha256() { sha256sum "$@"; }
elif command -v shasum >/dev/null 2>&1; then
  sha256() { shasum -a 256 "$@"; }
else
  fail "sha256sum or shasum is required"
fi

STAMP="$(date +%Y%m%d-%H%M%S)"
WORK="$DIST/.work/$STAMP"
[ -e "$WORK" ] && fail "staging folder already exists: $WORK (run again in a second)"
mkdir -p "$WORK"
say "Screenwall $VERSION -> $DIST"
say "staging: $WORK"

# Earlier assets move out of the way; nothing is overwritten.
for asset in $ASSETS; do
  if [ -e "$DIST/$asset" ]; then
    mkdir -p "$DIST/.previous/$STAMP"
    mv "$DIST/$asset" "$DIST/.previous/$STAMP/$asset"
  fi
done
[ -d "$DIST/.previous/$STAMP" ] && say "earlier assets moved to dist/.previous/$STAMP/"

if git -C "$REPO" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  dirty="$(git -C "$REPO" status --porcelain -- backend/app backend/pyproject.toml \
    backend/uv.lock frontend packaging 2>/dev/null || true)"
  if [ -n "$dirty" ]; then
    say "warning: the working tree has uncommitted changes in shipped paths; the zips contain them"
  fi
fi

# ---------------------------------------------------------------- lock file

# The launchers install with "uv sync --frozen", which trusts uv.lock as it is: refuse a lock
# that no longer matches pyproject.toml.
if command -v uv >/dev/null 2>&1; then
  (cd "$REPO/backend" && uv lock --check) || fail "backend/uv.lock does not match pyproject.toml"
else
  say "warning: uv not found, uv.lock was not checked against pyproject.toml"
fi

# ---------------------------------------------------------------- UI

UI_SRC="$REPO/frontend/dist"
ui_stale() {
  [ -f "$UI_SRC/index.html" ] || return 0
  [ -n "$(cd "$REPO/frontend" && find src public index.html package.json package-lock.json \
    vite.config.ts tsconfig.json -newer dist/index.html -type f 2>/dev/null | head -n 1)" ]
}
if [ "${SCREENWALL_BUILD_UI:-0}" = "1" ] || ui_stale; then
  command -v npm >/dev/null 2>&1 || fail "npm is required to build the UI"
  [ -d "$REPO/frontend/node_modules" ] || fail "frontend/node_modules is missing: run 'npm ci' in frontend/"
  say "building the UI into the staging folder (frontend/dist is missing or older than its sources)"
  (cd "$REPO/frontend" && npm run build -- --outDir "$WORK/ui-dist") || fail "UI build failed"
  UI_SRC="$WORK/ui-dist"
else
  say "using the prebuilt UI in frontend/dist"
fi
[ -f "$UI_SRC/index.html" ] || fail "no index.html in $UI_SRC"
grep -q "<title>Screenwall</title>" "$UI_SRC/index.html" || fail "$UI_SRC/index.html is not the Screenwall UI"
ls "$UI_SRC"/assets/*.js >/dev/null 2>&1 || fail "no JavaScript bundle in $UI_SRC/assets"

# ---------------------------------------------------------------- common tree

COMMON="$WORK/common/Screenwall"
mkdir -p "$COMMON/app/backend" "$COMMON/app/frontend/dist"

copy_file() { # copy_file <source> <destination>
  mkdir -p "$(dirname "$2")"
  cp "$1" "$2"
}

if git -C "$REPO" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  untracked="$(git -C "$REPO" ls-files -o --exclude-standard -- backend/app)"
  [ -n "$untracked" ] && say "note: shipping files git does not track yet:" && say "$untracked"
  git -C "$REPO" ls-files -z -c -o --exclude-standard -- backend/app |
    while IFS= read -r -d '' rel; do
      # A tracked file deleted in the working tree is listed too; it is not shipped.
      [ -f "$REPO/$rel" ] || continue
      copy_file "$REPO/$rel" "$COMMON/app/$rel"
    done
else
  (cd "$REPO/backend" && tar cf - --exclude __pycache__ --exclude '*.pyc' --exclude .DS_Store app) |
    (cd "$COMMON/app/backend" && tar xf -)
fi
copy_file "$REPO/backend/pyproject.toml" "$COMMON/app/backend/pyproject.toml"
copy_file "$REPO/backend/uv.lock" "$COMMON/app/backend/uv.lock"
(cd "$UI_SRC" && tar cf - --exclude .DS_Store .) | (cd "$COMMON/app/frontend/dist" && tar xf -)
printf '%s\n' "$VERSION" >"$COMMON/VERSION"

for required in app/backend/app/main.py app/backend/app/export/fonts/DejaVuSans.ttf \
  app/backend/pyproject.toml app/backend/uv.lock app/frontend/dist/index.html VERSION; do
  [ -f "$COMMON/$required" ] || fail "staged tree is missing $required"
done

# Predictable modes in the zips, whatever the umask: folders 755, files 644.
find "$COMMON" -type d -exec chmod 755 {} +
find "$COMMON" -type f -exec chmod 644 {} +

# Text helpers. to_crlf: Windows line endings. add_bom: UTF-8 byte order mark (once).
to_crlf() { perl -pe 's/\r?\n/\r\n/' "$1" >"$2"; }
add_bom() { perl -i -pe 'if ($. == 1) { s/^\xEF\xBB\xBF//; $_ = "\xEF\xBB\xBF" . $_ }' "$1"; }

# ---------------------------------------------------------------- macOS tree

MAC="$WORK/macos/Screenwall"
mkdir -p "$WORK/macos"
cp -R "$COMMON" "$MAC"
perl -pe 's/\r\n/\n/' "$PACKAGING/OKU-BENI.txt" >"$MAC/OKU-BENI.txt"
perl -pe 's/\r\n/\n/' "$PACKAGING/macos/Screenwall.command" >"$MAC/Screenwall.command"
chmod 644 "$MAC/OKU-BENI.txt"
chmod 755 "$MAC/Screenwall.command"

# ---------------------------------------------------------------- Windows tree

WIN="$WORK/windows/Screenwall"
mkdir -p "$WORK/windows"
cp -R "$COMMON" "$WIN"
to_crlf "$PACKAGING/windows/Screenwall.bat" "$WIN/Screenwall.bat"
to_crlf "$PACKAGING/windows/launcher.ps1" "$WIN/launcher.ps1"
add_bom "$WIN/launcher.ps1" # Windows PowerShell 5.1 reads a BOM-less script as the ANSI code page
to_crlf "$PACKAGING/OKU-BENI.txt" "$WIN/OKU-BENI.txt"
add_bom "$WIN/OKU-BENI.txt" # older Notepad versions guess the encoding without it
chmod 644 "$WIN/Screenwall.bat" "$WIN/launcher.ps1" "$WIN/OKU-BENI.txt"

# ---------------------------------------------------------------- zips and installers

# -X: no extra file attributes (uid/gid, macOS metadata); Unix modes are kept, so the launcher
# stays executable after unzip / Archive Utility.
(cd "$WORK/macos" && zip -q -r -X "$DIST/Screenwall-macOS.zip" Screenwall)
(cd "$WORK/windows" && zip -q -r -X "$DIST/Screenwall-Windows.zip" Screenwall)

cp "$PACKAGING/install-macos.sh" "$DIST/install-macos.sh"
chmod 755 "$DIST/install-macos.sh"
# Piped into "iex" by Windows PowerShell 5.1, which may decode it as ISO-8859-1: ASCII only.
if LC_ALL=C grep -q '[^ -~[:space:]]' "$PACKAGING/install-windows.ps1"; then
  fail "packaging/install-windows.ps1 must be ASCII-only (write Turkish letters as \\uXXXX)"
fi
to_crlf "$PACKAGING/install-windows.ps1" "$DIST/install-windows.ps1"
chmod 644 "$DIST/install-windows.ps1"

(cd "$DIST" && sha256 Screenwall-macOS.zip Screenwall-Windows.zip install-macos.sh \
  install-windows.ps1 >SHA256SUMS.txt)

# ---------------------------------------------------------------- checks and summary

check_zip() { # check_zip <zip> <entry>...
  local zip="$1" listing entry
  shift
  listing="$(unzip -Z1 "$zip")"
  for entry in "$@"; do
    printf '%s\n' "$listing" | grep -qx "$entry" || fail "$zip has no $entry"
  done
}
COMMON_ENTRIES="Screenwall/VERSION Screenwall/OKU-BENI.txt Screenwall/app/backend/app/main.py
Screenwall/app/backend/pyproject.toml Screenwall/app/backend/uv.lock
Screenwall/app/frontend/dist/index.html"
# shellcheck disable=SC2086 # word splitting of the entry list is intended
check_zip "$DIST/Screenwall-macOS.zip" $COMMON_ENTRIES Screenwall/Screenwall.command
# shellcheck disable=SC2086
check_zip "$DIST/Screenwall-Windows.zip" $COMMON_ENTRIES Screenwall/Screenwall.bat \
  Screenwall/launcher.ps1
for zip_file in "$DIST/Screenwall-macOS.zip" "$DIST/Screenwall-Windows.zip"; do
  if unzip -Z1 "$zip_file" | grep -E '__pycache__|\.pyc$|\.DS_Store|(^|/)\.env' >/dev/null; then
    fail "$zip_file contains caches or local files"
  fi
done

say ""
say "assets in $DIST:"
for asset in $ASSETS; do
  printf '  %-24s %10s bytes\n' "$asset" "$(wc -c <"$DIST/$asset" | tr -d ' ')"
done
say ""
cat "$DIST/SHA256SUMS.txt"

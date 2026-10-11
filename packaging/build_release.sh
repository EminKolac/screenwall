#!/usr/bin/env bash
# Build the Screenwall release assets into dist/ at the repository root.
#
#   bash packaging/build_release.sh [VERSION]        e.g. 0.1.1   (make release VERSION=0.1.1)
#
# Assets (no version in the names, so .../releases/latest/download/<asset> links stay stable):
#   Screenwall-macOS.dmg     disk image (volume "Screenwall"): Screenwall.app, an Applications
#                            link to drag it onto, OKU-BENI.txt. Built only on macOS (hdiutil).
#   Screenwall-macOS.zip     Screenwall/Screenwall.command, Screenwall/OKU-BENI.txt,
#                            Screenwall/VERSION,
#                            Screenwall/app/backend/{app/, pyproject.toml, uv.lock},
#                            Screenwall/app/frontend/dist/ (prebuilt UI)
#   install-macos.sh, SHA256SUMS.txt (covers the dmg, the zip and install-macos.sh)
#
# Screenwall.app holds the zip's Screenwall folder unchanged in Contents/Resources/Screenwall;
# Contents/MacOS/Screenwall (packaging/macos/app/Screenwall) opens its Screenwall.command in
# Terminal. Info.plist comes from packaging/macos/app/Info.plist (@VERSION@ filled in), the icon
# is the committed packaging/macos/app/AppIcon.icns (packaging/macos/app/make_icon.py draws it).
# The app is not signed.
#
# macOS only (Apple Silicon and Intel). The Windows launcher and installer were retired to
# archive/packaging-windows-2026-10-07/ and are not built.
#
# The backend files are the ones git knows (tracked, or new and not ignored), so caches and stray
# local files never ship. The backend reads nothing at run time outside backend/app (the PDF fonts
# and their licence, LICENSE-DejaVu.txt, are in app/export/fonts). The UI comes from
# frontend/dist when that is newer than every frontend source; otherwise it is built with
# "npm run build" into this run's staging folder, so frontend/dist itself is never rewritten.
# SCREENWALL_BUILD_UI=1 always builds.
#
# Nothing is deleted: assets from an earlier run are moved to dist/.previous/<time>/, and each run
# stages in its own dist/.work/<time>/ folder. dist/ is gitignored; dot folders stay out of a
# "dist/*" upload glob.
#
# Runs on macOS (bash 3.2; the CI build job) and Linux (everything but the dmg). Needs zip, perl
# and sha256sum or shasum; npm only when the UI has to be built, uv only for the lock check;
# hdiutil, ditto and plutil (all part of macOS) for the dmg.
set -euo pipefail
# macOS tar and cp: no ._ AppleDouble files or extended attributes in the staged trees.
export COPYFILE_DISABLE=1

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PACKAGING="$REPO/packaging"
DIST="$REPO/dist"
ASSETS="Screenwall-macOS.dmg Screenwall-macOS.zip install-macos.sh SHA256SUMS.txt"
# No longer built; an old copy left in dist/ is moved aside with the others, so a "dist/*"
# upload never picks it up.
RETIRED_ASSETS="Screenwall-Windows.zip install-windows.ps1"

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
# /openapi.json shows __version__ from backend/app/__init__.py, which is kept by hand: a release
# version (plain x.y.z) must match it. Dev versions such as 0.0.0-dev.<sha> are not checked.
if printf '%s\n' "$VERSION" | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+$'; then
  APP_VERSION="$(sed -n 's/^__version__ = "\([^"]*\)"$/\1/p' "$REPO/backend/app/__init__.py")"
  [ "$VERSION" = "$APP_VERSION" ] ||
    fail "version $VERSION does not match __version__ \"$APP_VERSION\" in backend/app/__init__.py"
fi

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
for asset in $ASSETS $RETIRED_ASSETS; do
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
    say "warning: the working tree has uncommitted changes in shipped paths; the assets contain them"
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
# AGPL-3.0: every copy of the program carries the licence and the third-party notices
copy_file "$REPO/LICENSE" "$COMMON/LICENSE"
copy_file "$REPO/THIRD_PARTY_LICENSES.md" "$COMMON/THIRD_PARTY_LICENSES.md"

for required in app/backend/app/main.py app/backend/app/export/fonts/DejaVuSans.ttf \
  app/backend/app/export/fonts/LICENSE-DejaVu.txt app/backend/pyproject.toml \
  app/backend/uv.lock app/frontend/dist/index.html VERSION LICENSE THIRD_PARTY_LICENSES.md; do
  [ -f "$COMMON/$required" ] || fail "staged tree is missing $required"
done

# Predictable modes in the zips, whatever the umask: folders 755, files 644.
find "$COMMON" -type d -exec chmod 755 {} +
find "$COMMON" -type f -exec chmod 644 {} +

# ---------------------------------------------------------------- macOS tree

MAC="$WORK/macos/Screenwall"
mkdir -p "$WORK/macos"
cp -R "$COMMON" "$MAC"
perl -pe 's/\r\n/\n/' "$PACKAGING/OKU-BENI.txt" >"$MAC/OKU-BENI.txt"
perl -pe 's/\r\n/\n/' "$PACKAGING/macos/Screenwall.command" >"$MAC/Screenwall.command"
chmod 644 "$MAC/OKU-BENI.txt"
chmod 755 "$MAC/Screenwall.command"

# ---------------------------------------------------------------- zip and installer

# -X: no extra file attributes (uid/gid, macOS metadata); Unix modes are kept, so the launcher
# stays executable after unzip / Archive Utility.
(cd "$WORK/macos" && zip -q -r -X "$DIST/Screenwall-macOS.zip" Screenwall)

cp "$PACKAGING/install-macos.sh" "$DIST/install-macos.sh"
chmod 755 "$DIST/install-macos.sh"

# ---------------------------------------------------------------- Screenwall.app

APP_SRC="$PACKAGING/macos/app"
APP="$WORK/app/Screenwall.app"
for required in Info.plist Screenwall AppIcon.icns; do
  [ -f "$APP_SRC/$required" ] || fail "packaging/macos/app/$required is missing"
done
grep -q '@VERSION@' "$APP_SRC/Info.plist" || fail "packaging/macos/app/Info.plist has no @VERSION@"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp -R "$MAC" "$APP/Contents/Resources/Screenwall"
# VERSION holds only [0-9A-Za-z.+_-] (checked above): safe inside the plist's XML strings.
VERSION="$VERSION" perl -pe 's/\r\n/\n/; s/\@VERSION\@/$ENV{VERSION}/g' "$APP_SRC/Info.plist" \
  >"$APP/Contents/Info.plist"
perl -pe 's/\r\n/\n/' "$APP_SRC/Screenwall" >"$APP/Contents/MacOS/Screenwall"
cp "$APP_SRC/AppIcon.icns" "$APP/Contents/Resources/AppIcon.icns"
printf 'APPL????' >"$APP/Contents/PkgInfo"
find "$APP" -type d -exec chmod 755 {} +
chmod 644 "$APP/Contents/Info.plist" "$APP/Contents/PkgInfo" "$APP/Contents/Resources/AppIcon.icns"
chmod 755 "$APP/Contents/MacOS/Screenwall"

grep -q '@VERSION@' "$APP/Contents/Info.plist" && fail "Info.plist still has @VERSION@"
if command -v plutil >/dev/null 2>&1; then
  plutil -lint -s "$APP/Contents/Info.plist" || fail "Screenwall.app Info.plist is not a valid plist"
  for key in CFBundleShortVersionString CFBundleVersion; do
    [ "$(plutil -extract "$key" raw "$APP/Contents/Info.plist")" = "$VERSION" ] ||
      fail "Info.plist $key is not $VERSION"
  done
  [ "$(plutil -extract CFBundleIdentifier raw "$APP/Contents/Info.plist")" = \
    "site.screenwall.Screenwall" ] || fail "Info.plist CFBundleIdentifier is wrong"
fi

# ---------------------------------------------------------------- dmg

# hdiutil now and then fails on a busy runner ("Resource busy"): up to three tries, each into its
# own folder, so a half-written image is never renamed into dist/.
make_dmg() { # make_dmg <source folder> <dmg>
  local try=1 out
  while [ $try -le 3 ]; do
    out="$WORK/dmg-try-$try/$(basename "$2")"
    mkdir -p "$(dirname "$out")"
    if hdiutil create -quiet -volname Screenwall -srcfolder "$1" -fs HFS+ -format UDZO \
      -imagekey zlib-level=9 "$out"; then
      mv "$out" "$2"
      return 0
    fi
    say "hdiutil create failed (try $try of 3)"
    try=$((try + 1))
    sleep 5
  done
  return 1
}

# What is wrong in a mounted dmg, or nothing when it holds what Finder should show.
dmg_problem() { # dmg_problem <mount point>
  local mnt="$1" app="$1/Screenwall.app" entries
  entries="$(cd "$mnt" && ls -A | grep -v '^\.' | tr '\n' ' ' || true)"
  if [ "$entries" != "Applications OKU-BENI.txt Screenwall.app " ]; then
    say "unexpected contents: $entries"
  elif [ ! -L "$mnt/Applications" ] || [ "$(readlink "$mnt/Applications")" != /Applications ]; then
    say "Applications is not a link to /Applications"
  elif [ ! -x "$app/Contents/MacOS/Screenwall" ]; then
    say "Screenwall.app/Contents/MacOS/Screenwall is missing or not executable"
  elif [ ! -x "$app/Contents/Resources/Screenwall/Screenwall.command" ]; then
    say "the launcher in Screenwall.app is missing or not executable"
  elif [ "$(cat "$app/Contents/Resources/Screenwall/VERSION")" != "$VERSION" ]; then
    say "Screenwall.app holds another VERSION"
  elif ! plutil -lint -s "$app/Contents/Info.plist"; then
    say "Info.plist is not valid"
  elif [ -n "$(find "$app" \( -name '._*' -o -name .DS_Store -o -name __pycache__ \
    -o -name '*.pyc' \) -print | head -n 1)" ]; then
    say "Screenwall.app contains caches or macOS metadata files"
  fi
}

# Mount the image read-only, as a user's double-click does (but out of Finder's sight), check
# it, detach it.
check_dmg() { # check_dmg <dmg>
  local mnt="$WORK/dmg-check" problem
  mkdir -p "$mnt"
  hdiutil attach -quiet -nobrowse -readonly -noautoopen -mountpoint "$mnt" "$1" ||
    fail "the dmg does not mount"
  problem="$(dmg_problem "$mnt")"
  hdiutil detach -quiet "$mnt" || hdiutil detach -quiet -force "$mnt" ||
    say "warning: could not detach $mnt"
  [ -z "$problem" ] || fail "Screenwall-macOS.dmg: $problem"
}

SUMMED="Screenwall-macOS.zip install-macos.sh"
if command -v hdiutil >/dev/null 2>&1; then
  for tool in ditto plutil; do
    command -v "$tool" >/dev/null 2>&1 || fail "$tool is required for the dmg"
  done
  DMG_STAGE="$WORK/dmg/Screenwall"
  mkdir -p "$DMG_STAGE"
  ditto "$APP" "$DMG_STAGE/Screenwall.app"
  ln -s /Applications "$DMG_STAGE/Applications"
  cp "$MAC/OKU-BENI.txt" "$DMG_STAGE/OKU-BENI.txt"
  make_dmg "$DMG_STAGE" "$DIST/Screenwall-macOS.dmg" || fail "hdiutil could not create the dmg"
  hdiutil verify -quiet "$DIST/Screenwall-macOS.dmg" || fail "hdiutil verify failed on the dmg"
  check_dmg "$DIST/Screenwall-macOS.dmg"
  SUMMED="Screenwall-macOS.dmg $SUMMED"
else
  say "note: hdiutil not found (this is not macOS): Screenwall-macOS.dmg is not built and"
  say "      SHA256SUMS.txt covers the zip and install-macos.sh only. Build on a Mac for the dmg."
fi

# shellcheck disable=SC2086 # word splitting of the asset list is intended
(cd "$DIST" && sha256 $SUMMED >SHA256SUMS.txt)

# ---------------------------------------------------------------- checks and summary

check_zip() { # check_zip <zip> <entry>...
  local zip="$1" listing entry
  shift
  listing="$(unzip -Z1 "$zip")"
  for entry in "$@"; do
    printf '%s\n' "$listing" | grep -qx "$entry" || fail "$zip has no $entry"
  done
}
MAC_ENTRIES="Screenwall/VERSION Screenwall/OKU-BENI.txt Screenwall/Screenwall.command
Screenwall/LICENSE Screenwall/THIRD_PARTY_LICENSES.md
Screenwall/app/backend/app/main.py Screenwall/app/backend/app/export/fonts/DejaVuSans.ttf
Screenwall/app/backend/app/export/fonts/LICENSE-DejaVu.txt
Screenwall/app/backend/pyproject.toml Screenwall/app/backend/uv.lock
Screenwall/app/frontend/dist/index.html"
# shellcheck disable=SC2086 # word splitting of the entry list is intended
check_zip "$DIST/Screenwall-macOS.zip" $MAC_ENTRIES
MAC_LISTING="$(unzip -Z1 "$DIST/Screenwall-macOS.zip")"
if printf '%s\n' "$MAC_LISTING" |
  grep -E '__pycache__|\.pyc$|\.DS_Store|(^|/)\._|(^|/)\.env' >/dev/null; then
  fail "Screenwall-macOS.zip contains caches or local files"
fi
if printf '%s\n' "$MAC_LISTING" | grep -iE '\.(bat|ps1|cmd|exe)$' >/dev/null; then
  fail "Screenwall-macOS.zip contains Windows files"
fi

say ""
say "assets in $DIST:"
for asset in $ASSETS; do
  [ -e "$DIST/$asset" ] || continue
  printf '  %-24s %10s bytes\n' "$asset" "$(wc -c <"$DIST/$asset" | tr -d ' ')"
done
say ""
cat "$DIST/SHA256SUMS.txt"

#!/bin/sh
# Screenwall installer for macOS.
#
# Usage:
#   curl -LsSf https://github.com/EminKolac/screenwall/releases/latest/download/install-macos.sh | sh
#
# Downloads Screenwall-macOS.zip from the latest release, checks it against SHA256SUMS.txt,
# unpacks it to ~/Screenwall and starts Screenwall.command in this terminal. Idempotent: when the
# same version is already installed it only starts it. A different version moves the old folder
# aside (~/Screenwall-eski-<version>-<time>); nothing is deleted. The download stays in $TMPDIR.
# Files fetched with curl carry no quarantine flag, so Gatekeeper does not stop the launcher.
#
# Optional environment:
#   SCREENWALL_INSTALL_DIR    install folder (default ~/Screenwall)
#   SCREENWALL_RELEASE_URL    where the assets are (default: the latest GitHub release)
#   SCREENWALL_REINSTALL=1    replace the install even when the version is the same
#   SCREENWALL_NO_START=1     install only, do not start
#
# POSIX sh (it is piped into sh). Everything runs inside main(), so the shell has read the whole
# script before anything happens.
set -eu

say() { printf '%s\n' "$*"; }
die() {
  say "HATA: $*" >&2
  exit 1
}

main() {
  release_url="${SCREENWALL_RELEASE_URL:-https://github.com/EminKolac/screenwall/releases/latest/download}"
  release_url="${release_url%/}"
  install_dir="${SCREENWALL_INSTALL_DIR:-$HOME/Screenwall}"
  install_dir="${install_dir%/}"
  stamp="$(date +%Y%m%d-%H%M%S)"

  [ "$(uname -s)" = "Darwin" ] || die "Bu kurulum betiği yalnızca macOS içindir."
  for tool in curl shasum ditto; do
    command -v "$tool" >/dev/null 2>&1 || die "Gerekli araç bulunamadı: $tool"
  done

  work="$(mktemp -d "${TMPDIR:-/tmp}/screenwall-install.XXXXXX")" ||
    die "Geçici klasör oluşturulamadı."
  zip="$work/Screenwall-macOS.zip"

  say "Screenwall indiriliyor: $release_url/Screenwall-macOS.zip"
  curl -fL --progress-bar -o "$zip" "$release_url/Screenwall-macOS.zip" ||
    die "İndirme başarısız oldu. İnternet bağlantınızı kontrol edip tekrar deneyin."
  curl -fsSL -o "$work/SHA256SUMS.txt" "$release_url/SHA256SUMS.txt" ||
    die "SHA256SUMS.txt indirilemedi; dosya doğrulanamadan kurulum yapılmaz."

  # SHA256SUMS.txt lines look like "<sha256>  <file name>".
  expected="$(awk '$2 == "Screenwall-macOS.zip" || $2 == "*Screenwall-macOS.zip" { print $1 }' \
    "$work/SHA256SUMS.txt")"
  actual="$(shasum -a 256 "$zip" | awk '{ print $1 }')"
  [ -n "$expected" ] && [ "$expected" = "$actual" ] ||
    die "İndirilen dosya doğrulanamadı (SHA256 uyuşmuyor). Kurulum durduruldu."

  mkdir "$work/unpacked"
  ditto -x -k "$zip" "$work/unpacked" || die "Zip açılamadı."
  new_dir="$work/unpacked/Screenwall"
  [ -f "$new_dir/Screenwall.command" ] ||
    die "Zip beklenen dosyaları içermiyor (Screenwall/Screenwall.command)."
  new_version="$(head -n 1 "$new_dir/VERSION" 2>/dev/null || echo bilinmiyor)"

  if [ -e "$install_dir" ]; then
    old_version="$(head -n 1 "$install_dir/VERSION" 2>/dev/null || echo bilinmiyor)"
    if [ "$old_version" = "$new_version" ] && [ "${SCREENWALL_REINSTALL:-0}" != "1" ]; then
      say "Screenwall $new_version zaten kurulu: $install_dir"
    else
      aside="$install_dir-eski-$old_version-$stamp"
      mv "$install_dir" "$aside" || die "Eski klasör taşınamadı: $install_dir"
      say "Önceki sürüm kenara alındı: $aside"
      say "Artık gerekmiyorsa bu klasörü kendiniz çöp kutusuna taşıyabilirsiniz."
      mv "$new_dir" "$install_dir"
      say "Kuruldu: Screenwall $new_version -> $install_dir"
    fi
  else
    mkdir -p "$(dirname "$install_dir")"
    mv "$new_dir" "$install_dir"
    say "Kuruldu: Screenwall $new_version -> $install_dir"
  fi
  chmod +x "$install_dir/Screenwall.command"

  say "Daha sonra başlatmak için Finder'da şu dosyaya çift tıklayın: $install_dir/Screenwall.command"
  if [ "${SCREENWALL_NO_START:-0}" = "1" ]; then
    return 0
  fi
  say ""
  # stdin is this script's pipe when run as "curl ... | sh": give the launcher /dev/null instead.
  exec "$install_dir/Screenwall.command" </dev/null
}

main "$@"

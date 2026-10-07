# Screenwall installer for Windows. EXPERIMENTAL until the windows-latest CI smoke job passes.
#
# Usage (PowerShell or cmd):
#   powershell -ExecutionPolicy ByPass -c "irm https://github.com/EminKolac/screenwall/releases/latest/download/install-windows.ps1 | iex"
#
# Downloads Screenwall-Windows.zip from the latest release, checks it against SHA256SUMS.txt,
# unpacks it to %LOCALAPPDATA%\Programs\Screenwall and starts launcher.ps1. Idempotent: when the
# same version is already installed it only starts it. A different version moves the old folder
# aside (Screenwall-eski-<version>-<time>); nothing is deleted. The downloaded zip stays in %TEMP%.
#
# Optional environment:
#   SCREENWALL_INSTALL_DIR    install folder (default %LOCALAPPDATA%\Programs\Screenwall,
#                             or %USERPROFILE%\Screenwall when LOCALAPPDATA is not set)
#   SCREENWALL_RELEASE_URL    where the assets are (default: the latest GitHub release)
#   SCREENWALL_REINSTALL=1    replace the install even when the version is the same
#   SCREENWALL_NO_START=1     install only, do not start
#
# Windows PowerShell 5.1 compatible. This file is kept ASCII-only on purpose: "irm | iex" can
# decode it as ISO-8859-1 there, which would garble UTF-8 letters (and a BOM would break iex).
# Turkish letters are therefore written as \uXXXX escapes that Say decodes. Everything runs inside
# one function, so iex leaves no variables behind and an error never closes the user's window.

function Install-Screenwall {
    $ErrorActionPreference = 'Stop'
    $ProgressPreference = 'SilentlyContinue'  # the progress bar makes 5.1 downloads very slow
    # 3072 = TLS 1.2, which older .NET defaults on Windows 10 do not enable (GitHub requires it).
    [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor 3072

    # Writes a message whose \uXXXX escapes are decoded; {0} and {1} are replaced by the values
    # afterwards, so paths with backslashes are never unescaped.
    function Say([string]$Text, [string]$First = '', [string]$Second = '') {
        $line = [regex]::Unescape($Text).Replace('{0}', $First).Replace('{1}', $Second)
        Write-Host $line
    }

    function EnvOr([string]$Name, [string]$Default) {
        $value = [Environment]::GetEnvironmentVariable($Name)
        if ([string]::IsNullOrWhiteSpace($value)) { return $Default }
        return $value
    }

    $releaseUrl = (EnvOr 'SCREENWALL_RELEASE_URL' `
        'https://github.com/EminKolac/screenwall/releases/latest/download').TrimEnd('/')
    if ($env:LOCALAPPDATA) {
        $defaultDir = Join-Path $env:LOCALAPPDATA 'Programs\Screenwall'
    } else {
        $defaultDir = Join-Path $env:USERPROFILE 'Screenwall'
    }
    $installDir = EnvOr 'SCREENWALL_INSTALL_DIR' $defaultDir
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    $work = Join-Path ([IO.Path]::GetTempPath()) "screenwall-install-$stamp"
    $zip = Join-Path $work 'Screenwall-Windows.zip'
    $sums = Join-Path $work 'SHA256SUMS.txt'

    Say 'Screenwall kuruluyor. Windows s\u00fcr\u00fcm\u00fc deneyseldir.'
    try {
        New-Item -ItemType Directory -Force -Path $work | Out-Null
        Say '\u0130ndiriliyor: {0}' "$releaseUrl/Screenwall-Windows.zip"
        Invoke-WebRequest -Uri "$releaseUrl/Screenwall-Windows.zip" -OutFile $zip -UseBasicParsing
        Invoke-WebRequest -Uri "$releaseUrl/SHA256SUMS.txt" -OutFile $sums -UseBasicParsing
    } catch {
        Say 'HATA: \u0130ndirme ba\u015far\u0131s\u0131z oldu. \u0130nternet ba\u011flant\u0131n\u0131z\u0131 kontrol edip tekrar deneyin.'
        Say '({0})' $_.Exception.Message
        return
    }

    # SHA256SUMS.txt lines look like "<sha256>  <file name>".
    $expected = ''
    foreach ($line in Get-Content -LiteralPath $sums) {
        $parts = $line.Trim() -split '\s+'
        if ($parts.Count -ge 2 -and $parts[1].TrimStart('*') -eq 'Screenwall-Windows.zip') {
            $expected = $parts[0].ToLowerInvariant()
        }
    }
    $actual = (Get-FileHash -LiteralPath $zip -Algorithm SHA256).Hash.ToLowerInvariant()
    if (-not $expected -or $expected -ne $actual) {
        Say 'HATA: \u0130ndirilen dosya do\u011frulanamad\u0131 (SHA256 uyu\u015fmuyor). Kurulum durduruldu.'
        return
    }

    try {
        $unpacked = Join-Path $work 'unpacked'
        Expand-Archive -LiteralPath $zip -DestinationPath $unpacked -Force
        $newDir = Join-Path $unpacked 'Screenwall'
        if (-not (Test-Path -LiteralPath (Join-Path $newDir 'launcher.ps1'))) {
            Say 'HATA: Zip beklenen dosyalar\u0131 i\u00e7ermiyor ({0}).' 'Screenwall\launcher.ps1'
            return
        }
        $newVersion = (Get-Content -LiteralPath (Join-Path $newDir 'VERSION') -TotalCount 1).Trim()

        if (Test-Path -LiteralPath $installDir) {
            $oldVersion = 'bilinmiyor'
            $oldVersionFile = Join-Path $installDir 'VERSION'
            if (Test-Path -LiteralPath $oldVersionFile) {
                $oldVersion = (Get-Content -LiteralPath $oldVersionFile -TotalCount 1).Trim()
            }
            if ($oldVersion -eq $newVersion -and (EnvOr 'SCREENWALL_REINSTALL' '0') -ne '1') {
                Say 'Screenwall {0} zaten kurulu: {1}' $newVersion $installDir
            } else {
                $aside = "$installDir-eski-$oldVersion-$stamp"
                try {
                    Move-Item -LiteralPath $installDir -Destination $aside
                } catch {
                    Say 'HATA: Eski klas\u00f6r ta\u015f\u0131namad\u0131: {0}' $installDir
                    Say 'Screenwall a\u00e7\u0131ksa penceresini kapat\u0131p tekrar deneyin.'
                    return
                }
                Say '\u00d6nceki s\u00fcr\u00fcm kenara al\u0131nd\u0131: {0}' $aside
                Say 'Art\u0131k gerekmiyorsa bu klas\u00f6r\u00fc kendiniz Geri D\u00f6n\u00fc\u015f\u00fcm Kutusu''na ta\u015f\u0131yabilirsiniz.'
                Move-Item -LiteralPath $newDir -Destination $installDir
                Say 'Kuruldu: Screenwall {0} -> {1}' $newVersion $installDir
            }
        } else {
            $parent = Split-Path -Parent $installDir
            if ($parent) { New-Item -ItemType Directory -Force -Path $parent | Out-Null }
            Move-Item -LiteralPath $newDir -Destination $installDir
            Say 'Kuruldu: Screenwall {0} -> {1}' $newVersion $installDir
        }
    } catch {
        Say 'HATA: Kurulum tamamlanamad\u0131 ({0}).' $_.Exception.Message
        return
    }

    Say 'Daha sonra ba\u015flatmak i\u00e7in bu dosyaya \u00e7ift t\u0131klay\u0131n: {0}' (Join-Path $installDir 'Screenwall.bat')
    if ((EnvOr 'SCREENWALL_NO_START' '0') -eq '1') { return }
    Say ''
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $installDir 'launcher.ps1')
}

Install-Screenwall

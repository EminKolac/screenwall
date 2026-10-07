# Screenwall launcher for Windows. EXPERIMENTAL until the windows-latest CI smoke job passes.
#
# Screenwall.bat runs it:  powershell -NoProfile -ExecutionPolicy Bypass -File launcher.ps1
# The console window stays open while the app runs; Ctrl+C or closing the window stops the server.
#
# Steps (the same as the macOS Screenwall.command):
#   1. uv: found on PATH or in %USERPROFILE%\.local\bin, otherwise installed with the official
#      installer (UV_NO_MODIFY_PATH=1: the user's PATH is not changed).
#   2. "uv sync --frozen --no-dev --python 3.12" installs the locked backend dependencies into
#      %SCREENWALL_HOME%\venv (the first run downloads them; later runs only check).
#   3. Ollama and the auditor model, needed to approve documents. If the Ollama API does not
#      answer, Ollama is started when installed; otherwise the download page is shown and the app
#      starts anyway (documents are masked but nothing can be approved). A missing model is pulled.
#   4. The server on 127.0.0.1:%SCREENWALL_PORT% serves the API and the built UI. If that port
#      already answers /health, only the browser is opened.
#   5. Every server start gets a new random launch token in %SCREENWALL_HOME%\launch-token (the
#      folder is in the user's own profile). The server reads it from that file (LAUNCH_TOKEN_FILE)
#      and the browser gets it in the address (http://127.0.0.1:PORT/#k=<token>); without it no
#      session is issued, so other accounts on this computer cannot use the app (backend
#      config.py launch_token).
#
# Optional environment:
#   SCREENWALL_HOME           base folder (default %LOCALAPPDATA%\Screenwall) with data\ (documents),
#                             venv\ (Python) and logs\
#   SCREENWALL_PORT           port (default 8765)
#   SCREENWALL_NO_BROWSER=1   do not open the browser
#   SCREENWALL_SKIP_OLLAMA=1  skip the Ollama checks (CI)
#   AUDITOR_MODEL             auditor model (default qwen3.5:4b); the backend reads it too
#   OLLAMA_BASE_URL           Ollama API (default http://127.0.0.1:11434); the backend reads it too
#
# Written for Windows PowerShell 5.1: no PowerShell 7-only syntax (no ?? ?. && || or ternaries).
# The file is saved as UTF-8 with a BOM, without which 5.1 misreads the Turkish messages.

# Native tools (uv, ollama) write progress to stderr; their exit codes are checked instead.
$ErrorActionPreference = 'Continue'
# The Invoke-WebRequest progress bar makes Windows PowerShell 5.1 very slow.
$ProgressPreference = 'SilentlyContinue'

function Say([string]$Text) { Write-Host $Text }

function Fail([string]$Text) {
    Write-Host ''
    Write-Host "HATA: $Text" -ForegroundColor Red
    exit 1
}

function EnvOr([string]$Name, [string]$Default) {
    $value = [Environment]::GetEnvironmentVariable($Name)
    if ([string]::IsNullOrWhiteSpace($value)) { return $Default }
    return $value
}

# True when the URL answers 200 within a few seconds.
function Test-Url([string]$Url) {
    try {
        $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 3
        return ($response.StatusCode -eq 200)
    } catch {
        return $false
    }
}

function Open-Browser([string]$Url) {
    if ((EnvOr 'SCREENWALL_NO_BROWSER' '0') -eq '1') { return }
    try {
        Start-Process $Url
    } catch {
        Say "Tarayıcıda şu adresi açın: $Url"
    }
}

function Find-Exe([string]$Name, [string[]]$Candidates) {
    $command = Get-Command $Name -CommandType Application -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($command) { return $command.Path }
    foreach ($candidate in $Candidates) {
        if ($candidate -and (Test-Path -LiteralPath $candidate -PathType Leaf)) { return $candidate }
    }
    return $null
}

$AppRoot = $PSScriptRoot
$BackendDir = Join-Path $AppRoot 'app\backend'
$UiDistDir = Join-Path $AppRoot 'app\frontend\dist'
$VersionFile = Join-Path $AppRoot 'VERSION'
$Version = '?'
if (Test-Path -LiteralPath $VersionFile) { $Version = (Get-Content -LiteralPath $VersionFile -TotalCount 1).Trim() }

$LocalAppData = EnvOr 'LOCALAPPDATA' (Join-Path $env:USERPROFILE 'AppData\Local')
$SwHome = EnvOr 'SCREENWALL_HOME' (Join-Path $LocalAppData 'Screenwall')
$PortText = EnvOr 'SCREENWALL_PORT' '8765'
$Port = 0
if (-not [int]::TryParse($PortText, [ref]$Port) -or $Port -lt 1 -or $Port -gt 65535) {
    Fail "SCREENWALL_PORT bir port numarası olmalı (şu an: '$PortText')."
}
$AuditorModel = EnvOr 'AUDITOR_MODEL' 'qwen3.5:4b'
$OllamaUrl = (EnvOr 'OLLAMA_BASE_URL' 'http://127.0.0.1:11434').TrimEnd('/')
$AppUrl = "http://127.0.0.1:$Port"

$DataDir = Join-Path $SwHome 'data'
$VenvDir = Join-Path $SwHome 'venv'
$LogDir = Join-Path $SwHome 'logs'
$TokenFile = Join-Path $SwHome 'launch-token'

# The address to open: with the running server's launch token in the fragment when this home
# holds one. A fragment never reaches the server or its log; the UI sends it once to /api/session.
function Get-AppLink {
    try {
        $token = [string](Get-Content -LiteralPath $TokenFile -TotalCount 1 -ErrorAction Stop)
    } catch {
        return $AppUrl
    }
    $token = $token.Trim()
    if ($token -match '^[A-Za-z0-9_-]{16,256}$') { return "$AppUrl/#k=$token" }
    return $AppUrl
}

Say "Screenwall $Version (Windows, deneysel)"
Say "Veri klasörü: $SwHome"
Say ''

foreach ($dir in @($DataDir, $VenvDir, $LogDir)) {
    try {
        New-Item -ItemType Directory -Force -Path $dir -ErrorAction Stop | Out-Null
    } catch {
        Fail "Klasör oluşturulamadı: $dir"
    }
}
if (-not (Test-Path -LiteralPath (Join-Path $BackendDir 'uv.lock'))) {
    Fail "Uygulama dosyaları eksik: $BackendDir. Zip'i yeniden ayıklayın."
}
if (-not (Test-Path -LiteralPath (Join-Path $UiDistDir 'index.html'))) {
    Fail "Arayüz dosyaları eksik: $UiDistDir. Zip'i yeniden ayıklayın."
}

# Already running (another window, or an earlier start): just show it.
if (Test-Url "$AppUrl/health") {
    Say "Screenwall zaten çalışıyor: $AppUrl"
    Open-Browser (Get-AppLink)
    exit 0
}

# ---------------------------------------------------------------- 1) uv

$UvCandidates = @(
    (Join-Path $env:USERPROFILE '.local\bin\uv.exe'),
    (Join-Path $env:USERPROFILE '.cargo\bin\uv.exe')
)
$Uv = Find-Exe 'uv.exe' $UvCandidates
if (-not $Uv) {
    Say 'uv bulunamadı; resmî kurulum betiğiyle %USERPROFILE%\.local\bin klasörüne kuruluyor...'
    $env:UV_NO_MODIFY_PATH = '1'
    $env:UV_INSTALL_DIR = Join-Path $env:USERPROFILE '.local\bin'
    # 3072 = TLS 1.2, which older .NET defaults on Windows 10 do not enable.
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -Command `
        '[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor 3072; irm https://astral.sh/uv/install.ps1 | iex'
    $Uv = Find-Exe 'uv.exe' $UvCandidates
    if (-not $Uv) { Fail 'uv kurulamadı. İnternet bağlantınızı kontrol edip tekrar deneyin.' }
}

# ---------------------------------------------------------------- 2) Python environment

$env:UV_PROJECT_ENVIRONMENT = $VenvDir
Say 'Python ortamı hazırlanıyor (ilk açılışta paketler indirilir, birkaç dakika sürebilir)...'
Push-Location -LiteralPath $BackendDir
& $Uv sync --frozen --no-dev --python 3.12
$SyncCode = $LASTEXITCODE
Pop-Location
if ($SyncCode -ne 0) {
    Fail 'Python paketleri kurulamadı. İnternet bağlantınızı kontrol edip tekrar deneyin.'
}

# ---------------------------------------------------------------- 3) Ollama + auditor model

function Test-Model {
    try {
        $tags = Invoke-RestMethod -Uri "$OllamaUrl/api/tags" -UseBasicParsing -TimeoutSec 5
    } catch {
        return $false
    }
    foreach ($model in @($tags.models)) {
        if ($model -and $model.name -eq $AuditorModel) { return $true }
    }
    return $false
}

function Initialize-Ollama {
    $ollamaDir = Join-Path $LocalAppData 'Programs\Ollama'
    $ollama = Find-Exe 'ollama.exe' @((Join-Path $ollamaDir 'ollama.exe'))
    if (-not (Test-Url "$OllamaUrl/api/tags")) {
        $trayApp = Join-Path $ollamaDir 'ollama app.exe'
        if (Test-Path -LiteralPath $trayApp -PathType Leaf) {
            Say 'Ollama başlatılıyor...'
            Start-Process -FilePath $trayApp | Out-Null
        } elseif ($ollama) {
            Say 'Ollama başlatılıyor (ollama serve)...'
            $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
            # Hidden and separate: Ollama keeps running for other apps after this window closes.
            Start-Process -FilePath $ollama -ArgumentList 'serve' -WindowStyle Hidden `
                -RedirectStandardOutput (Join-Path $LogDir "ollama-$stamp.out.log") `
                -RedirectStandardError (Join-Path $LogDir "ollama-$stamp.log") | Out-Null
        } else {
            Say 'Ollama bulunamadı.'
            Say "Screenwall açılacak ve belgeleri maskeleyecek, ama Ollama ve $AuditorModel modeli"
            Say 'kurulana kadar hiçbir belge onaylanamaz. Ollama''yı https://ollama.com/download'
            Say 'adresinden kurun, sonra Screenwall''ı yeniden başlatın.'
            Open-Browser 'https://ollama.com/download'
            return
        }
        $deadline = (Get-Date).AddSeconds(30)
        while (-not (Test-Url "$OllamaUrl/api/tags") -and (Get-Date) -lt $deadline) {
            Start-Sleep -Seconds 1
        }
        if (-not (Test-Url "$OllamaUrl/api/tags")) {
            Say "Ollama yanıt vermiyor ($OllamaUrl). Belgeler onaylanamaz."
            return
        }
    }
    if (Test-Model) {
        Say "Denetçi modeli hazır: $AuditorModel"
        return
    }
    if (-not $ollama) {
        Say "$AuditorModel modeli yok ve ollama komutu bulunamadı."
        Say "Bir PowerShell penceresinde 'ollama pull $AuditorModel' çalıştırın."
        return
    }
    Say "Denetçi modeli indiriliyor: $AuditorModel (yaklaşık 3,4 GB, yalnızca bir kez)..."
    $env:OLLAMA_HOST = $OllamaUrl
    & $ollama pull $AuditorModel
    if ($LASTEXITCODE -ne 0) {
        Say "Model indirilemedi. Belgeler onaylanamaz; daha sonra 'ollama pull $AuditorModel' deneyin."
    }
}

if ((EnvOr 'SCREENWALL_SKIP_OLLAMA' '0') -eq '1') {
    Say 'Ollama denetimi atlandı (SCREENWALL_SKIP_OLLAMA=1).'
} else {
    Initialize-Ollama
}

# ---------------------------------------------------------------- 4) server

# Optional OCR: the backend looks for tesseract on PATH, PyMuPDF for its language data in
# TESSDATA_PREFIX. Both point at the default install folder when it exists.
$TesseractDir = Join-Path $env:ProgramFiles 'Tesseract-OCR'
if (Test-Path -LiteralPath (Join-Path $TesseractDir 'tesseract.exe') -PathType Leaf) {
    $env:PATH = "$env:PATH;$TesseractDir"
    if (-not $env:TESSDATA_PREFIX -and (Test-Path -LiteralPath (Join-Path $TesseractDir 'tessdata'))) {
        $env:TESSDATA_PREFIX = Join-Path $TesseractDir 'tessdata'
    }
}

# A new launch token for this start: 32 random bytes as hex, written without a BOM (the backend
# reads it as ASCII).
$TokenBytes = New-Object byte[] 32
$Rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
$Rng.GetBytes($TokenBytes)
$Rng.Dispose()
$LaunchToken = -join ($TokenBytes | ForEach-Object { $_.ToString('x2') })
try {
    [System.IO.File]::WriteAllText($TokenFile, $LaunchToken, (New-Object System.Text.ASCIIEncoding))
} catch {
    Fail "Başlatma anahtarı yazılamadı: $TokenFile"
}

$env:STORAGE_ROOT = $DataDir
$env:UI_DIST = $UiDistDir
$env:CORS_ALLOW_ORIGINS = "$AppUrl,http://localhost:$Port"
$env:LAUNCH_TOKEN_FILE = $TokenFile
$env:AUDITOR_MODEL = $AuditorModel

# One pair of log files per start (Start-Process cannot append); uvicorn logs to stderr.
$Stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$ServerLog = Join-Path $LogDir "server-$Stamp.log"
$ServerOut = Join-Path $LogDir "server-$Stamp.out.log"
$ServerArgs = @('run', '--frozen', '--no-dev', 'uvicorn', 'app.main:app',
    '--host', '127.0.0.1', '--port', "$Port")

Say "Sunucu başlatılıyor: $AppUrl"
try {
    $Server = Start-Process -FilePath $Uv -ArgumentList $ServerArgs -WorkingDirectory $BackendDir `
        -NoNewWindow -PassThru -RedirectStandardOutput $ServerOut -RedirectStandardError $ServerLog `
        -ErrorAction Stop
} catch {
    Fail "Sunucu başlatılamadı: $($_.Exception.Message)"
}
$null = $Server.Handle  # keeps ExitCode readable after exit (Windows PowerShell 5.1)

function Show-LogTail {
    Say "Son kayıtlar ($ServerLog):"
    if (Test-Path -LiteralPath $ServerLog) { Get-Content -LiteralPath $ServerLog -Tail 25 }
}

try {
    $started = Get-Date
    while (-not (Test-Url "$AppUrl/health")) {
        if ($Server.HasExited) {
            Say ''
            Say 'Sunucu başlamadı.'
            Show-LogTail
            Say ''
            Say "Port $Port başka bir program tarafından kullanılıyorsa başka bir port deneyin:"
            Say '  set SCREENWALL_PORT=8766  ve ardından Screenwall.bat'
            exit 1
        }
        if (((Get-Date) - $started).TotalSeconds -ge 90) {
            Say ''
            Say 'Sunucu 90 saniyede hazır olmadı.'
            Show-LogTail
            Say ''
            Say 'İlk açılış yavaş bir bilgisayarda uzun sürebilir; Screenwall''ı bir kez daha başlatın.'
            exit 1
        }
        Start-Sleep -Seconds 1
    }

    $seconds = [int]((Get-Date) - $started).TotalSeconds
    Say ''
    Say "Screenwall hazır ($seconds sn): $AppUrl"
    Say 'Kullanırken bu pencereyi açık tutun. Durdurmak için Ctrl+C''ye basın veya pencereyi kapatın.'
    Open-Browser "$AppUrl/#k=$LaunchToken"

    while (-not $Server.HasExited) { Start-Sleep -Milliseconds 500 }
    Say "Sunucu kapandı (çıkış kodu $($Server.ExitCode)). Kayıtlar: $ServerLog"
    exit $Server.ExitCode
} finally {
    # Ctrl+C, an error or "exit" above: stop the server this window started, with its python child.
    if (-not $Server.HasExited) {
        Say ''
        Say 'Screenwall durduruluyor...'
        & taskkill.exe /PID $Server.Id /T /F | Out-Null
    }
}

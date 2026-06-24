<#
  sound-splitter one-time setup.
  Run from the repo root in PowerShell:   .\setup.ps1
  Creates the backend venv, installs PyTorch (CUDA if an NVIDIA GPU is found, else CPU),
  installs Python + frontend deps, and seeds backend\.env from the example.
#>
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

function Step($msg) { Write-Host "`n=== $msg ===" -ForegroundColor Cyan }
function Warn($msg) { Write-Host "  ! $msg" -ForegroundColor Yellow }
function Ok($msg)   { Write-Host "  + $msg" -ForegroundColor Green }

# Pull newly-installed tools onto PATH without needing a fresh shell.
function Update-SessionPath {
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
                [Environment]::GetEnvironmentVariable("Path", "User")
}

$haveWinget = [bool](Get-Command winget -ErrorAction SilentlyContinue)
function Install-Dep($id, $name) {
    if (-not $haveWinget) {
        throw "$name is required but winget isn't available to install it automatically. " +
              "Install $name manually, then re-run .\setup.ps1"
    }
    Step "Installing $name (winget: $id)"
    winget install --id $id -e --accept-source-agreements --accept-package-agreements --disable-interactivity
    $code = $LASTEXITCODE
    Update-SessionPath
    # winget returns 0 on a fresh install. -1978335189 (0x8A15002B) means "already installed / no
    # applicable upgrade", which is fine for us. Anything else is a real failure - surface it so a
    # silent install (e.g. a declined source agreement) doesn't masquerade as success downstream.
    if ($code -ne 0 -and $code -ne -1978335189) {
        throw "winget failed to install $name (exit code $code). Install $name manually, then re-run .\setup.ps1"
    }
}

# --- prerequisites -----------------------------------------------------------
Step "Checking prerequisites"

# Python (prefer the py launcher; auto-install if missing). basic-pitch is gone, so any of
# 3.11-3.13 works; image-tabs / torch / CUDA / Demucs all support 3.13.
function Resolve-Python {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        foreach ($v in @("-3.13", "-3.12", "-3.11")) {
            & py $v --version *> $null
            if ($LASTEXITCODE -eq 0) { return @("py", $v) }
        }
    }
    if (Get-Command python -ErrorAction SilentlyContinue) {
        Warn "Using 'python' on PATH (no 'py' launcher). Make sure it's Python 3.11-3.13."
        return @("python")
    }
    # winget installs Python but its PATH update often isn't visible in this session (or even after
    # re-reading the registry). Fall back to the well-known install locations so a fresh setup
    # doesn't need a new terminal. Newest first; covers per-user and all-users (winget) installs.
    $candidates = @()
    foreach ($base in @("$env:LOCALAPPDATA\Programs\Python", "$env:ProgramFiles\Python", "${env:ProgramFiles(x86)}\Python")) {
        foreach ($v in @("313", "312", "311")) {
            $candidates += Join-Path $base "Python$v\python.exe"
        }
    }
    foreach ($exe in $candidates) {
        if (Test-Path $exe) {
            Warn "Found Python at $exe (not yet on PATH - using it directly)."
            return @($exe)
        }
    }
    return $null
}
$pyCmd = Resolve-Python
if (-not $pyCmd) {
    Warn "Python not found - installing 3.13..."
    Install-Dep "Python.Python.3.13" "Python 3.13"
    $pyCmd = Resolve-Python
}
if (-not $pyCmd) {
    throw "Python still not found after install. Open a NEW terminal and re-run .\setup.ps1"
}
Ok "Python: $((& $pyCmd[0] $pyCmd[1..($pyCmd.Length-1)] --version) 2>&1)"

# Node (auto-install if missing)
if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    Warn "Node.js not found - installing..."
    Install-Dep "OpenJS.NodeJS.LTS" "Node.js (LTS)"
}
if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    throw "Node.js still not found after install. Open a NEW terminal and re-run .\setup.ps1"
}
Ok "Node: $(node --version)"

# ffmpeg (optional - only needed to import your own non-WAV/FLAC recordings)
if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue) -and $haveWinget) {
    Warn "ffmpeg not found - installing (optional)..."
    try { Install-Dep "Gyan.FFmpeg" "ffmpeg" } catch { Warn "ffmpeg install skipped: $_" }
}
if (Get-Command ffmpeg -ErrorAction SilentlyContinue) { Ok "ffmpeg found" }
else { Warn "ffmpeg not available - optional, only needed to import your own takes." }

# GPU detection
$hasGpu = [bool](Get-Command nvidia-smi -ErrorAction SilentlyContinue)
if ($hasGpu) { Ok "NVIDIA GPU detected - installing CUDA PyTorch (fast separation)" }
else { Warn "No NVIDIA GPU detected - installing CPU PyTorch (separation will take a few minutes per song)" }

# --- backend -----------------------------------------------------------------
Step "Setting up backend (Python venv + PyTorch + deps)"
Set-Location "$root\backend"

if (-not (Test-Path ".venv")) {
    & $pyCmd[0] $pyCmd[1..($pyCmd.Length-1)] -m venv .venv
    Ok "Created backend\.venv"
} else { Ok "backend\.venv already exists" }

$venvPy = "$root\backend\.venv\Scripts\python.exe"
& $venvPy -m pip install --upgrade pip --quiet

if ($hasGpu) {
    & $venvPy -m pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu124
} else {
    & $venvPy -m pip install torch torchaudio
}
if ($LASTEXITCODE -ne 0) { throw "PyTorch install failed." }
Ok "PyTorch installed"

& $venvPy -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw "requirements.txt install failed." }
Ok "Backend dependencies installed"

# --- tab generation: image-tabs library + headless browser + OCR -------------
Step "Setting up tab generation (image-tabs: web capture + OCR)"

# image-tabs + canvas-to-image are sibling repos next to sound-splitter. Install editable so a
# later frozen build (PyInstaller) bundles them. (Distribution TODO: bundle Chromium + Tesseract
# into the installer too.)
$canvas = Join-Path $root "..\canvas-to-image"
$imgTabs = Join-Path $root "..\image-tabs"
if ((Test-Path $canvas) -and (Test-Path $imgTabs)) {
    & $venvPy -m pip install -e $canvas -e $imgTabs
    if ($LASTEXITCODE -ne 0) { throw "image-tabs install failed." }
    Ok "image-tabs installed"
} else {
    Warn "image-tabs / canvas-to-image not found next to sound-splitter - tab generation unavailable until they are."
}

# Headless Chromium for capturing the tab page (Playwright). Idempotent - skips if present.
& $venvPy -m playwright install chromium
if ($LASTEXITCODE -eq 0) { Ok "Playwright Chromium ready" } else { Warn "Playwright Chromium install failed - tab capture won't work." }

# Tesseract OCR. image-tabs looks for it on PATH or at %LOCALAPPDATA%\Tesseract-OCR.
$tessExe = Join-Path $env:LOCALAPPDATA "Tesseract-OCR\tesseract.exe"
if ((Get-Command tesseract -ErrorAction SilentlyContinue) -or (Test-Path $tessExe)) {
    Ok "Tesseract found"
} else {
    Warn "Tesseract not found - installing (no admin, into LocalAppData)..."
    $sevenZip = Join-Path $env:ProgramFiles "7-Zip\7z.exe"
    if (-not (Test-Path $sevenZip) -and $haveWinget) {
        try { Install-Dep "7zip.7zip" "7-Zip" } catch { Warn "7-Zip install skipped: $_" }
    }
    if (Test-Path $sevenZip) {
        $tmp = Join-Path $env:TEMP "tesseract-setup.exe"
        $url = "https://digi.bib.uni-mannheim.de/tesseract/tesseract-ocr-w64-setup-5.4.0.20240606.exe"
        try {
            Invoke-WebRequest -Uri $url -OutFile $tmp -UseBasicParsing
            & $sevenZip x -y ("-o" + (Join-Path $env:LOCALAPPDATA "Tesseract-OCR")) $tmp *> $null
            if (Test-Path $tessExe) { Ok "Tesseract installed to $env:LOCALAPPDATA\Tesseract-OCR" }
            else { Warn "Tesseract extraction failed - install it manually (UB-Mannheim) or set TESSERACT_CMD." }
        } catch { Warn "Tesseract download failed: $_ - install manually or set TESSERACT_CMD." }
    } else {
        Warn "7-Zip unavailable - install Tesseract manually (UB-Mannheim), put tesseract.exe on PATH, or set TESSERACT_CMD."
    }
}

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Warn "Created backend\.env - you MUST fill in your Spotify credentials before first run."
} else { Ok "backend\.env already exists" }

# --- frontend ----------------------------------------------------------------
Step "Setting up frontend (npm install)"
Set-Location "$root\frontend"
npm install
if ($LASTEXITCODE -ne 0) { throw "npm install failed." }
Ok "Frontend dependencies installed"

# --- done --------------------------------------------------------------------
Set-Location $root
Step "Setup complete"
Write-Host @"
Next steps:
  1. Install VB-CABLE (https://vb-audio.com/Cable/), reboot, and set Spotify's
     output device to 'CABLE Input'.
  2. Create a free Spotify Developer app and put your credentials in backend\.env
     (see the 'Set up on a new PC' section of README.md).
  3. Start the app:   .\run.ps1
"@ -ForegroundColor White

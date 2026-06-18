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

# --- prerequisites -----------------------------------------------------------
Step "Checking prerequisites"

# Python 3.13 (prefer the py launcher)
$pyCmd = $null
if (Get-Command py -ErrorAction SilentlyContinue) {
    & py -3.13 --version *> $null
    if ($LASTEXITCODE -eq 0) { $pyCmd = @("py", "-3.13") }
}
if (-not $pyCmd -and (Get-Command python -ErrorAction SilentlyContinue)) {
    $pyCmd = @("python")
    Warn "Using 'python' on PATH (couldn't find 'py -3.13'). Make sure it's Python 3.13."
}
if (-not $pyCmd) {
    throw "Python 3.13 not found. Install it from https://www.python.org/downloads/ (check 'Add to PATH'), then re-run."
}
Ok "Python: $((& $pyCmd[0] $pyCmd[1..($pyCmd.Length-1)] --version) 2>&1)"

# Node
if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    throw "Node.js not found. Install the LTS from https://nodejs.org/ , then re-run."
}
Ok "Node: $(node --version)"

# ffmpeg (only needed to import your own non-WAV/FLAC recordings)
if (Get-Command ffmpeg -ErrorAction SilentlyContinue) { Ok "ffmpeg found" }
else { Warn "ffmpeg not found - optional, only needed to import your own takes. https://www.gyan.dev/ffmpeg/builds/" }

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

<#
  Launch SoundSplitter as a desktop app (Tauri).

  Unlike .\run.ps1 (which opens the app in your web browser via two terminals),
  this builds/runs the native desktop window. The window provisions everything on
  first launch (installs Python deps via setup.ps1 and builds the UI if needed),
  starts the Python backend, and closes it again on exit — so it's a single app,
  nothing else to manage.

  Run from the repo root:   .\desktop.ps1
  First run compiles the Rust shell AND installs dependencies, so it can take a
  while; later runs are fast.
#>
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path

function Update-SessionPath {
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
                [Environment]::GetEnvironmentVariable("Path", "User") +
                ";$env:USERPROFILE\.cargo\bin"
}
Update-SessionPath

# Rust/Cargo is needed to build & run the desktop shell. Auto-install if missing.
if (-not (Get-Command cargo -ErrorAction SilentlyContinue)) {
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        Write-Host "Rust/Cargo not found and winget is unavailable. Install Rust from https://rustup.rs , then re-run." -ForegroundColor Yellow
        exit 1
    }
    Write-Host "Installing Rust (winget: Rustlang.Rustup)..." -ForegroundColor Cyan
    winget install --id Rustlang.Rustup -e --accept-source-agreements --accept-package-agreements --disable-interactivity
    Update-SessionPath
}
if (-not (Get-Command cargo -ErrorAction SilentlyContinue)) {
    Write-Host "Rust installed but not on PATH yet. Open a NEW terminal and re-run .\desktop.ps1" -ForegroundColor Yellow
    exit 1
}

# Tauri CLI (provides `cargo tauri`). Install once if missing.
& cargo tauri --version *> $null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Installing the Tauri CLI (one-time, compiles for a few minutes)..." -ForegroundColor Cyan
    cargo install tauri-cli --version "^2.0" --locked
}

# --- ensure all app dependencies are present (idempotent) --------------------
# A fast check; if anything is missing we run the full setup.ps1 (which is itself idempotent),
# so `.\desktop.ps1` is a single "install if needed, then run" command.
function Test-Provisioned {
    # Native stderr must not throw under the script's ErrorActionPreference=Stop:
    # basic-pitch (and TensorFlow) print import-time WARNINGs to stderr, and PS 5.1
    # turns redirected native stderr into error records - the check itself would die.
    $ErrorActionPreference = "Continue"
    $venvPy = Join-Path $root "backend\.venv\Scripts\python.exe"
    if (-not (Test-Path $venvPy)) { return $false }
    # backend python deps, including the image-tabs tab-generation stack
    & $venvPy -c "import torch, demucs, fastapi, image_tabs, cv2, pytesseract, playwright, basic_pitch" *> $null
    if ($LASTEXITCODE -ne 0) { return $false }
    # Tesseract OCR (on PATH or extracted into LocalAppData)
    $tessExe = Join-Path $env:LOCALAPPDATA "Tesseract-OCR\tesseract.exe"
    if (-not (Get-Command tesseract -ErrorAction SilentlyContinue) -and -not (Test-Path $tessExe)) { return $false }
    # Playwright Chromium downloaded
    & $venvPy -c "import os,sys; from playwright.sync_api import sync_playwright; p=sync_playwright().start(); ok=os.path.exists(p.chromium.executable_path); p.stop(); sys.exit(0 if ok else 1)" *> $null
    if ($LASTEXITCODE -ne 0) { return $false }
    # frontend deps
    if (-not (Test-Path (Join-Path $root "frontend\node_modules"))) { return $false }
    return $true
}

if (Test-Provisioned) {
    Write-Host "Dependencies present." -ForegroundColor DarkGray
} else {
    Write-Host "Installing/updating dependencies (first run can take a while)..." -ForegroundColor Cyan
    & (Join-Path $root "setup.ps1")
}

Write-Host "Launching SoundSplitter desktop app..." -ForegroundColor Cyan
Write-Host "(First run installs dependencies and builds the UI automatically; a setup window may appear.)" -ForegroundColor DarkGray
Push-Location (Join-Path $root "src-tauri")
cargo tauri dev
Pop-Location

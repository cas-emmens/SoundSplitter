<#
  Build the self-contained SoundSplitter installer (single offline .exe via Inno Setup).

  Stages a relocatable payload (CPU torch + Demucs + pre-downloaded htdemucs_6s weights,
  librosa/opencv/-, Playwright Chromium, Tesseract, ffmpeg, the prebuilt Angular UI), builds
  the Tauri shell exe, then packages everything with Inno Setup (handles >2GB, unlike NSIS).
  Optionally signs the installer (minisign) and emits latest.json for the in-app auto-updater.

  Run from the repo root:   .\build-installer.ps1            (CPU build, default)
                            .\build-installer.ps1 -Cuda      (NVIDIA/CUDA build)
  Switches:
    -Fresh   wipe the staged payload first (re-download Python + Chromium)
    -Cuda    build the NVIDIA variant (CUDA torch, payload-cuda, -cuda installer name)

  Prerequisites on THIS (build) machine:
    - Rust (cargo) + Node/npm, Tesseract + ffmpeg installed (setup.ps1 installs them).
    - Inno Setup 6 (winget: JRSoftware.InnoSetup).
    - For a release: updater signing key in $env:TAURI_SIGNING_PRIVATE_KEY (+ _PASSWORD).
      Without it the installer is still built but unsigned (fine for local testing; the
      auto-updater rejects unsigned updates). See RELEASING.md.
#>
param([switch]$Fresh, [switch]$Cuda)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

function Step($m) { Write-Host "`n=== $m ===" -ForegroundColor Cyan }
function Warn($m) { Write-Host "  ! $m" -ForegroundColor Yellow }
function Ok($m)   { Write-Host "  + $m" -ForegroundColor Green }
function Die($m)  { Write-Host "  x $m" -ForegroundColor Red; exit 1 }

# Build variant: CPU (default, runs anywhere) or CUDA (-Cuda, NVIDIA GPU, much faster).
# Each variant has its own staged payload + torch wheel + installer name + updater key.
$variant       = if ($Cuda) { "cuda" } else { "cpu" }
$variantSuffix = if ($Cuda) { "-cuda" } else { "" }
$payloadName   = if ($Cuda) { "payload-cuda" } else { "payload" }
$torchIndex    = if ($Cuda) { "https://download.pytorch.org/whl/cu124" } else { "https://download.pytorch.org/whl/cpu" }

$payload = Join-Path $root "src-tauri\$payloadName"
$runtime = Join-Path $payload "runtime"
$pyDir   = Join-Path $runtime "python"
$py      = Join-Path $pyDir "python.exe"

# Version: keep src-tauri/Cargo.toml and tauri.conf.json in sync; the running app compares
# against CARGO_PKG_VERSION, so read it from Cargo.toml.
$verLine = Select-String -Path (Join-Path $root "src-tauri\Cargo.toml") -Pattern '^\s*version\s*=\s*"([0-9.]+)"' | Select-Object -First 1
$version = $verLine.Matches[0].Groups[1].Value
if (-not $version) { Die "Could not read version from src-tauri\Cargo.toml" }
Ok "Building version $version"

if ($Fresh -and (Test-Path $payload)) { Step "Wiping staged payload (-Fresh)"; Remove-Item -Recurse -Force $payload }
New-Item -ItemType Directory -Force -Path $runtime | Out-Null

# --- 1. Relocatable Python (python-build-standalone, "install_only") ----------
Step "Provisioning relocatable Python 3.13"
if (Test-Path $py) {
    Ok "Reusing existing $pyDir (use -Fresh to rebuild)"
} else {
    $rel = Invoke-RestMethod "https://api.github.com/repos/astral-sh/python-build-standalone/releases/latest"
    $asset = $rel.assets | Where-Object {
        $_.name -match '^cpython-3\.13\.[0-9.]+\+[0-9]+-x86_64-pc-windows-msvc-install_only\.tar\.gz$'
    } | Select-Object -First 1
    if (-not $asset) { Die "Could not find a cpython-3.13 install_only windows asset." }
    $tgz = Join-Path $env:TEMP $asset.name
    Ok "Downloading $($asset.name)"
    Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $tgz -UseBasicParsing
    & tar -xzf $tgz -C $runtime
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path $py)) { Die "Python extraction failed." }
    Remove-Item $tgz -Force
    Ok "Python at $pyDir"
}
& $py -m pip install --upgrade pip --quiet
Ok "Python: $((& $py --version) 2>&1)"

# --- 2. Python dependencies (torch first, then the rest) ----------------------
Step "Installing Python dependencies ($variant torch + requirements + tab libs)"
& $py -m pip install torch torchaudio --index-url $torchIndex
if ($LASTEXITCODE -ne 0) { Die "PyTorch install failed." }
& $py -m pip install -r (Join-Path $root "backend\requirements.txt")
if ($LASTEXITCODE -ne 0) { Die "requirements.txt install failed." }
$canvas  = Join-Path $root "..\canvas-to-image"
$imgTabs = Join-Path $root "..\image-tabs"
if ((Test-Path $canvas) -and (Test-Path $imgTabs)) {
    & $py -m pip install $canvas $imgTabs
    if ($LASTEXITCODE -ne 0) { Die "image-tabs / canvas-to-image install failed." }
    Ok "Tab-generation libraries installed"
} else { Die "image-tabs / canvas-to-image not found next to sound-splitter." }

# --- 3. Playwright Chromium ---------------------------------------------------
Step "Installing Playwright Chromium into the bundle"
$env:PLAYWRIGHT_BROWSERS_PATH = Join-Path $runtime "ms-playwright"
& $py -m playwright install chromium
if ($LASTEXITCODE -ne 0) { Die "Playwright Chromium install failed." }
Ok "Chromium bundled"

# --- 4. Pre-download Demucs weights (offline separation) ----------------------
Step "Pre-downloading htdemucs_6s weights"
$env:TORCH_HOME = Join-Path $runtime "torch"
& $py -c "from demucs.pretrained import get_model; get_model('htdemucs_6s'); print('ok')"
if ($LASTEXITCODE -ne 0) { Die "Demucs weight pre-download failed." }
Ok "Weights cached under runtime\torch"

# --- 5. Tesseract + ffmpeg (copied from this machine) -------------------------
Step "Bundling Tesseract + ffmpeg"
$tessSrc = Join-Path $env:LOCALAPPDATA "Tesseract-OCR"
$tessDst = Join-Path $runtime "tesseract"
if (Test-Path $tessDst) { Remove-Item -Recurse -Force $tessDst }
if (Test-Path (Join-Path $tessSrc "tesseract.exe")) {
    Copy-Item -Recurse -Force $tessSrc $tessDst; Ok "Tesseract bundled"
} elseif (Get-Command tesseract -ErrorAction SilentlyContinue) {
    Copy-Item -Recurse -Force (Split-Path (Get-Command tesseract).Source -Parent) $tessDst; Ok "Tesseract bundled (PATH)"
} else { Die "Tesseract not found - run setup.ps1 once, or install UB-Mannheim Tesseract." }
$ffDst = Join-Path $runtime "ffmpeg\bin"
New-Item -ItemType Directory -Force -Path $ffDst | Out-Null
if (Get-Command ffmpeg -ErrorAction SilentlyContinue) {
    Copy-Item -Force (Get-Command ffmpeg).Source (Join-Path $ffDst "ffmpeg.exe"); Ok "ffmpeg bundled"
} else { Warn "ffmpeg not found - optional; only needed to import non-WAV/FLAC takes." }

# --- 6. Build + stage the Angular frontend ------------------------------------
Step "Building the Angular frontend"
Push-Location (Join-Path $root "frontend")
npm install; if ($LASTEXITCODE -ne 0) { Pop-Location; Die "npm install failed." }
npm run build; if ($LASTEXITCODE -ne 0) { Pop-Location; Die "npm run build failed." }
Pop-Location
$distSrc = Join-Path $root "frontend\dist\frontend\browser"
$distDst = Join-Path $payload "frontend-dist"
if (-not (Test-Path (Join-Path $distSrc "index.html"))) { Die "Built frontend not found at $distSrc" }
if (Test-Path $distDst) { Remove-Item -Recurse -Force $distDst }
Copy-Item -Recurse -Force $distSrc $distDst
Ok "Frontend staged"

# --- 7. Stage the backend (code only; no venv/data) ---------------------------
Step "Staging the backend"
$beDst = Join-Path $payload "backend"
if (Test-Path $beDst) { Remove-Item -Recurse -Force $beDst }
New-Item -ItemType Directory -Force -Path $beDst | Out-Null
Copy-Item -Recurse -Force (Join-Path $root "backend\app") (Join-Path $beDst "app")
Copy-Item -Force (Join-Path $root "backend\run.py") $beDst
Copy-Item -Force (Join-Path $root "backend\.env.example") $beDst
Get-ChildItem -Recurse -Directory -Filter "__pycache__" $beDst -ErrorAction SilentlyContinue | Remove-Item -Recurse -Force
Ok "Backend staged"

# Variant marker the shell reads at runtime to pick the matching auto-update installer.
Set-Content (Join-Path $payload "variant") $variant -NoNewline
Ok "Variant marker: $variant"

# --- 8. Assert the payload is complete (guards against a half-built bundle) ----
Step "Verifying payload completeness"
$required = @(
    "$runtime\python\python.exe",
    "$runtime\ms-playwright",
    "$runtime\torch",
    "$runtime\tesseract\tesseract.exe",
    "$payload\frontend-dist\index.html",
    "$beDst\run.py",
    "$beDst\app\main.py"
)
$missing = $required | Where-Object { -not (Test-Path $_) }
if ($missing) { $list = $missing -join [Environment]::NewLine; Die "Payload incomplete - missing:`n$list" }
Ok "Payload complete"

# --- 9. Build the Tauri shell exe ---------------------------------------------
Step "Building the Tauri shell (cargo build --release)"
Push-Location (Join-Path $root "src-tauri")
cargo build --release
$code = $LASTEXITCODE
Pop-Location
if ($code -ne 0) { Die "cargo build failed." }
Ok "Shell exe built"

# --- 10. Package with Inno Setup ----------------------------------------------
Step "Packaging the installer (Inno Setup)"
$iscc = @("$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
          "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
          "$env:ProgramFiles\Inno Setup 6\ISCC.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) { Die "Inno Setup not found. Install it: winget install JRSoftware.InnoSetup" }
& $iscc "/DAppVersion=$version" "/DPayloadDir=$payloadName" "/DVariantSuffix=$variantSuffix" (Join-Path $root "sound-splitter.iss")
if ($LASTEXITCODE -ne 0) { Die "Inno Setup compilation failed." }
$installer = Join-Path $root "dist\SoundSplitter-Setup-$version$variantSuffix.exe"
if (-not (Test-Path $installer)) { Die "Installer not produced at $installer" }
$mb = [math]::Round((Get-Item $installer).Length / 1MB, 1)
Ok "Installer: $installer ($mb MB)"

# --- 11. Sign + emit latest.json (release only) -------------------------------
if ($env:TAURI_SIGNING_PRIVATE_KEY) {
    Step "Signing the installer (minisign) + writing latest.json"
    Push-Location (Join-Path $root "src-tauri")
    cargo tauri signer sign "$installer"
    $code = $LASTEXITCODE
    Pop-Location
    if ($code -ne 0) { Die "Signing failed." }
    $sig = Get-Content "$installer.sig" -Raw
    $latestPath = Join-Path $root "dist\latest.json"
    # Upsert this variant's entry, preserving the other variant's (so one latest.json
    # carries both windows-x86_64 and windows-x86_64-cuda across the two build runs).
    $platforms = [ordered]@{}
    if (Test-Path $latestPath) {
        $prev = Get-Content $latestPath -Raw | ConvertFrom-Json
        if ($prev.version -eq $version) {
            foreach ($p in $prev.platforms.PSObject.Properties) {
                $platforms[$p.Name] = [ordered]@{ signature = $p.Value.signature; url = $p.Value.url }
            }
        }
    }
    $platforms["windows-x86_64$variantSuffix"] = [ordered]@{
        signature = $sig.Trim()
        url       = "https://github.com/cas-emmens/SoundSplitter/releases/download/v$version/SoundSplitter-Setup-$version$variantSuffix.exe"
    }
    $latest = [ordered]@{
        version   = $version
        notes     = "See the release notes."
        pub_date  = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
        platforms = $platforms
    }
    # Write WITHOUT a BOM: serde_json in the updater rejects a leading BOM.
    [IO.File]::WriteAllText($latestPath,
        ($latest | ConvertTo-Json -Depth 5), (New-Object System.Text.UTF8Encoding $false))
    Ok "Signed; dist\latest.json updated ($variant)"
} else {
    Warn "TAURI_SIGNING_PRIVATE_KEY not set - installer is UNSIGNED (fine for local testing; the auto-updater rejects unsigned updates). See RELEASING.md."
}

Step "Build complete"
Write-Host "  Installer: $installer ($mb MB)" -ForegroundColor White
Write-Host "  Next: see RELEASING.md to publish (upload the .exe + latest.json to a GitHub Release)." -ForegroundColor White

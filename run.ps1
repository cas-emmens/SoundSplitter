<#
  Launch sound-splitter: starts the backend and frontend in two windows and opens
  the app in your browser. Run from the repo root:   .\run.ps1
  Close either window (Ctrl+C) to stop that part.
#>
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path

$venvPy = "$root\backend\.venv\Scripts\python.exe"
if (-not (Test-Path $venvPy)) {
    Write-Host "Backend isn't set up yet. Run .\setup.ps1 first." -ForegroundColor Yellow
    exit 1
}

Write-Host "Starting backend (http://127.0.0.1:8000)..." -ForegroundColor Cyan
Start-Process powershell -ArgumentList @(
    "-NoExit", "-Command",
    "Set-Location '$root\backend'; & '$venvPy' run.py"
)

Write-Host "Starting frontend (http://localhost:4200)..." -ForegroundColor Cyan
Start-Process powershell -ArgumentList @(
    "-NoExit", "-Command",
    "Set-Location '$root\frontend'; npm start"
)

# Give the dev server a moment, then open the app.
Start-Sleep -Seconds 6
Start-Process "http://localhost:4200"
Write-Host "`nOpened http://localhost:4200 - first compile may take a few seconds." -ForegroundColor Green

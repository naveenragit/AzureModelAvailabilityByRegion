# Run the Model Availability Dashboard locally.
# Usage:
#   pwsh -File run.ps1            # uses existing .venv if present
#   pwsh -File run.ps1 -Recreate  # rebuild .venv

param(
  [int]$Port = 8765,
  [switch]$Recreate,
  [string]$PyVersion = "3.11"
)

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

$venv = Join-Path $PSScriptRoot ".venv"
if ($Recreate -and (Test-Path $venv)) { Remove-Item -Recurse -Force $venv }

if (-not (Test-Path $venv)) {
  Write-Host "Creating virtualenv at $venv (Python $PyVersion)" -ForegroundColor Cyan
  # Use the Windows py launcher to pin Python version (3.11 has prebuilt wheels for win_arm64).
  $launcher = Get-Command py -ErrorAction SilentlyContinue
  if ($launcher) {
    & py -$PyVersion -m venv $venv
  } else {
    Write-Warning "The 'py' launcher was not found; falling back to 'python'. Install Python $PyVersion if dependency builds fail."
    python -m venv $venv
  }
}

$py = Join-Path $venv "Scripts\python.exe"
& $py -m pip install --upgrade pip *> $null
& $py -m pip install -r backend/requirements.txt
if ($LASTEXITCODE -ne 0) {
  Write-Error "pip install failed (exit code $LASTEXITCODE). Re-run with -Recreate after fixing, or pass -PyVersion 3.11."
  exit $LASTEXITCODE
}

Write-Host ""
Write-Host "Make sure you've run 'az login' so the backend can fetch an ARM token." -ForegroundColor Yellow
Write-Host "Starting on http://localhost:$Port" -ForegroundColor Green

Start-Process "http://localhost:$Port"
& $py -m uvicorn backend.main:app --host 127.0.0.1 --port $Port

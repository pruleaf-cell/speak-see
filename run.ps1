# Speak -> See (Windows)
# Requires: PowerShell 7+, Python 3.11+ in PATH, or install uv and let it manage Python.

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

$env:HF_HUB_DISABLE_TELEMETRY = "1"
$env:HF_HUB_DISABLE_PROGRESS_BARS = "1"
$env:HF_HOME = Join-Path $ScriptDir "data\\hf"
$env:PYTHONUNBUFFERED = "1"
$env:PYTHONPATH = Join-Path $ScriptDir "src"

function Ensure-Uv {
  if (Get-Command uv -ErrorAction SilentlyContinue) { return }
  Write-Host "[Speak->See] uv not found. Install uv from https://astral.sh/uv/ and re-run."
  exit 1
}

Ensure-Uv

if (-not (Test-Path ".venv")) {
  Write-Host "[Speak->See] Creating virtualenv..."
  uv venv --python 3.11 .venv
}

Write-Host "[Speak->See] Syncing dependencies..."
try { uv sync --frozen } catch { uv sync }

& .venv\\Scripts\\python.exe -m speaksee.server


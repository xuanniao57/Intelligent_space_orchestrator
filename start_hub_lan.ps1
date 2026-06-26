param(
  [int]$Port = 8798,
  [string]$HostAddress = "0.0.0.0"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

$EnvFile = Join-Path $Root ".env"
if (-not (Test-Path -LiteralPath $EnvFile)) {
  Copy-Item -LiteralPath (Join-Path $Root ".env.example") -Destination $EnvFile
  Write-Host "Created .env from .env.example. Fill model API keys before live LLM tests." -ForegroundColor Yellow
}

$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"
if (!(Test-Path -LiteralPath $VenvPython)) {
  & ".\scripts\setup.ps1"
}

$env:URBAN_AGENTS_ROOT = Join-Path $Root "third_party\UrbanAgents"
& $VenvPython ".\central_hub\backend\server.py" --host $HostAddress --port $Port

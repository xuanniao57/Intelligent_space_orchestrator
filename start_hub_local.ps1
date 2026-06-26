param(
  [int]$Port = 8798,
  [string]$HostName = "127.0.0.1"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

if (!(Test-Path -LiteralPath ".\.env")) {
  Copy-Item -LiteralPath ".\.env.example" -Destination ".\.env"
  Write-Host "Created .env from .env.example. Fill model/API keys before using live LLM calls." -ForegroundColor Yellow
}

$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"
if (!(Test-Path -LiteralPath $VenvPython)) {
  & ".\scripts\setup.ps1"
}

if (!(Test-Path -LiteralPath $VenvPython)) {
  throw "Virtual environment was not created. Run scripts\setup.ps1 first."
}

& $VenvPython -c "import flask, openai" 2>$null
if ($LASTEXITCODE -ne 0) {
  Write-Host "Dependencies are missing in .venv; running setup ..." -ForegroundColor Yellow
  & ".\scripts\setup.ps1"
}

$env:URBAN_AGENTS_ROOT = Join-Path $Root "third_party\UrbanAgents"
Write-Host "Starting hub at http://$HostName`:$Port/agent-console" -ForegroundColor Cyan
& $VenvPython ".\central_hub\backend\server.py" --host $HostName --port $Port

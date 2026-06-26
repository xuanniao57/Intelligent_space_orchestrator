param(
  [int]$Port = 8731,
  [string]$HubUrl = "http://127.0.0.1:8798",
  [double]$StepDelay = 0.08
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $ProjectRoot

$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $Python)) {
  & ".\scripts\setup.ps1"
}

$Script = Join-Path $ProjectRoot "tools\fake_g1\fake_g1_push_server.py"
if (-not (Test-Path -LiteralPath $Script)) {
  throw "Fake G1 server not found: $Script"
}

Write-Host "Starting fake G1 at http://127.0.0.1:$Port, hub=$HubUrl" -ForegroundColor Cyan
& $Python $Script --host "127.0.0.1" --port $Port --hub-url $HubUrl --step-delay $StepDelay

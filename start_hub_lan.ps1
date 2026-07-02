param(
  [int]$Port = 8798,
  [int]$BackendPort = 8799,
  [string]$HostAddress = "0.0.0.0",
  [string]$BackendHost = "127.0.0.1"
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
$LogDir = Join-Path $Root "_runtime_logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

Write-Host "Starting Tongyu backend on ${BackendHost}:${BackendPort} ..." -ForegroundColor Cyan
$Backend = Start-Process -FilePath $VenvPython `
  -ArgumentList @((Join-Path $Root "central_hub\backend\server.py"), "--host", $BackendHost, "--port", $BackendPort) `
  -WorkingDirectory $Root `
  -RedirectStandardOutput (Join-Path $LogDir "central_hub_${BackendPort}.out.log") `
  -RedirectStandardError (Join-Path $LogDir "central_hub_${BackendPort}.err.log") `
  -PassThru `
  -WindowStyle Hidden

Start-Sleep -Seconds 2

Write-Host "Starting Tongyu mux on ${HostAddress}:${Port} -> ${BackendHost}:${BackendPort}; plug -> 127.0.0.1:8080 ..." -ForegroundColor Cyan
try {
  & $VenvPython ".\central_hub\backend\tcp_port_mux.py" `
    --listen-host $HostAddress `
    --listen-port $Port `
    --http-target-host $BackendHost `
    --http-target-port $BackendPort `
    --plug-target-host 127.0.0.1 `
    --plug-target-port 8080 `
    --plug-peer-ips 192.168.1.156
}
finally {
  if ($Backend -and -not $Backend.HasExited) {
    Stop-Process -Id $Backend.Id -Force -ErrorAction SilentlyContinue
  }
}

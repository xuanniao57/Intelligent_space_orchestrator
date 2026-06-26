param(
  [int]$ExternalPort = 8798,
  [int]$HubInternalPort = 8799,
  [string]$HostAddress = "0.0.0.0",
  [string]$SmartPlugIp = "192.168.1.156",
  [int]$SmartPlugInternalPort = 8080
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$LogDir = Join-Path $Root "logs"
$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
Set-Location $Root

if (!(Test-Path -LiteralPath ".\.env")) {
  Copy-Item -LiteralPath ".\.env.example" -Destination ".\.env"
  Write-Host "Created .env from .env.example. Fill model/API keys before live LLM tests." -ForegroundColor Yellow
}

if (!(Test-Path -LiteralPath $VenvPython)) {
  & ".\scripts\setup.ps1"
}

function Test-LocalPortFree {
  param([int]$Port)
  $Conn = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
  return $null -eq $Conn
}

if (!(Test-LocalPortFree -Port $ExternalPort)) {
  throw "Port $ExternalPort is already occupied. Stop the old hub before starting the 8798 multiplexer."
}

if (!(Test-LocalPortFree -Port $HubInternalPort)) {
  throw "Port $HubInternalPort is already occupied. Choose another -HubInternalPort."
}

$env:URBAN_AGENTS_ROOT = Join-Path $Root "third_party\UrbanAgents"

$HubOut = Join-Path $LogDir "hub_$HubInternalPort.out.log"
$HubErr = Join-Path $LogDir "hub_$HubInternalPort.err.log"
$MuxOut = Join-Path $LogDir "mux_$ExternalPort.out.log"
$MuxErr = Join-Path $LogDir "mux_$ExternalPort.err.log"

Write-Host "Starting internal hub at http://127.0.0.1:$HubInternalPort" -ForegroundColor Cyan
$HubProcess = Start-Process `
  -FilePath $VenvPython `
  -ArgumentList @(".\central_hub\backend\server.py", "--host", "127.0.0.1", "--port", "$HubInternalPort") `
  -WorkingDirectory $Root `
  -WindowStyle Hidden `
  -RedirectStandardOutput $HubOut `
  -RedirectStandardError $HubErr `
  -PassThru

$Ready = $false
for ($i = 0; $i -lt 18; $i++) {
  Start-Sleep -Milliseconds 700
  try {
    $Health = Invoke-RestMethod -Uri "http://127.0.0.1:$HubInternalPort/api/health" -TimeoutSec 2
    if ($Health.status -eq "ok") {
      $Ready = $true
      break
    }
  } catch {
  }
}

if (!$Ready) {
  Stop-Process -Id $HubProcess.Id -Force -ErrorAction SilentlyContinue
  throw "Internal hub did not become healthy. Check $HubErr"
}

Write-Host "Starting 8798 multiplexer: HTTP -> $HubInternalPort, smart plug $SmartPlugIp -> $SmartPlugInternalPort" -ForegroundColor Cyan
Write-Host "Open http://192.168.1.50:$ExternalPort/agent-console" -ForegroundColor Green

& $VenvPython ".\central_hub\backend\tcp_port_mux.py" `
  --listen-host $HostAddress `
  --listen-port $ExternalPort `
  --http-target-host 127.0.0.1 `
  --http-target-port $HubInternalPort `
  --plug-target-host 127.0.0.1 `
  --plug-target-port $SmartPlugInternalPort `
  --plug-peer-ips $SmartPlugIp 1>> $MuxOut 2>> $MuxErr

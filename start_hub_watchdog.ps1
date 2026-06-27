param(
  [int]$Port = 8798,
  [string]$HostAddress = "0.0.0.0",
  [int]$HealthIntervalSeconds = 20,
  [switch]$ClassicHub
)

$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$LogDir = Join-Path $Root "logs"
$OutLog = Join-Path $LogDir "hub_$Port.out.log"
$ErrLog = Join-Path $LogDir "hub_$Port.err.log"
$WatchdogLog = Join-Path $LogDir "hub_watchdog.log"
$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"
$MuxScript = Join-Path $Root "start_hub_lan_mux.ps1"

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
Set-Location $Root

function Write-WatchdogLog {
  param([string]$Message)
  $Timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
  Add-Content -LiteralPath $WatchdogLog -Value "[$Timestamp] $Message" -Encoding UTF8
}

function Ensure-EnvFile {
  if (!(Test-Path -LiteralPath ".\.env")) {
    Copy-Item -LiteralPath ".\.env.example" -Destination ".\.env"
    Write-WatchdogLog "Created .env from .env.example."
  }
}

function Ensure-Venv {
  if (Test-Path -LiteralPath $VenvPython) {
    return
  }
  $PythonCmd = Get-Command python -ErrorAction SilentlyContinue
  if ($null -eq $PythonCmd) {
    throw "Python was not found and .venv does not exist."
  }
  Write-WatchdogLog "Creating .venv with $($PythonCmd.Source)."
  & ".\scripts\setup.ps1"
}

function Test-HubHealth {
  try {
    $Health = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/health" -TimeoutSec 3
    return $Health.status -eq "ok"
  } catch {
    return $false
  }
}

Ensure-EnvFile
Ensure-Venv
$env:URBAN_AGENTS_ROOT = Join-Path $Root "third_party\UrbanAgents"
$ModeLabel = if ($ClassicHub) { "classic" } else { "mux" }
Write-WatchdogLog "Watchdog started for $HostAddress`:$Port mode=$ModeLabel."

while ($true) {
  if (Test-HubHealth) {
    Start-Sleep -Seconds $HealthIntervalSeconds
    continue
  }

  if ($ClassicHub) {
    Write-WatchdogLog "Hub health check failed; starting classic server."
    $Process = Start-Process `
      -FilePath $VenvPython `
      -ArgumentList @(".\central_hub\backend\server.py", "--host", $HostAddress, "--port", "$Port") `
      -WorkingDirectory $Root `
      -WindowStyle Hidden `
      -RedirectStandardOutput $OutLog `
      -RedirectStandardError $ErrLog `
      -PassThru
  } else {
    Write-WatchdogLog "Hub health check failed; starting mux mode."
    $Process = Start-Process `
      -FilePath "powershell.exe" `
      -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $MuxScript, "-ExternalPort", "$Port", "-HostAddress", $HostAddress) `
      -WorkingDirectory $Root `
      -WindowStyle Hidden `
      -PassThru
  }

  Write-WatchdogLog "Started hub process PID=$($Process.Id) mode=$ModeLabel."
  Wait-Process -Id $Process.Id
  Write-WatchdogLog "Hub process PID=$($Process.Id) exited; restarting after 5 seconds."
  Start-Sleep -Seconds 5
}

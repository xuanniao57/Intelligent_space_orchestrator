param(
  [int]$HubPort = 8798,
  [int]$RobotPort = 8731,
  [string]$OutputDir = "",
  [switch]$UseLiveLLM,
  [switch]$NoRobotPush,
  [switch]$ResetMemory
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$HubUrl = "http://127.0.0.1:$HubPort"
$RobotUrl = "http://127.0.0.1:$RobotPort"
$LogsDir = Join-Path $ProjectRoot "logs"
if (-not $OutputDir) {
  $OutputDir = Join-Path $ProjectRoot "outputs\zhichang_agent_cycle_demo"
}
New-Item -ItemType Directory -Force -Path $LogsDir | Out-Null
New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null

$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $Python)) {
  $Python = "python"
}

$FakeG1Script = Join-Path $ProjectRoot "tools\fake_g1\fake_g1_push_server.py"
$CycleScript = Join-Path $ProjectRoot "scripts\run_zhichang_tongyu_agent_cycle.py"
$HubLog = Join-Path $LogsDir "zhichang_agent_hub_$HubPort.log"
$HubErrLog = Join-Path $LogsDir "zhichang_agent_hub_$HubPort.err.log"
$FakeG1Log = Join-Path $LogsDir "zhichang_agent_fake_g1_$RobotPort.log"
$FakeG1ErrLog = Join-Path $LogsDir "zhichang_agent_fake_g1_$RobotPort.err.log"
$MemoryPath = Join-Path $ProjectRoot "central_hub\data\zhichang_tongyu_agent_memory.jsonl"

if ($ResetMemory -and (Test-Path -LiteralPath $MemoryPath)) {
  Remove-Item -LiteralPath $MemoryPath -Force
}

function Wait-HttpOk {
  param(
    [string]$Url,
    [int]$TimeoutSec = 20
  )
  $deadline = (Get-Date).AddSeconds($TimeoutSec)
  while ((Get-Date) -lt $deadline) {
    try {
      Invoke-RestMethod -Uri $Url -TimeoutSec 2 | Out-Null
      return
    } catch {
      Start-Sleep -Milliseconds 300
    }
  }
  throw "Timed out waiting for $Url"
}

$oldDisable = $env:TONGYU_AGENT_DISABLE_LLM
if ($UseLiveLLM) {
  Remove-Item Env:\TONGYU_AGENT_DISABLE_LLM -ErrorAction SilentlyContinue
} else {
  $env:TONGYU_AGENT_DISABLE_LLM = "1"
}

$hubProcess = $null
$g1Process = $null
try {
  $hubProcess = Start-Process `
    -FilePath $Python `
    -ArgumentList @("central_hub\backend\server.py", "--host", "127.0.0.1", "--port", "$HubPort") `
    -WorkingDirectory $ProjectRoot `
    -RedirectStandardOutput $HubLog `
    -RedirectStandardError $HubErrLog `
    -WindowStyle Hidden `
    -PassThru

  Wait-HttpOk "$HubUrl/api/health" 25

  if (-not $NoRobotPush) {
    $g1Process = Start-Process `
      -FilePath $Python `
      -ArgumentList @($FakeG1Script, "--host", "127.0.0.1", "--port", "$RobotPort", "--hub-url", $HubUrl, "--step-delay", "0.08") `
      -WorkingDirectory $ProjectRoot `
      -RedirectStandardOutput $FakeG1Log `
      -RedirectStandardError $FakeG1ErrLog `
      -WindowStyle Hidden `
      -PassThru
    Wait-HttpOk "$RobotUrl/health" 20
  }

  $cycleArgs = @(
    $CycleScript,
    "--hub-url", $HubUrl,
    "--robot-url", $RobotUrl,
    "--output-dir", $OutputDir
  )
  if ($UseLiveLLM) {
    $cycleArgs += @("--request-timeout", "120")
  }
  if ($NoRobotPush) {
    $cycleArgs += "--no-robot-push"
  }
  & $Python @cycleArgs
} finally {
  if ($g1Process -and -not $g1Process.HasExited) {
    Stop-Process -Id $g1Process.Id -Force
  }
  if ($hubProcess -and -not $hubProcess.HasExited) {
    Stop-Process -Id $hubProcess.Id -Force
  }
  if ($null -eq $oldDisable) {
    Remove-Item Env:\TONGYU_AGENT_DISABLE_LLM -ErrorAction SilentlyContinue
  } else {
    $env:TONGYU_AGENT_DISABLE_LLM = $oldDisable
  }
}

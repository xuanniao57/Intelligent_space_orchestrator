param(
  [string]$Python = "python",
  [switch]$SkipUrbanAgents
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $ProjectRoot

Write-Host "== 智场同语中枢 Agent 安装 ==" -ForegroundColor Cyan
Write-Host "Project: $ProjectRoot"

if (-not (Test-Path -LiteralPath ".\.env")) {
  Copy-Item -LiteralPath ".\.env.example" -Destination ".\.env"
  Write-Host "已从 .env.example 创建 .env。请填写 DeepSeek/Kimi API Key。" -ForegroundColor Yellow
}

$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $VenvPython)) {
  Write-Host "创建 Python 虚拟环境 .venv ..."
  & $Python -m venv ".\.venv"
}

& $VenvPython -m pip install --upgrade pip setuptools wheel

if (-not $SkipUrbanAgents) {
  $UrbanAgentsRoot = Join-Path $ProjectRoot "third_party\UrbanAgents"
  if (-not (Test-Path -LiteralPath (Join-Path $UrbanAgentsRoot "pyproject.toml"))) {
    throw "缺少 third_party\UrbanAgents。请确认仓库完整 clone。"
  }
  Write-Host "安装 UrbanAgents / Urban-Hermes runtime ..."
  & $VenvPython -m pip install -e $UrbanAgentsRoot --no-build-isolation
}

Write-Host "安装中枢后端依赖 ..."
& $VenvPython -m pip install -r ".\central_hub\backend\requirements.txt"

Write-Host ""
Write-Host "安装完成。" -ForegroundColor Green
Write-Host "下一步："
Write-Host "1. 编辑 .env，填写 DEEPSEEK_API_KEY 或 KIMI_CODE_API_KEY"
Write-Host "2. 运行：powershell -ExecutionPolicy Bypass -File .\start_hub_local.ps1 -Port 8798"

param(
    [string]$InstallDir = $(if ($env:URBAN_AGENT_INSTALL_DIR) { $env:URBAN_AGENT_INSTALL_DIR } else { Join-Path (Get-Location) "urban-agent" }),
    [string]$UrbanHome = $(if ($env:URBAN_AGENT_HOME) { $env:URBAN_AGENT_HOME } else { Join-Path (Get-Location) ".urban-agent" }),
    [string]$Branch = "main",
    [string]$Repo = $(if ($env:URBAN_AGENT_REPO_URL) { $env:URBAN_AGENT_REPO_URL } else { "https://github.com/xuanniao57/UrbanAgents.git" }),
    [switch]$NoVenv,
    [switch]$SkipSetup
)

$ErrorActionPreference = "Stop"

function Write-Info([string]$Message) { Write-Host "-> $Message" -ForegroundColor Cyan }
function Write-Ok([string]$Message) { Write-Host "OK $Message" -ForegroundColor Green }
function Write-Warn([string]$Message) { Write-Host "WARN $Message" -ForegroundColor Yellow }

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    throw "git is required to install UrbanAgent."
}

$PythonCmd = if ($env:PYTHON) { $env:PYTHON } elseif (Get-Command py -ErrorAction SilentlyContinue) { "py -3" } else { "python" }

New-Item -ItemType Directory -Force -Path $UrbanHome | Out-Null
New-Item -ItemType Directory -Force -Path (Split-Path $InstallDir) | Out-Null

if (Test-Path (Join-Path $InstallDir ".git")) {
    Write-Info "Updating UrbanAgent at $InstallDir"
    git -C $InstallDir fetch --all --prune
    git -C $InstallDir checkout $Branch
    git -C $InstallDir pull --ff-only
} else {
    Write-Info "Cloning UrbanAgent into $InstallDir"
    if (Test-Path $InstallDir) { Remove-Item -Recurse -Force $InstallDir }
    git clone --branch $Branch $Repo $InstallDir
}

Push-Location $InstallDir
try {
    if (-not $NoVenv) {
        if (Get-Command uv -ErrorAction SilentlyContinue) {
            uv venv .venv --python 3.10
            $PythonExe = Join-Path $InstallDir ".venv\Scripts\python.exe"
            uv pip install --python $PythonExe -e $InstallDir
        } else {
            Invoke-Expression "$PythonCmd -m venv .venv"
            $PythonExe = Join-Path $InstallDir ".venv\Scripts\python.exe"
            & $PythonExe -m pip install --upgrade pip
            & $PythonExe -m pip install -e $InstallDir
        }
    } else {
        $PythonExe = $PythonCmd
        Invoke-Expression "$PythonCmd -m pip install -e `"$InstallDir`""
    }
} finally {
    Pop-Location
}

$BinDir = Join-Path $UrbanHome "bin"
New-Item -ItemType Directory -Force -Path $BinDir | Out-Null
$Launcher = Join-Path $BinDir "urban-agent.cmd"
@"
@echo off
set URBAN_AGENT_HOME=$UrbanHome
set URBAN_AGENT_INSTALL_DIR=$InstallDir
"$PythonExe" -m urban_agent %*
"@ | Set-Content -Encoding ASCII $Launcher

$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
if (-not ($userPath -split ";" | Where-Object { $_ -eq $BinDir })) {
    [Environment]::SetEnvironmentVariable("Path", ($userPath.TrimEnd(";") + ";" + $BinDir), "User")
    Write-Warn "Added $BinDir to the user PATH. Open a new terminal to use urban-agent."
}

$env:URBAN_AGENT_HOME = $UrbanHome
$env:URBAN_AGENT_INSTALL_DIR = $InstallDir
& $PythonExe -m urban_agent init

if (-not $SkipSetup) {
    & $PythonExe -m urban_agent setup
}

Write-Ok "UrbanAgent installed"
Write-Host "  Code:      $InstallDir"
Write-Host "  User data: $UrbanHome"
Write-Host "  Command:   $Launcher"

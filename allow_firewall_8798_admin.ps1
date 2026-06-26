$ErrorActionPreference = "Stop"
$RuleName = "Tongyu Central Hub 8798"

$Principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $Principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
  throw "Please run this script from an Administrator PowerShell."
}

$ExistingRule = Get-NetFirewallRule -DisplayName $RuleName -ErrorAction SilentlyContinue
if ($ExistingRule) {
  Write-Host "Firewall rule already exists: $RuleName"
  return
}

New-NetFirewallRule `
  -DisplayName $RuleName `
  -Direction Inbound `
  -Action Allow `
  -Protocol TCP `
  -LocalPort 8798 `
  -Profile Any | Out-Null

Write-Host "Created firewall inbound rule: $RuleName"

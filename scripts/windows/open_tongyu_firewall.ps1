#Requires -RunAsAdministrator
<#
Open the minimum Windows Firewall rules needed by the Tongyu central host.

Run in an elevated PowerShell:
  powershell -ExecutionPolicy Bypass -File .\scripts\windows\open_tongyu_firewall.ps1
#>

param(
    [int[]]$HubPorts = @(8798),
    [int[]]$HardwarePorts = @(22001, 8080),
    [int[]]$VisionUdpPorts = @(5005),
    [string]$RemoteAddress = "192.168.0.0/16",
    [switch]$PauseAtEnd
)

$ErrorActionPreference = "Stop"

Write-Host "Removing old Tongyu firewall rules..." -ForegroundColor Yellow
Get-NetFirewallRule -DisplayName "Tongyu*" -ErrorAction SilentlyContinue |
    Remove-NetFirewallRule -ErrorAction SilentlyContinue

function New-TongyuPortRule {
    param(
        [string]$DisplayName,
        [int]$Port,
        [ValidateSet("TCP", "UDP")]
        [string]$Protocol = "TCP"
    )
    New-NetFirewallRule `
        -DisplayName $DisplayName `
        -Direction Inbound `
        -Action Allow `
        -Protocol $Protocol `
        -LocalPort $Port `
        -RemoteAddress $RemoteAddress `
        -Profile Any | Out-Null
    Write-Host "Created ${Protocol} rule: $DisplayName / port $Port / remote $RemoteAddress" -ForegroundColor Cyan
}

function New-TongyuIcmpRule {
    $displayName = "Tongyu Central Hub ICMPv4 Echo"
    New-NetFirewallRule `
        -DisplayName $displayName `
        -Direction Inbound `
        -Action Allow `
        -Protocol ICMPv4 `
        -IcmpType 8 `
        -RemoteAddress $RemoteAddress `
        -Profile Any | Out-Null
    Write-Host "Created ICMP rule: $displayName / remote $RemoteAddress" -ForegroundColor Cyan
}

New-TongyuIcmpRule
foreach ($port in $HubPorts) {
    New-TongyuPortRule -DisplayName "Tongyu Central Hub TCP $port" -Port $port
}
foreach ($port in $HardwarePorts) {
    New-TongyuPortRule -DisplayName "Tongyu Hardware Gateway TCP $port" -Port $port
}
foreach ($port in $VisionUdpPorts) {
    New-TongyuPortRule -DisplayName "Tongyu Vision Stream UDP $port" -Port $port -Protocol UDP
}

Write-Host ""
Write-Host "Tongyu firewall rules are enabled for $RemoteAddress on all profiles." -ForegroundColor Green
Get-NetFirewallRule -DisplayName "Tongyu*" |
    Select-Object DisplayName, Enabled, Direction, Action, Profile |
    Format-Table -AutoSize
Get-NetFirewallRule -DisplayName "Tongyu*" |
    Get-NetFirewallAddressFilter |
    Select-Object InstanceID, RemoteAddress |
    Format-Table -AutoSize
Get-NetFirewallRule -DisplayName "Tongyu*" |
    Get-NetFirewallPortFilter |
    Select-Object InstanceID, Protocol, LocalPort, IcmpType |
    Format-Table -AutoSize

Write-Host ""
Write-Host "Local listener check:" -ForegroundColor Yellow
Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
    Where-Object { $_.LocalPort -in @($HubPorts + $HardwarePorts) } |
    Select-Object LocalAddress, LocalPort, OwningProcess |
    Format-Table -AutoSize
Get-NetUDPEndpoint -ErrorAction SilentlyContinue |
    Where-Object { $_.LocalPort -in @($VisionUdpPorts) } |
    Select-Object LocalAddress, LocalPort, OwningProcess |
    Format-Table -AutoSize

if ($PauseAtEnd) {
    Write-Host ""
    Read-Host "Press Enter to close"
}

param(
    [string]$HubIp = "192.168.1.50",
    [int[]]$Ports = @(8798, 22001, 8080)
)

$ErrorActionPreference = "Continue"

Write-Host "=== Tongyu network profiles ===" -ForegroundColor Yellow
Get-NetConnectionProfile |
    Select-Object InterfaceAlias, InterfaceIndex, NetworkCategory, IPv4Connectivity |
    Format-Table -AutoSize

Write-Host ""
Write-Host "=== Local IPv4 addresses ===" -ForegroundColor Yellow
Get-NetIPConfiguration |
    Where-Object { $_.IPv4Address } |
    Select-Object InterfaceAlias, InterfaceIndex,
        @{n="IPv4";e={$_.IPv4Address.IPAddress -join ", "}},
        @{n="Gateway";e={$_.IPv4DefaultGateway.NextHop -join ", "}} |
    Format-Table -AutoSize

Write-Host ""
Write-Host "=== Listening ports ===" -ForegroundColor Yellow
Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
    Where-Object { $_.LocalPort -in $Ports -or $_.LocalPort -eq 8799 } |
    Select-Object LocalAddress, LocalPort, OwningProcess |
    Format-Table -AutoSize

Write-Host ""
Write-Host "=== Tongyu firewall rules ===" -ForegroundColor Yellow
$rules = Get-NetFirewallRule -DisplayName "Tongyu*" -ErrorAction SilentlyContinue
if ($rules) {
    $rules | Select-Object DisplayName, Enabled, Direction, Action, Profile | Format-Table -AutoSize
    $rules | Get-NetFirewallAddressFilter | Select-Object InstanceID, RemoteAddress | Format-Table -AutoSize
    $rules | Get-NetFirewallPortFilter | Select-Object InstanceID, Protocol, LocalPort, IcmpType | Format-Table -AutoSize
} else {
    Write-Host "No Tongyu firewall rules found." -ForegroundColor Red
}

Write-Host ""
Write-Host "=== Local self check ===" -ForegroundColor Yellow
foreach ($port in $Ports) {
    Test-NetConnection $HubIp -Port $port |
        Select-Object ComputerName, RemoteAddress, RemotePort, TcpTestSucceeded |
        Format-List
}

Write-Host ""
Write-Host "=== HTTP health ===" -ForegroundColor Yellow
try {
    Invoke-RestMethod "http://$HubIp`:8798/api/health" -TimeoutSec 5 | ConvertTo-Json -Depth 3
} catch {
    Write-Host $_.Exception.Message -ForegroundColor Red
}

Write-Host ""
Write-Host "Ask another computer on the same network to run:" -ForegroundColor Green
Write-Host "  ping $HubIp"
Write-Host "  curl http://$HubIp`:8798/api/health"
Write-Host "  python -c ""import urllib.request; print(urllib.request.urlopen('http://$HubIp`:8798/api/health', timeout=5).read().decode())"""
Write-Host ""
Read-Host "Press Enter to close"

param(
  [string]$HubUrl = "http://127.0.0.1:8798",
  [string]$RobotUrl = "http://127.0.0.1:8731",
  [switch]$NoRobotPush
)

$ErrorActionPreference = "Stop"
$HubUrl = $HubUrl.TrimEnd("/")
$RobotUrl = $RobotUrl.TrimEnd("/")

function Invoke-Scenario {
  param(
    [string]$ScenarioId,
    [hashtable]$Body
  )

  $json = $Body | ConvertTo-Json -Depth 30
  Invoke-RestMethod `
    -Uri "$HubUrl/api/demo/scenario/$ScenarioId" `
    -Method Post `
    -ContentType "application/json; charset=utf-8" `
    -Body $json
}

$health = Invoke-RestMethod "$HubUrl/api/health"
Write-Host "Hub: $($health.status) service=$($health.service)"

$heatBody = @{}
if (-not $NoRobotPush) {
  $heatBody.robot_url = $RobotUrl
}

$heat = Invoke-Scenario -ScenarioId "heat_cooling_loop" -Body $heatBody
$music = Invoke-Scenario -ScenarioId "music_cocktail_loop" -Body @{}

[PSCustomObject]@{
  heat_scenario = $heat.scenario.id
  heat_commands = $heat.result.command_count
  heat_dispatch = ($heat.result.dispatch_results | Where-Object { $_.status -ne "skipped" } | Select-Object -First 1).status
  music_scenario = $music.scenario.id
  music_commands = $music.result.command_count
  latest_agent_run = $music.result.agent_run.run_id
  command_history_url = "$HubUrl/api/commands/history?limit=10"
  robot_ack_url = "$HubUrl/api/robot/ack/history?limit=10"
} | Format-List

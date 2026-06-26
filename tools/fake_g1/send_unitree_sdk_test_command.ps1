param(
  [string]$HubUrl = "http://127.0.0.1:8798",
  [string]$RobotUrl = "http://127.0.0.1:8731",
  [string]$RequestText = "Lab dry-run: LLM hub sends Unitree-SDK-style command sequence.",
  [switch]$HubOnly
)

$ErrorActionPreference = "Stop"
$HubUrl = $HubUrl.TrimEnd("/")
$RobotUrl = $RobotUrl.TrimEnd("/")
$MessageId = "cmd_unitree_sdk_{0}" -f ([DateTimeOffset]::Now.ToUnixTimeMilliseconds())
$TaskId = "g1_sdk_dryrun_{0}" -f ([DateTimeOffset]::Now.ToUnixTimeMilliseconds())

$CommandEnvelope = @{
  message_type = "device_command"
  message_id = $MessageId
  target_id = "unitree_g1"
  target_type = "robot"
  ack_required = $true
  routing = @{
    direct_http = "$RobotUrl/api/g1/execute"
    ros2_topic = "/talking_spaces/g1/sdk_sequence"
    mqtt_topic = "talking_spaces/unitree_g1/sdk_sequence"
  }
  command = @{
    type = "g1.unitree_sdk_sequence"
    params = @{
      task_id = $TaskId
      scene_id = "cooling_handoff_network_dryrun"
      request_text = $RequestText
      speech_cn = "Hub task received. I will run a safe dry-run action sequence."
      safety = @{
        dry_run = $true
        speed_limit_mps = 0.25
        min_human_distance_m = 0.8
        require_debug_mode = $true
        allow_hot_liquid_contact = $false
      }
      sdk_sequence = @(
        @{
          seq = 1
          primitive = "unitree_sdk_call"
          source_primitive = "safety_check"
          layer = "bridge"
          client = "SafetyGuard"
          method = "CheckPreconditions"
          args = @{
            require_debug_mode = $true
            min_human_distance_m = 0.8
            dry_run = $true
          }
          note = "Real bridge checks G1 debug mode, emergency stop, and human distance first."
        },
        @{
          seq = 2
          primitive = "unitree_sdk_call"
          source_primitive = "speak"
          layer = "onboard_io"
          client = "AudioClient"
          method = "TtsMaker"
          args = @{
            text_cn = "Hub task received. I will run a safe dry-run action sequence."
            speaker_id = 0
          }
          note = "Official G1 SDK2 audio path maps to unitree::robot::g1::AudioClient.TtsMaker."
        },
        @{
          seq = 3
          primitive = "unitree_sdk_call"
          source_primitive = "move_probe"
          layer = "unitree_high_level"
          client = "LocoClient"
          method = "SetVelocity"
          args = @{
            vx = 0.0
            vy = 0.0
            omega = 0.0
            duration = 1.0
            dry_run_only = $true
          }
          note = "Official G1 SDK2 locomotion path maps to unitree::robot::g1::LocoClient.SetVelocity."
        },
        @{
          seq = 4
          primitive = "unitree_sdk_call"
          source_primitive = "cooling_station_probe"
          layer = "station_tool"
          client = "CoolingStationAdapter"
          method = "PrepareIceWater"
          args = @{
            item_id = "ice_water_cup"
            station_id = "cooling_station_01"
            dry_run_only = $true
          }
          note = "Verifies that the hub can orchestrate a scene task into a cooling-station tool call."
        },
        @{
          seq = 5
          primitive = "unitree_sdk_call"
          source_primitive = "handoff_feedback"
          layer = "bridge"
          client = "FeedbackAdapter"
          method = "ReportReady"
          args = @{
            text_cn = "Dry-run sequence completed. Waiting for hub context update."
          }
          note = "Closed-loop cognition: robot side explicitly reports completion and observable feedback."
        }
      )
    }
  }
}

$HubResponse = Invoke-RestMethod `
  -Uri "$HubUrl/api/command" `
  -Method Post `
  -ContentType "application/json; charset=utf-8" `
  -Body ($CommandEnvelope | ConvertTo-Json -Depth 20)

$PushResponse = $null
if (-not $HubOnly) {
  $PushResponse = Invoke-RestMethod `
    -Uri "$RobotUrl/api/g1/execute" `
    -Method Post `
    -ContentType "application/json; charset=utf-8" `
    -Body ($HubResponse.command | ConvertTo-Json -Depth 30)
}

[PSCustomObject]@{
  message_id = $HubResponse.command.message_id
  task_id = $CommandEnvelope.command.params.task_id
  hub_ack = $HubResponse.ack.status
  robot_push_status = if ($PushResponse) { $PushResponse.status } else { "skipped" }
  final_robot_status = if ($PushResponse) { $PushResponse.final_ack.status } else { $null }
  robot_url = if ($HubOnly) { $null } else { "$RobotUrl/api/g1/execute" }
} | Format-List

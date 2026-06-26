# Unitree G1 SDK alignment note

Date: 2026-06-25

## Conclusion

The fake-G1 zip is a protocol-level stand-in, not an exact Unitree SDK simulator.

The current Tongyu output registry now separates:

- Official Unitree SDK2 G1 bindings:
  - `AudioClient.TtsMaker` for G1 speech/TTS.
  - `LocoClient.SetVelocity` for short dry-run movement.
- Tongyu bridge extensions:
  - `SafetyGuard.CheckPreconditions`
  - `WaypointPlanner.PlanThenLocoSetVelocity`
  - `WaterStationAdapter.DeliverItem`
  - `FeedbackAdapter.ReportReady`

## What changed

`output_tools.json` previously used adapter-shaped calls such as `SportClient.Move` and
`SportClient.MoveByWaypoint`. Official SDK2 has a `go2::SportClient`, but the G1
high-level locomotion API is exposed through `unitree::robot::g1::LocoClient`.

The registry now uses:

- `g1_speak_notice`: `AudioClient.TtsMaker`
- `g1_move_probe`: `LocoClient.SetVelocity`
- `g1_navigate_water_station`: bridge-only `WaypointPlanner.PlanThenLocoSetVelocity`

The fake G1 receiver still accepts the sequence because it is designed to simulate
the DeviceCommand protocol and ACK loop, not enforce real DDS calls.

## Source check

- Official Unitree SDK2 repository: `unitreerobotics/unitree_sdk2`
- G1 locomotion: `include/unitree/robot/g1/loco/g1_loco_client.hpp`
- G1 audio example: `example/g1/audio/g1_audio_client_example.cpp`
- Python SDK2 notes: `unitree_sdk2_python` README says Python keeps SDK2-compatible data structures and control methods.

## Handoff note for robot teammate

The real robot-side bridge should implement:

1. `SafetyGuard` locally before any SDK call.
2. `AudioClient.TtsMaker(text, speaker_id)` for onboard speech.
3. `LocoClient.SetVelocity(vx, vy, omega, duration)` or `LocoClient.Move(vx, vy, vyaw)` for small safe movement probes.
4. Waypoint navigation only after mapping scene waypoints to a safe locomotion/navigation layer; it is not a native G1 `MoveByWaypoint` SDK call.
5. `RobotACK` posts back to the hub after accepted/running/final states.

# G1 Ubuntu 桥接服务 Demo

这份 demo 给机器人 Ubuntu 电脑使用。它先完成三件事：

1. 在 Ubuntu 上启动 `0.0.0.0:8731`。
2. 接收中控下发的标准 `DeviceCommand`。
3. dry-run 打印动作链，并把 ACK 回传到中控。

默认不会真正调用 Unitree SDK，不会让机器人运动。确认协议跑通后，加 `--real-sdk --network-interface <网卡名>`，服务会把动作表中的 `G1ArmActionClient.ExecuteAction` 映射到 PC2 本机的 Unitree SDK。

## 1. 启动

Ubuntu 电脑 IP 约定为：

```text
192.168.1.172
```

中控主机固定为：

```text
192.168.1.50:8798
```

在 Ubuntu 上运行：

```bash
cd Intelligent_space_orchestrator/examples/g1_ubuntu_bridge
python3 g1_bridge_demo.py --host 0.0.0.0 --port 8731 --hub-url http://192.168.1.50:8798 --register
```

真实 SDK 动作：

```bash
python3 g1_bridge_demo.py --host 0.0.0.0 --port 8731 --hub-url http://192.168.1.50:8798 --network-interface eth0 --real-sdk --register
```

如果仓库目录不同，只要进入 `examples/g1_ubuntu_bridge` 后运行即可。

## 2. 联通检查

Ubuntu 本机：

```bash
curl http://127.0.0.1:8731/health
curl http://192.168.1.50:8798/api/health
```

中控电脑：

```powershell
curl http://192.168.1.172:8731/health
```

看到 `status: ok` 后，再从中控前端“输出测试”里测试 G1。

## 3. 中控会 POST 什么

中控会请求：

```text
POST http://192.168.1.172:8731/api/g1/execute
Content-Type: application/json
```

最小 JSON 格式：

```json
{
  "message_type": "device_command",
  "message_id": "cmd_sdk_1782716617139",
  "target_id": "unitree_g1",
  "target_type": "robot",
  "command": {
    "type": "g1.unitree_sdk_sequence",
    "params": {
      "task_id": "g1_arm_test_001",
      "scene_id": "g1_sdk_sequence",
      "speech_cn": "G1 动作测试开始。",
      "safety": {
        "dry_run": true,
        "speed_limit_mps": 0.25,
        "min_human_distance_m": 0.8
      },
      "sdk_sequence": [
        {
          "seq": 1,
          "primitive": "unitree_sdk_call",
          "source_primitive": "safety_check",
          "layer": "bridge",
          "client": "SafetyGuard",
          "method": "CheckPreconditions",
          "args": {
            "dry_run": true,
            "min_human_distance_m": 0.8,
            "speed_limit_mps": 0.25
          }
        },
        {
          "seq": 2,
          "primitive": "unitree_sdk_call",
          "source_primitive": "arm_action",
          "layer": "unitree_arm",
          "client": "G1ArmActionClient",
          "method": "ExecuteAction",
          "args": {
            "action_name": "high wave",
            "action_id": 4
          }
        },
        {
          "seq": 3,
          "primitive": "unitree_sdk_call",
          "source_primitive": "report_ready",
          "layer": "feedback",
          "client": "FeedbackAdapter",
          "method": "ReportReady",
          "args": {
            "status": "ready"
          }
        }
      ]
    }
  }
}
```

桥接服务主要读取：

```text
payload.message_id
payload.command.type
payload.command.params.task_id
payload.command.params.sdk_sequence
```

## 4. ACK 回传格式

执行完后，Ubuntu 侧要 POST：

```text
POST http://192.168.1.50:8798/api/robot/ack
```

格式：

```json
{
  "message_id": "cmd_sdk_1782716617139",
  "task_id": "g1_arm_test_001",
  "target_id": "unitree_g1",
  "target_type": "robot",
  "status": "ok",
  "stage": "report_ready",
  "progress": 1.0,
  "executed_steps": ["safety_check", "arm_action", "report_ready"],
  "simulated": true,
  "telemetry": {
    "executor": "g1_ubuntu_bridge_demo",
    "control_mode": "dry_run"
  }
}
```

失败时：

```json
{
  "message_id": "cmd_sdk_1782716617139",
  "target_id": "unitree_g1",
  "status": "failed",
  "stage": "bridge_error",
  "progress": 0,
  "error": "具体错误"
}
```

## 5. 真实 Unitree SDK 接入点

PC2 服务的真实 SDK 接入点在 `g1_bridge_demo.py` 的 `execute_sdk_step()`。

中控目前会给这些 step：

| client | method | 含义 |
| --- | --- | --- |
| `SafetyGuard` | `CheckPreconditions` | 检查调试模式、急停、人距、电量、地面空间。 |
| `AudioClient` / `SpeechAdapter` | `TtsMaker` / `Speak` | 机器人播报 `args.text_cn`。 |
| `LocoClient` / `SportClient` | `SetVelocity` / waypoint 方法 | 低速移动或导航。 |
| `G1ArmActionClient` | `ExecuteAction` | 已实现：执行手臂动作，优先读取 `args.action_name` 对应的 `action_map`，否则读取 `args.action_id`。 |
| `BridgeRuntime` | `Sleep` | 两个动作之间等待。 |
| `FeedbackAdapter` | `ReportReady` | 结束并准备 ACK。 |

动作表目前按 `action_id`：

| id | action_name |
| --- | --- |
| 0 | release arm |
| 1 | shake hand |
| 2 | high five |
| 3 | hug |
| 4 | high wave |
| 5 | clap |
| 6 | face wave |
| 7 | left kiss |
| 8 | heart |
| 9 | right heart |
| 10 | hands up |
| 11 | x-ray |
| 12 | right hand up |
| 13 | reject |
| 14 | right kiss |
| 15 | two-hand kiss |

真实动作前，建议机器人侧强制做自己的安全检查。中控发来的 `safety.dry_run` 只能作为协议字段，不能替代现场安全判断。

## 6. 中控前端测试

打开：

```text
http://192.168.1.50:8798/agent-console
```

进入“输出测试”，G1 地址填写：

```text
http://192.168.1.172:8731
```

推荐顺序：

```text
health -> G1 SDK 基础测试链 -> release arm -> high wave -> shake hand -> 十项动作链
```

不要一开始直接跑长动作链。

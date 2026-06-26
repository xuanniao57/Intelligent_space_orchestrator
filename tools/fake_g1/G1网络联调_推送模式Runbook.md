# G1 网络联调：中枢 JSON 推送到 Fake G1

Fake G1 是协议级测试服务，用来验证“智场同语中枢 -> G1 机器人桥接服务 -> ACK 回流”这条链路。它不模拟底层 DDS，也不替代真实 Unitree SDK。

## 1. 启动中枢

在仓库根目录：

```powershell
powershell -ExecutionPolicy Bypass -File .\start_hub_local.ps1 -Port 8798
```

局域网测试时：

```powershell
powershell -ExecutionPolicy Bypass -File .\start_hub_lan.ps1 -Port 8798
```

检查：

```powershell
Invoke-RestMethod http://127.0.0.1:8798/api/health
```

## 2. 启动 Fake G1

另开一个 PowerShell：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start_fake_g1.ps1 `
  -Port 8731 `
  -HubUrl http://127.0.0.1:8798 `
  -StepDelay 0.08
```

检查：

```powershell
Invoke-RestMethod http://127.0.0.1:8731/health
```

## 3. 在前端测试输出

打开：

```text
http://127.0.0.1:8798/agent-console
```

进入“输出测试”，G1 地址填写：

```text
http://127.0.0.1:8731
```

从工具列表中选择 G1 相关动作，发送后应看到：

- 中枢命令记录新增。
- Fake G1 控制台打印接收到的 SDK 风格 dry-run 步骤。
- 主监测页感知回传中出现 robot ACK。
- `/api/robot/ack/history` 中出现 `accepted -> running -> ok`。

## 4. 直接 POST 测试

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\fake_g1\send_unitree_sdk_test_command.ps1 `
  -HubUrl http://127.0.0.1:8798 `
  -RobotUrl http://127.0.0.1:8731 `
  -RequestText "联调测试：中枢驱动 G1 做一组安全 dry-run"
```

预期输出包含：

```text
hub_ack            : ok
robot_push_status  : ok
final_robot_status : ok
```

## 5. 真 G1 同学怎么接

真机侧可以先实现一个与 Fake G1 兼容的 HTTP 服务：

```text
POST /api/g1/execute
```

服务接收中枢下发的 `DeviceCommand`，读取 `command.params.sdk_sequence`，逐步映射到 Unitree SDK2 / ROS2 / 自己的控制节点，并按阶段回传：

```text
POST http://<hub-ip>:8798/api/robot/ack
```

最小 ACK：

```json
{
  "message_id": "cmd_unitree_sdk_...",
  "task_id": "g1_sdk_dryrun_...",
  "target_id": "unitree_g1",
  "status": "ok",
  "stage": "report_ready",
  "progress": 1.0,
  "executed_steps": ["safety_check", "speak", "move_probe"],
  "simulated": false,
  "telemetry": {
    "executor": "real_g1_bridge",
    "control_mode": "unitree_sdk2_high_level"
  }
}
```

## 6. 常见问题

- 中枢收不到 ACK：检查 Fake G1 的 `-HubUrl` 是否指向中枢电脑，而不是机器人侧自己的 `127.0.0.1`。
- 机器人端收不到命令：检查输出测试页的 G1 地址，局域网时应填写机器人电脑可访问的 IP。
- 中文日志乱码：通常只是 Windows 终端编码问题，HTTP JSON 仍是 UTF-8。

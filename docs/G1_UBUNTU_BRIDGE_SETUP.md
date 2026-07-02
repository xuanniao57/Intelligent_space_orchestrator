# G1 Ubuntu 接收中枢命令配置

本文档面向当前单台 G1 Ubuntu 控制电脑：

- G1 Ubuntu IP：`192.168.1.172`
- 中控主机 IP：`192.168.1.50`
- 中控入口：`http://192.168.1.50:8798`
- 推荐 G1 接收端口：`8731`
- 当前中枢 target_id：`unitree_g1`

## 0. 可直接运行的 Ubuntu demo

项目内已经提供最小桥接服务：

```text
examples/g1_ubuntu_bridge/g1_bridge_demo.py
examples/g1_ubuntu_bridge/README.md
```

在 G1 Ubuntu 电脑上运行：

```bash
cd Intelligent_space_orchestrator/examples/g1_ubuntu_bridge
python3 g1_bridge_demo.py --host 0.0.0.0 --port 8731 --hub-url http://192.168.1.50:8798 --register
```

默认是 dry-run，只打印中控下发的 SDK step，不会让机器人运动。协议跑通后，机器人同学只需要在 `execute_sdk_step()` 里把 `SafetyGuard`、`AudioClient`、`LocoClient`、`G1ArmActionClient` 等分支映射到真实 Unitree SDK。

## 1. 当前 SDK 基础测试链

前端“G1 SDK 基础测试链”会把四个动作组装成一个标准 `DeviceCommand`：

```text
g1_safety_check -> g1_speak_notice -> g1_move_probe -> g1_report_ready
```

下发命令类型：

```text
command.type = g1.unitree_sdk_sequence
target_id = unitree_g1
target_type = robot
```

`command.params.sdk_sequence` 中每一步都是 SDK/桥接调用描述：

- `SafetyGuard.CheckPreconditions`：机器人侧安全检查，非官方 SDK。
- `AudioClient.TtsMaker`：G1 语音播报，对应 Unitree SDK2 G1 audio。
- `LocoClient.SetVelocity`：短程速度探针，对应 Unitree SDK2 G1 loco。
- `FeedbackAdapter.ReportReady`：执行结果回传中枢，非官方 SDK。

当前链路适合做安全 dry-run 与协议联调；真实移动前，机器人侧桥接服务必须自己确认调试模式、急停、人距和场地安全。

## 2. 推荐方式 A：中枢直推到 Ubuntu

机器人 Ubuntu 启动一个 HTTP 服务：

```text
0.0.0.0:8731
POST /api/g1/execute
GET  /health
```

中控前端“输出测试”的 G1 地址填写：

```text
http://192.168.1.172:8731
```

中枢会自动推送到：

```text
POST http://192.168.1.172:8731/api/g1/execute
```

Ubuntu 侧收到的请求体就是完整 `DeviceCommand`。机器人桥接服务应读取：

```text
payload.command.type
payload.command.params.sdk_sequence
payload.message_id
payload.command.params.task_id
```

执行后回传 ACK：

```bash
curl -X POST http://192.168.1.50:8798/api/robot/ack \
  -H "Content-Type: application/json" \
  -d '{
    "message_id": "cmd_agent_xxx",
    "task_id": "manual_g1_sdk_xxx",
    "target_id": "unitree_g1",
    "target_type": "robot",
    "status": "ok",
    "stage": "report_ready",
    "progress": 1.0,
    "executed_steps": ["safety_check", "speak", "move_probe", "report_ready"],
    "simulated": false,
    "telemetry": {
      "executor": "real_g1_ubuntu_bridge",
      "control_mode": "unitree_sdk2_high_level"
    }
  }'
```

## 3. 备选方式 B：Ubuntu 轮询中枢

如果 Ubuntu 不方便开放入站端口，可让机器人主动轮询：

```bash
curl "http://192.168.1.50:8798/api/devices/unitree_g1/commands?command_type=g1.unitree_sdk_sequence&limit=5"
```

执行完同样 POST：

```text
http://192.168.1.50:8798/api/robot/ack
```

轮询模式不要求中控知道 Ubuntu 的端口，但机器人侧需要记录 `after_message_id`，避免重复执行旧命令。

## 4. 可选注册

Ubuntu 桥接服务启动后可注册，便于中控页面显示设备在线：

```bash
curl -X POST http://192.168.1.50:8798/api/devices/register \
  -H "Content-Type: application/json" \
  -d '{
    "target_id": "unitree_g1",
    "target_type": "robot",
    "client_id": "g1_ubuntu_01",
    "ip": "192.168.1.172",
    "port": 8731,
    "transport": "http_push",
    "capabilities": ["g1.unitree_sdk_sequence"],
    "status": "online"
  }'
```

注意：注册只用于在线状态和能力描述；当前中枢是否直推，仍由前端或请求里的 `robot_url` 决定。

## 5. Ubuntu 侧最小检查

在中控电脑上：

```powershell
Test-NetConnection 192.168.1.172 -Port 8731
```

应看到 `TcpTestSucceeded: True`。

在 Ubuntu 上：

```bash
curl http://192.168.1.50:8798/api/health
curl http://127.0.0.1:8731/health
```

两个都通，才说明“中控能推过去、机器人能回传 ACK”这条链路具备基础条件。
# 说明

最新配置说明以 `docs/G1_PC2_DECODER_SERVICE.md` 为准。本文件保留为早期桥接联调记录。

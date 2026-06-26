# 同语中枢信息流与进程处理设计

> 本文档描述中控平台如何持续接收环境数据反馈、如何与 LLM Agent 推理循环衔接、如何调度命令执行与状态回传。
> 版本：0.4（2026-06-22）

---

## 1. 信息流动总图

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│                              外部环境                                        │
│  冲之场环境传感器 ──┐                                                        │
│  机器人摄像头      ──┼──► 数据分析组（多传感器融合）                          │
│  其他 IoT 设备     ──┘                                                        │
└──────────────────────────────────┬──────────────────────────────────────────┘
                                   │ SceneSemanticFrame
                                   ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                          同语中控平台 (Central Hub)                           │
│                                                                              │
│  ┌─────────────────────┐    ┌─────────────────────┐    ┌─────────────────┐  │
│  │ 输入接收进程/线程     │    │ LLM Agent 推理进程    │    │ 输出调度进程     │  │
│  │ /api/scene/semantic │───►│ 语义解析 → 策略推理   │───►│ DeviceCommand   │  │
│  │ ingest              │    │ → 工具调用计划        │    │ 分发 → TCP/HTTP │  │
│  └─────────────────────┘    └─────────────────────┘    └─────────────────┘  │
│           │                          │                          │            │
│           ▼                          ▼                          ▼            │
│  ┌─────────────────────┐    ┌─────────────────────┐    ┌─────────────────┐  │
│  │ 语义状态缓存          │    │ Agent Run / 工作轨迹  │    │ 设备 ACK 接收   │  │
│  │ semantic_scene_store  │    │ agent_run_store       │    │ device/robot ack│  │
│  └─────────────────────┘    └─────────────────────┘    └─────────────────┘  │
│           ▲                          ▲                          │            │
│           │                          │                          ▼            │
│  ┌─────────────────────┐    ┌─────────────────────┐    ┌─────────────────┐  │
│  │ 环境反馈循环          │◄───│ 上下文更新           │◄───│ 执行结果入库     │  │
│  │ （下一轮输入）        │    │                       │    │ command_history │  │
│  └─────────────────────┘    └─────────────────────┘    └─────────────────┘  │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. 进程/线程模型建议

当前 `server.py` 为单进程 Flask 服务。为承载持续环境反馈与异步媒体生成，建议扩展为以下模型：

### 2.1 主进程：HTTP/WebSocket 服务

- 职责：REST API、WebSocket 广播、状态存储、设备注册。
- 端口：`8798`。
- 关键模块：`server.py` 现有代码。

### 2.2 后台线程：语义输入缓冲与去重

- 职责：
  - 接收高频 `SceneSemanticFrame`（如 1–5 Hz）。
  - 按 `space_id` 做时间窗口去重，避免 LLM 反复触发。
  - 将有效帧放入 `agent_inbox` 队列。
- 输出：`agent_inbox`（线程安全队列）。

### 2.3 后台线程/进程：LLM Agent 推理循环

- 职责：
  - 从 `agent_inbox` 消费语义帧。
  - 维护短期记忆（最近 N 帧、最近命令、最近 ACK）。
  - 调用 LLM 生成 `AgentIntention` 和 `DeviceCommand` 列表。
  - 将命令写入 `command_outbox`。
- 触发策略：
  - 事件驱动：高优先级帧立即触发。
  - 心跳驱动：低优先级场景每 5–10 秒合并评估一次。

### 2.4 后台线程：命令分发器

- 职责：
  - 从 `command_outbox` 取出命令。
  - 根据 `target_type` + `routing` 选择传输方式：
    - `robot` → ROS2 topic / HTTP 轮询 / TCP `12001`/`12002`
    - `spray_gateway` → TCP `12003` 或 HTTP 轮询
    - `speaker_gateway` → 先生成音频 → TCP `12004`
    - `projection_gateway` → 先生成视频 → TCP `12005`
  - 对需要媒体生成的命令，先投递到 `media_generation_tool`，等待 `asset_ready` 回调后再分发。

### 2.5 后台线程：媒体生成 worker（可选独立进程）

- 职责：
  - 消费 `media.generate_audio` / `media.generate_video` 任务。
  - 调用 TTS / 视频生成 tool。
  - 完成后回调 `POST /api/media/asset_ready`。
- 建议：若 TTS/视频生成耗时较长，放入独立进程，避免阻塞主服务。

### 2.6 后台线程：ACK 聚合与上下文反馈

- 职责：
  - 接收 `/api/device/ack` 和 `/api/robot/ack`。
  - 更新 `command_history` 中对应命令的执行状态。
  - 将执行结果摘要写回 Agent 上下文（如最近失败命令、设备离线）。

---

## 3. 核心数据结构

### 3.1 Agent Inbox 项

```python
{
  "frame_id": "ssf_...",
  "space_id": "garden_01",
  "priority": 0.7,
  "frame": { /* SceneSemanticFrame */ },
  "received_at_ms": 1781500000000
}
```

### 3.2 Command Outbox 项

```python
{
  "message_id": "cmd_...",
  "target_type": "spray_gateway",
  "command": { /* DeviceCommand */ },
  "requires_media": false,
  "media_asset_id": None,
  "status": "pending",  # pending / media_generating / dispatched / acked / failed
  "retry_count": 0
}
```

### 3.3 Agent 上下文摘要

```python
{
  "current_space_id": "garden_01",
  "latest_scene": { /* SceneSemanticFrame */ },
  "recent_commands": [ /* 最近 20 条命令 */ ],
  "recent_acks": [ /* 最近 20 条 ACK */ ],
  "active_tasks": [ /* 尚未收到 ok/failed 的命令 */ ],
  "device_status": {
    "unitree_g1_alpha": "online",
    "spray_gateway": "offline_since_..."
  }
}
```

---

## 4. 处理时序示例

```text
T0  传感器数据到达数据分析组
T1  数据分析组生成 SceneSemanticFrame，POST /api/scene/semantic/ingest
T2  中控：验证 → 存储 semantic_scene_store → 放入 agent_inbox
T3  LLM Agent：消费帧，结合上下文推理 → 生成 2 条 DeviceCommand
    - Cmd-A: speaker.speak（需 TTS）
    - Cmd-B: spray.scene（直接执行）
T4  命令分发器：
    - Cmd-B 直接 TCP 发送至喷雾网关 12003
    - Cmd-A 投递至 media_generation_tool，状态设为 media_generating
T5  媒体生成 worker 完成 TTS → POST /api/media/asset_ready
T6  命令分发器收到回调 → 通过 TCP 12004 推送音频至音响网关
T7  喷雾网关执行完毕 → POST /api/device/ack
T8  音响网关执行完毕 → POST /api/device/ack
T9  ACK 聚合器更新 command_history，并将结果摘要写回 Agent 上下文
T10 下一轮 SceneSemanticFrame 到达，Agent 可感知上一轮动作结果
```

---

## 5. 关键设计决策

| 决策 | 方案 | 原因 |
|------|------|------|
| 中控是否直接消费原始传感器？ | 否，只接收 `SceneSemanticFrame` | 职责分离，数据分析组拥有多传感器融合自主权 |
| LLM Agent 是否阻塞主服务？ | 否，独立线程/进程 | 避免推理延迟影响 API 响应 |
| 媒体生成是否阻塞命令分发？ | 否，异步回调 | TTS/视频生成可能耗时数秒 |
| 设备命令使用推还是拉？ | 默认推（TCP/ROS2），兼容拉（HTTP 轮询） | 机器人侧推荐 ROS2；简易网关推荐 TCP/HTTP |
| ACK 是否必须？ | `ack_required=true` 时必须 | 保证关键命令可追溯；非关键通知可关闭 |
| 失败命令是否重试？ | 最多 3 次，带指数退避 | 避免网络抖动导致动作丢失 |

---

## 6. 与现有代码的衔接

- `server.py` 已存在 `SceneSemanticFrame`、`process_scene_semantic_payload`、`DeviceCommand`、`connected_devices`。
- 当前 `process_scene_semantic_payload` 仅存储并返回候选 tool target，尚未真正调用 LLM。
- 下一步：在 `server.py` 中增加 `agent_inbox` 队列和后台调度线程，将 `available_tool_targets` 扩展为实际命令生成。
- 当前 G1 输出以 `g1.unitree_sdk_sequence` / `g1.motion_primitive` 为主。Fake G1 与真机桥接服务都消费同一类 `DeviceCommand`，执行后通过 `/api/robot/ack` 回流到中枢记忆和下一轮上下文。

---

## 7. 待办接口（后端需补齐）

| 接口 | 方法 | 用途 |
|------|------|------|
| `/api/media/asset_ready` | `POST` | 媒体生成完成回调 |
| `/api/devices/<target_id>/commands` | `GET` | 硬件客户端轮询命令（已存在） |
| `/api/devices/register` | `POST` | 硬件客户端注册（已存在） |
| `/api/command/batch` | `POST` | 批量下发命令（可选） |
| `/api/agent/context/<space_id>` | `GET` | 查询 Agent 当前上下文 |

---

## 8. 变更日志

| 版本 | 日期 | 说明 |
|------|------|------|
| 0.4 | 2026-06-22 | 初版：定义输入缓冲、LLM 推理、命令分发、媒体生成、ACK 反馈五大进程/线程及其数据结构与时序。 |

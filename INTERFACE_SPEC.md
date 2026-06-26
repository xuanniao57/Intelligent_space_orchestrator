# 同语中枢 I/O 接口规范 v0.4

> 本文档定义中控平台（Tongyu Central Hub）与数据分析组、输出执行组之间的**规范化输入输出接口**。
> 适用对象：数据分析组（多传感器融合）、机器人组（宇树 G1×2）、场景输出组（喷雾、音响、投影）。
> 版本：0.4（2026-06-22）

---

## 1. 总体架构

```text
┌─────────────────────────────────────────────────────────────────────┐
│                         中控平台 (Central Hub)                        │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────────┐  │
│  │ 语义输入层    │→│ LLM Agent    │→│ 命令输出 / 媒体生成调度    │  │
│  │ SceneSemantic│  │ 推理与轨迹    │  │ DeviceCommand            │  │
│  └──────────────┘  └──────────────┘  └──────────────────────────┘  │
└──────────┬──────────────────────────────────────┬──────────────────┘
           │ HTTP/WebSocket                         │ HTTP/TCP/ROS2
           ▼                                        ▼
┌─────────────────────┐              ┌───────────────────────────────┐
│ 数据分析组           │              │ 输出执行组                     │
│ 冲之场传感器+摄像头   │              │ 宇树 G1 ×2、喷雾网关、音响网关、投影网关 │
│ → 融合语义帧         │              │ ← 机器人/场景/媒体命令           │
└─────────────────────┘              └───────────────────────────────┘
```

**设计原则**

- 中控只接收**综合场景语义帧**（`scene_semantic_frame`），不直接消费原始传感器数据。
- 输出命令使用统一信封 `DeviceCommand`，通过 `target_type` + `command.type` 区分设备。
- 音响、投影内容文件**预置在终端/上位电脑本地**，JSON 只传操作名、内容 ID、音量等必要字段，尽量简化。
- 所有硬件客户端先注册、再轮询命令、执行后回传 ACK；机器人通过 ROS2 topic 或 HTTP 轮询接收命令。

---

## 2. 输入接口（Input）

### 2.1 接口端点

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/api/scene/semantic/ingest` | 数据分析组投递融合后的场景语义帧 |
| `GET`  | `/api/scene/semantic/latest` | 查询最新场景语义缓存 |
| `GET`  | `/api/scene/semantic/latest/<space_id>` | 查询指定空间最新语义 |

### 2.2 场景语义帧 `SceneSemanticFrame`

```json
{
  "message_type": "scene_semantic_frame",
  "frame_id": "ssf_1781500000000",
  "timestamp": "2026-06-22T14:30:00.000+08:00",
  "source_id": "data_analysis_fusion_v1",
  "space_id": "garden_01",
  "time_window": {
    "start": "2026-06-22T14:25:00+08:00",
    "end": "2026-06-22T14:30:00+08:00",
    "aggregation": "5s"
  },
  "scene": {
    "situation_id": "garden_water_stress",
    "summary": "花园区域高温干燥，植物水分胁迫显著，人流稀疏。",
    "intent_hint": "watering_request",
    "tags": ["hot", "dry", "plant_stressed", "low_density"]
  },
  "semantics": {
    "environment": {
      "label": "高温干燥",
      "level": "warning",
      "tags": ["hot", "dry"]
    },
    "crowd": {
      "label": "稀疏",
      "level": "normal",
      "tags": ["low_density"]
    },
    "vegetation": {
      "label": "缺水胁迫",
      "level": "alert",
      "tags": ["plant_stressed"]
    }
  },
  "entities": [
    {
      "id": "person_01",
      "type": "person",
      "zone": "entrance",
      "attributes": {"posture": "standing", "group_size": 1}
    }
  ],
  "events": [
    {
      "type": "entered_zone",
      "target": "person_01",
      "zone": "entrance",
      "confidence": 0.92
    }
  ],
  "affordances": [
    {
      "action": "guide",
      "target_zone": "social_circle_01",
      "reason": "入口有人进入，可引导参观。"
    }
  ],
  "safety": {
    "level": "normal",
    "notes": "无异常"
  },
  "raw_refs": [
    {"source": "chongzhi_env", "sensor_ids": ["env_01", "env_02"]},
    {"source": "robot_cam_01", "type": "rgb"}
  ],
  "semantic_tags": ["hot", "dry", "plant_stressed", "low_density"],
  "confidence": 0.88,
  "priority": 0.7
}
```

### 2.3 字段说明

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `message_type` | string | 是 | 固定 `scene_semantic_frame` |
| `frame_id` | string | 否 | 帧唯一 ID，建议 `ssf_<毫秒时间戳>` |
| `timestamp` | string | 否 | ISO 8601 +08:00 |
| `source_id` | string | 否 | 数据分析组版本标识，便于追溯 |
| `space_id` | string | 是 | 空间 ID，如 `garden_01` |
| `time_window` | object | 否 | 融合时间窗口 |
| `scene` | object | 否 | 场景总体描述 |
| `semantics` | object | 否 | 分类语义（环境/人群/植被/情绪等） |
| `entities` | array | 否 | 检测到的实体 |
| `events` | array | 否 | 离散事件 |
| `affordances` | array | 否 | 系统可执行机会 |
| `safety` | object | 否 | 安全等级与备注 |
| `raw_refs` | array | 否 | 原始传感器引用，用于审计 |
| `semantic_tags` | array | 否 | 标准化语义标签，供 ECA/LLM 匹配 |
| `confidence` | float | 否 | 0–1 融合置信度 |
| `priority` | float | 否 | 0–1 场景优先级 |

### 2.4 标准化语义标签池（推荐）

| 维度 | 标签示例 |
|------|---------|
| 环境 | `hot`, `cold`, `dry`, `wet`, `humid`, `loud`, `quiet`, `air_quality_attention` |
| 人群 | `empty`, `low_density`, `moderate`, `crowded`, `queue_forming` |
| 情绪 | `mood_bright`, `mood_stressed`, `mood_neutral`, `mood_mixed` |
| 植被 | `plant_stressed`, `plant_healthy` |
| 安全 | `safety_normal`, `safety_watch`, `safety_alert` |
| 事件 | `person_detected`, `entered_zone`, `left_zone`, `gathering` |

### 2.5 响应体

```json
{
  "frame": { "message_type": "scene_semantic_frame", ... },
  "agent_run": {
    "run_id": "run_1781500000000",
    "frame_id": "ssf_1781500000000",
    "space_id": "garden_01",
    "status": "accepted",
    "trace": [ "receive", "memory_update", "reason", "tool_plan" ],
    "pending_decision": "LLM policy/tool planner should transform this semantic frame into DeviceCommand objects."
  },
  "commands": [],
  "command_count": 0,
  "next_api": "POST /api/command for robot, spray, speaker, or projection commands"
}
```

---

## 3. 输出接口（Output）

### 3.1 统一命令信封 `DeviceCommand`

```json
{
  "message_type": "device_command",
  "message_id": "cmd_1781500000000",
  "timestamp": "2026-06-22T14:30:00.000+08:00",
  "source_id": "control_hub",
  "target_id": "unitree_g1_alpha",
  "target_type": "robot",
  "verb": "command",
  "command": {
    "type": "g1.action",
    "params": { }
  },
  "routing": {
    "mqtt_topic": "talking_spaces/unitree_g1_alpha/command",
    "ros2_topic": "/talking_spaces/g1/command",
    "http_poll": "/api/devices/unitree_g1_alpha/commands",
    "tcp_endpoint": "192.168.1.201:12001"
  },
  "ack_required": true,
  "timeout_ms": 60000
}
```

### 3.2 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/api/command` | 通用命令下发 |
| `GET` | `/api/devices/<target_id>/commands` | 硬件客户端轮询命令 |
| `POST` | `/api/devices/register` | 硬件客户端注册 |
| `POST` | `/api/device/ack` | 通用设备 ACK |
| `POST` | `/api/robot/ack` | 机器人专用 ACK（语义同 device/ack） |

---

## 4. 输出类型详细规范

### 4.1 机器人命令 `target_type: robot`

支持两台机器人：`unitree_g1_alpha`、`unitree_g1_beta`。

#### 4.1.1 `g1.action` — 通用动作

```json
{
  "type": "g1.action",
  "params": {
    "action": "navigate_and_speak",
    "waypoints": [{"x": 2.5, "y": 1.8}],
    "speech": "花园里的植物需要浇水",
    "gesture": "point_to_garden",
    "speed_limit_mps": 0.25,
    "min_human_distance_m": 0.8
  }
}
```

#### 4.1.2 `g1.unitree_sdk_sequence` — SDK 风格动作序列

用于当前热感知清凉联动和其他 G1 dry-run / 真机联调。中枢输出一组桥接层可解释的 `sdk_sequence`，机器人侧服务接收后映射到 Unitree SDK2 / ROS2 / 自定义控制节点。

```json
{
  "type": "g1.unitree_sdk_sequence",
  "params": {
    "task_id": "g1_sdk_dryrun_1781500000000",
    "sdk_sequence": [
      {
        "seq": 1,
        "primitive": "unitree_sdk_call",
        "layer": "bridge",
        "client": "SafetyGuard",
        "method": "CheckPreconditions",
        "args": {"min_human_distance_m": 0.8}
      },
      {
        "seq": 2,
        "primitive": "unitree_sdk_call",
        "layer": "unitree_high_level",
        "client": "LocoClient",
        "method": "SetVelocity",
        "args": {"vx": 0.12, "vy": 0.0, "omega": 0.0, "duration": 1.0}
      }
    ]
  }
}
```

#### 4.1.3 `g1.motion_primitive` — 原子动作序列

```json
{
  "type": "g1.motion_primitive",
  "params": {
    "task_id": "task_1781500000000",
    "primitives": [
      {"seq": 1, "primitive": "navigate", "target": "cooling_handoff_01"},
      {"seq": 2, "primitive": "speak", "text_cn": "请跟我来"},
      {"seq": 3, "primitive": "gesture", "name": "wave"}
    ],
    "safety": {
      "speed_limit_mps": 0.25,
      "min_human_distance_m": 0.8
    }
  }
}
```

---

### 4.2 喷雾命令 `target_type: spray_gateway`

喷雾硬件由上位电脑（Client）通过局域网接收命令并控制物理设备。JSON 只包含必要控制字段。

#### 4.2.1 `spray.scene` — 场景喷雾

```json
{
  "message_type": "device_command",
  "message_id": "cmd_1781500000000",
  "target_id": "spray_gateway",
  "target_type": "spray_gateway",
  "command": {
    "type": "spray.scene",
    "params": {
      "cmd_id": "cmd_1781500000000",
      "op": "mist",
      "zone": "garden_01",
      "duration_sec": 30,
      "intensity": 0.4
    }
  }
}
```

#### 4.2.2 `spray.stop`

```json
{
  "type": "spray.stop",
  "params": {
    "cmd_id": "cmd_1781500000001",
    "op": "stop",
    "zone": "garden_01"
  }
}
```

---

### 4.3 音响命令 `target_type: speaker_gateway`

音频文件预置在音响上位电脑本地，JSON 只传操作名、内容 ID、音量等必要字段。

#### 4.3.1 `speaker.play` — 播放指定音频

```json
{
  "message_type": "device_command",
  "message_id": "cmd_1781500000000",
  "target_id": "speaker_gateway",
  "target_type": "speaker_gateway",
  "command": {
    "type": "speaker.play",
    "params": {
      "cmd_id": "cmd_1781500000000",
      "op": "play",
      "content_id": "welcome_to_tongyu",
      "volume": 65,
      "loop": false
    }
  }
}
```

#### 4.3.2 `speaker.stop` — 停止播放

```json
{
  "type": "speaker.stop",
  "params": {
    "cmd_id": "cmd_1781500000002",
    "op": "stop"
  }
}
```

---

### 4.4 投影命令 `target_type: projection_gateway`

视频文件预置在投影上位电脑本地，JSON 只传操作名、内容 ID、音量等必要字段。

#### 4.4.1 `projection.play` — 播放指定视频

```json
{
  "message_type": "device_command",
  "message_id": "cmd_1781500000000",
  "target_id": "projection_gateway",
  "target_type": "projection_gateway",
  "command": {
    "type": "projection.play",
    "params": {
      "cmd_id": "cmd_1781500000000",
      "op": "play",
      "content_id": "water_alert_visual",
      "volume": 80,
      "loop": false
    }
  }
}
```

#### 4.4.2 `projection.stop` — 停止播放

```json
{
  "type": "projection.stop",
  "params": {
    "cmd_id": "cmd_1781500000003",
    "op": "stop"
  }
}
```

---

### 4.5 终端内容映射表（Media Mapping）

由于音频/视频文件直接放在终端上位电脑上，中枢不需要知道文件路径，只需要下发**内容 ID**。各终端维护一张本地 `content_id → 文件路径` 的映射表。

#### 示例映射表（音响上位电脑）

```json
{
  "welcome_to_tongyu": "/media/audio/welcome_to_tongyu.wav",
  "garden_cooling_notice": "/media/audio/garden_cooling_notice.wav",
  "crowd_guide_north": "/media/audio/crowd_guide_north.wav"
}
```

#### 示例映射表（投影上位电脑）

```json
{
  "water_alert_visual": "/media/video/water_alert_visual.mp4",
  "welcome_loop": "/media/video/welcome_loop.mp4",
  "temp_warning_red": "/media/video/temp_warning_red.mp4"
}
```

#### 内容注册接口（可选）

终端启动后可向中枢上报自己支持的内容 ID 列表：

`POST /api/devices/register`

```json
{
  "target_id": "speaker_gateway",
  "target_type": "speaker_gateway",
  "client_id": "speaker_pc_01",
  "ip": "192.168.1.203",
  "port": 12004,
  "transport": "tcp_server",
  "capabilities": ["speaker.play", "speaker.stop"],
  "content_ids": ["welcome_to_tongyu", "garden_cooling_notice", "crowd_guide_north"],
  "status": "online"
}
```

---

## 5. 设备注册与 ACK

### 5.1 设备注册 `POST /api/devices/register`

```json
{
  "target_id": "spray_gateway",
  "target_type": "spray_gateway",
  "client_id": "spray_pc_01",
  "ip": "192.168.1.202",
  "port": 22001,
  "transport": "tcp_server",
  "capabilities": ["spray.scene", "spray.stop"],
  "status": "online",
  "meta": {"hardware_version": "v1.2"}
}
```

### 5.2 设备 ACK `POST /api/device/ack`

```json
{
  "message_id": "cmd_1781500000000",
  "task_id": "task_1781500000000",
  "target_id": "spray_gateway",
  "target_type": "spray_gateway",
  "status": "ok",
  "stage": "spraying",
  "progress": 0.5,
  "executed_steps": ["validate", "start_mist"],
  "device_time": "2026-06-22T14:30:15.000+08:00",
  "error": null,
  "telemetry": {"tank_level": 0.72, "pressure_kpa": 120},
  "artifacts": []
}
```

### 5.3 ACK 状态枚举

| 状态 | 含义 |
|------|------|
| `accepted` | 已接收，等待执行 |
| `running` | 执行中 |
| `ok` | 执行完成 |
| `failed` | 执行失败 |
| `blocked` | 被安全/环境条件阻塞 |
| `timeout` | 超时 |

---

## 6. 信息流时序

```text
1. 传感器 → 数据分析组（原始数据）
2. 数据分析组 → POST /api/scene/semantic/ingest（SceneSemanticFrame）
3. 中控 → 语义存储 + LLM Agent 推理 → 产生 DeviceCommand
4. 中控 → 媒体生成 tool（可选）→ 生成音频/视频资产
5. 中控 → 命令分发：HTTP 轮询 / TCP 推流 / ROS2 topic
6. 硬件客户端执行 → POST /api/device/ack 或 /api/robot/ack
7. 中控 → 更新命令状态 → 反馈给 Agent 上下文 → 影响下一轮决策
```

---

## 7. 变更日志

| 版本 | 日期 | 说明 |
|------|------|------|
| 0.4 | 2026-06-22 | 新增双机器人、喷雾、音响、投影、媒体生成接口；统一 DeviceCommand 信封；新增端口分配引用。 |

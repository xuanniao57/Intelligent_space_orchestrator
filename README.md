# 智场同语中枢 Agent

[![UrbanAgents](https://img.shields.io/badge/runtime-UrbanAgents%20%2F%20Urban--Hermes-2f80ed?logo=github)](https://github.com/xuanniao57/UrbanAgents)
[![Star UrbanAgents](https://img.shields.io/github/stars/xuanniao57/UrbanAgents?style=social)](https://github.com/xuanniao57/UrbanAgents)

智场同语中枢 Agent 是一个面向真实空间的中控平台：它持续接收场景语义输入，组织 Agent 上下文，调用喷雾、音乐、投影、Unitree G1 等工具，并把设备 ACK / 机器人反馈沉淀为下一轮上下文和长期记忆。

本项目的 Agent runtime 基于 [UrbanAgents / Urban-Hermes](https://github.com/xuanniao57/UrbanAgents)。UrbanAgents 负责提供 Hermes runtime、工具注册、模型-工具 loop、记忆和可审计执行链；本仓库在它上面实现“智场同语”的物理场景语义、输出协议和中枢监控界面。觉得这个 runtime 有用的话，欢迎顺手给 UrbanAgents 点个 star。

## 当前能力

- 主监测页：查看感知终端语义回传、Agent 推理/执行链、步骤详情和目标设定。
- 输入测试页：从注册语义块组装 world state，测试 Agent 对单语义/复合语义的响应。
- 输出测试页：从注册工具列表组装动作链，测试喷雾、音乐、投影、G1 SDK 桥接等输出。
- 两个核心场景：
  - 热感知清凉联动：温度/人群/手势语义 -> 喷雾、投影、G1 递冰水动作链。
  - 声音鸡尾酒音乐调和：多维声音/情绪/活跃度语义 -> 音乐层与投影波形。
- Fake G1：没有真实机器人时，可以用本地假 G1 服务测试 TCP/HTTP JSON 下发和 ACK 回流。

## 快速开始

要求：Windows + PowerShell + Python 3.10 或以上。推荐 Python 3.10/3.11。

```powershell
git clone https://github.com/xuanniao57/Intelligent_space_orchestrator.git
cd Intelligent_space_orchestrator

powershell -ExecutionPolicy Bypass -File .\scripts\setup.ps1
notepad .env
powershell -ExecutionPolicy Bypass -File .\start_hub_local.ps1 -Port 8798
```

打开：

```text
http://127.0.0.1:8798/agent-console
```

`.env` 至少填一个模型供应商。当前推荐：

```env
TONGYU_HERMES_PROVIDER=deepseek
TONGYU_HERMES_MODEL=deepseek-v4-flash
DEEPSEEK_API_KEY=你的 key
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-v4-flash
```

如果暂时没有模型 key，也可以设置：

```env
TONGYU_AGENT_DISABLE_LLM=1
```

这样可以用规则和 fallback 技能跑通设备协议、前端和 ACK 闭环。

## 启动 Fake G1

另开一个 PowerShell：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start_fake_g1.ps1 -Port 8731 -HubUrl http://127.0.0.1:8798
```

Fake G1 健康检查：

```text
http://127.0.0.1:8731/health
```

主监测页或输出测试页里，G1 地址填写：

```text
http://127.0.0.1:8731
```

## 一键跑两场景 demo

默认使用 fallback/规则路径，适合先验证安装：

```powershell
powershell -ExecutionPolicy Bypass -File .\run_zhichang_tongyu_agent_demo.ps1 -ResetMemory
```

使用真实 LLM：

```powershell
powershell -ExecutionPolicy Bypass -File .\run_zhichang_tongyu_agent_demo.ps1 -UseLiveLLM -ResetMemory
```

## Hermes / UrbanAgents 是怎么装的

本仓库随带一个裁剪后的 UrbanAgents 快照：

```text
third_party/UrbanAgents
```

安装脚本会执行：

```powershell
python -m pip install -e .\third_party\UrbanAgents --no-build-isolation
```

UrbanAgents 自身已经 vendor 了 Hermes runtime：

```text
third_party/UrbanAgents/hermes_urban_agent/urban_hermes/_vendor/hermes_runtime
```

所以协作者不需要另外下载 Hermes。若要跟踪 UrbanAgents 的上游开发，请看：

```text
https://github.com/xuanniao57/UrbanAgents
```

## 协作者主要改哪里

输入语义注册：

```text
central_hub/data/agent_io_registry/input_semantics.json
```

输出工具注册：

```text
central_hub/data/agent_io_registry/output_tools.json
```

Agent runtime 适配：

```text
central_hub/backend/zhichang_hermes_runtime.py
```

中枢 API / 设备路由：

```text
central_hub/backend/server.py
```

监控与测试前端：

```text
frontend/zhichang_agent_console
```

Fake G1：

```text
tools/fake_g1
```

## I/O 协议入口

- `POST /api/scene/semantic/ingest`：输入场景语义帧 `SceneSemanticFrame`
- `POST /api/agent/input-test/assemble`：按注册语义块组装 world state，并可触发 Agent
- `POST /api/agent/output-test/sequence`：按注册工具组装输出动作链
- `POST /api/robot/ack`：机器人 ACK 回流
- `POST /api/device/ack`：普通设备 ACK 回流
- `GET /api/hermes/status`：内部 Agent runtime 状态。前端不展示 Hermes 名称，但该兼容路径保留给开发调试。

更多协议说明见：

```text
INTERFACE_SPEC.md
INFORMATION_FLOW.md
central_hub/data/agent_io_registry/unitree_g1_sdk_alignment_20260625.md
tools/fake_g1/
```

## Unitree G1 SDK 对齐

当前注册表已按官方 SDK2/G1 接口修正：

- G1 语音：`unitree::robot::g1::AudioClient.TtsMaker`
- G1 短程动作：`unitree::robot::g1::LocoClient.SetVelocity`
- 路径导航、取冰水、ACK：属于智场同语桥接层或场地工具层，不伪装成官方 SDK 调用。

Fake G1 是协议级替身，不是低层 DDS/SDK 模拟器。

## 发布注意

- 不要提交 `.env`、`.venv`、`logs/`、运行 memory、临时录屏。
- 如果需要开放到局域网，使用 `start_hub_lan.ps1` 或把 `start_hub_local.ps1` 的 `-HostName` 改为 `0.0.0.0`，并确认防火墙。
- 真实现场设备一般通过交换机/路由器接入中控主机，本仓库的其他协作者主要做语义注册、工具协议、Agent loop 和前端监测界面的迭代。

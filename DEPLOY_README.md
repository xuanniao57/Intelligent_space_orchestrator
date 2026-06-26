# 部署说明

推荐使用仓库根目录的自动脚本部署。仓库已内置 UrbanAgents 快照，安装时会一并安装 Agent runtime。

## 1. 克隆

```powershell
git clone https://github.com/xuanniao57/Intelligent_space_orchestrator.git
cd Intelligent_space_orchestrator
```

## 2. 安装

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\setup.ps1
```

脚本会：

- 从 `.env.example` 创建 `.env`。
- 创建 `.venv`。
- 安装 `third_party/UrbanAgents`。
- 安装中枢后端依赖。

## 3. 配置模型

编辑 `.env`：

```powershell
notepad .env
```

DeepSeek V4 Flash 示例：

```env
TONGYU_HERMES_PROVIDER=deepseek
TONGYU_HERMES_MODEL=deepseek-v4-flash
DEEPSEEK_API_KEY=你的 key
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-v4-flash
TONGYU_DEEPSEEK_THINKING_DEFAULT=disabled
```

没有 key 时可以先用 fallback：

```env
TONGYU_AGENT_DISABLE_LLM=1
```

## 4. 启动

本机：

```powershell
powershell -ExecutionPolicy Bypass -File .\start_hub_local.ps1 -Port 8798
```

局域网：

```powershell
powershell -ExecutionPolicy Bypass -File .\start_hub_lan.ps1 -Port 8798
```

如果现场智能插座也固定连接 `192.168.1.50:8798`，使用 8798 分流模式：

```powershell
powershell -ExecutionPolicy Bypass -File .\start_hub_lan_mux.ps1
```

此模式下，对外仍访问 `http://192.168.1.50:8798/agent-console`；内部中枢 Flask 运行在 `127.0.0.1:8799`，来自智能插座 `192.168.1.156` 的原始 TCP 会被分流到喷雾网关内部端口 `8080`。

访问：

```text
http://127.0.0.1:8798/agent-console
```

## 5. Fake G1 联调

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start_fake_g1.ps1 -Port 8731 -HubUrl http://127.0.0.1:8798
```

Fake G1 接收中枢下发的 `/api/g1/execute`，并把 ACK 回传到中枢 `/api/robot/ack`。

## 6. 协作开发入口

- 输入语义：`central_hub/data/agent_io_registry/input_semantics.json`
- 输出工具：`central_hub/data/agent_io_registry/output_tools.json`
- Agent runtime 适配：`central_hub/backend/zhichang_hermes_runtime.py`
- 前端：`frontend/zhichang_agent_console`

UrbanAgents 上游：

```text
https://github.com/xuanniao57/UrbanAgents
```

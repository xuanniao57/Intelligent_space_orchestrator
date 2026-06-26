# central_hub 说明

这里是“智场同语中枢 Agent”的后端服务、协议数据和设备桥接代码。仓库根目录的 `README.md` 是协作者的主入口，安装和启动优先看根目录文档。

## 启动

推荐从仓库根目录启动：

```powershell
powershell -ExecutionPolicy Bypass -File .\start_hub_local.ps1 -Port 8798
```

然后打开：

```text
http://127.0.0.1:8798/agent-console
```

如果需要局域网访问：

```powershell
powershell -ExecutionPolicy Bypass -File .\start_hub_lan.ps1 -Port 8798
```

## 主要目录

- `backend/`：Flask API、Agent 适配、设备路由和 ACK 回流。
- `data/agent_io_registry/`：输入语义块、输出工具、场景 schema 和 G1 SDK 对齐文档。
- `data/zhichang_tongyu_agent_memory.jsonl`：运行期记忆文件，默认不提交。

## Agent runtime

中枢后端通过 `backend/zhichang_hermes_runtime.py` 连接仓库内置的 UrbanAgents：

```text
third_party/UrbanAgents
```

UrbanAgents 已经包含 Hermes runtime，安装脚本会用 editable 模式安装它。协作者通常只需要改智场同语的语义注册、工具注册和场景 loop；除非要改 Agent 底层机制，否则不需要单独安装 Hermes。

UrbanAgents 上游：

```text
https://github.com/xuanniao57/UrbanAgents
```

## 常用 API

- `GET /api/health`
- `GET /api/hermes/status`
- `POST /api/scene/semantic/ingest`
- `POST /api/agent/input-test/assemble`
- `POST /api/agent/output-test/sequence`
- `POST /api/robot/ack`
- `POST /api/device/ack`

协议细节见根目录的 `INTERFACE_SPEC.md` 和 `INFORMATION_FLOW.md`。

# 智场同语中枢运维 Runbook

本文件用于本机或局域网联调。面向首次安装的完整说明见 `README.md`。

## 本机启动

```powershell
powershell -ExecutionPolicy Bypass -File .\start_hub_local.ps1 -Port 8798
```

打开：

```text
http://127.0.0.1:8798/agent-console
```

健康检查：

```powershell
Invoke-RestMethod http://127.0.0.1:8798/api/health
Invoke-RestMethod http://127.0.0.1:8798/api/hermes/status
```

## 局域网启动

```powershell
powershell -ExecutionPolicy Bypass -File .\start_hub_lan.ps1 -Port 8798
```

如果其他设备无法访问，先确认：

- Windows 防火墙允许入站 TCP `8798`。
- 中控主机和终端设备在同一网段或路由可达。
- 终端设备使用 `http://<hub-ip>:8798` 作为中枢地址。

## Fake G1

另开一个 PowerShell：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start_fake_g1.ps1 -Port 8731 -HubUrl http://127.0.0.1:8798
```

健康检查：

```powershell
Invoke-RestMethod http://127.0.0.1:8731/health
```

主监测页或输出测试页里的 G1 地址填：

```text
http://127.0.0.1:8731
```

## 运行日志

默认日志和临时结果不提交 Git：

```text
logs/
central_hub/data/*.log
central_hub/data/zhichang_tongyu_agent_memory.jsonl
central_hub/data/demo_recordings/
central_hub/data/qa_screenshots/
```

## 常见问题

- `api/hermes/status` 显示 runtime 不可用：先运行 `scripts/setup.ps1`，确认 `third_party/UrbanAgents` 已安装。
- 模型无返回或超时：检查 `.env` 中的 `DEEPSEEK_API_KEY`、`DEEPSEEK_MODEL` 和 `TONGYU_HERMES_LLM_TIMEOUT_SEC`。
- 不想走真实模型：设置 `TONGYU_AGENT_DISABLE_LLM=1`，先验证协议闭环。
- 设备没有 ACK：检查设备端是否能访问 `POST http://<hub-ip>:8798/api/robot/ack` 或 `/api/device/ack`。

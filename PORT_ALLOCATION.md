# 同语中枢 LAN 端口分配表

> 本文档规定中控平台与局域网内各硬件客户端/网关之间的**TCP 端口分配**，避免与现有后端服务冲突。
> 适用网络：硬件电脑（Client）与总控（Server）所在同一局域网。  > 版本：0.4（2026-06-22）

---

## 1. 端口分配总览

| 端口 | 用途 | 角色 | 协议 | 绑定地址建议 | 备注 |
|------|------|------|------|--------------|------|
| `8798` | 同语中枢主服务 | Server | HTTP + WebSocket | `0.0.0.0` | 已运行，勿占用 |
| `12001` | 宇树 G1 机器人 Alpha | Client/Server | TCP 控制流 + 状态回传 | 机器人机载电脑 IP | 中枢 → G1 命令 |
| `12002` | 宇树 G1 机器人 Beta | Client/Server | TCP 控制流 + 状态回传 | 机器人机载电脑 IP | 中枢 → G1 命令 |
| `12003` | 喷雾网关 | Client/Server | TCP 控制流 | 喷雾上位电脑 IP | 中枢 → 喷雾 |
| `12004` | 音响网关 | Client/Server | TCP 音频推流 + 控制 | 音响上位电脑 IP | 中枢生成音频后推送 |
| `12005` | 投影网关 | Client/Server | TCP 视频推流 + 控制 | 投影上位电脑 IP | 中枢生成视频后推送 |
| `12006` | 预留：第三台机器人/移动平台 | — | TCP | — | 为未来扩展保留 |
| `12007` | 预留：环境执行器/灯光网关 | — | TCP | — | 为未来扩展保留 |
| `12008` | 预留：备用媒体/告警通道 | — | TCP | — | 为未来扩展保留 |

**说明**

- 每个硬件客户端在启动后向中枢 `POST /api/devices/register` 上报自己的 `ip` + `port`。
- 端口分配采用 `12001–12008` 区间，远离常用开发端口（3000/5000/8000/8080/9000），也远离 ABC Square 公网端口 `28002`。
- 如果现场局域网已有 `12000` 段占用，可整体偏移到 `12101–12108`，但需所有客户端同步。

---

## 2. 当前机器已用端口

截至 2026-06-22，中控服务器所在电脑监听端口：

| 端口 | 进程 | 说明 |
|------|------|------|
| `8798` | Python Flask (PID 25732) | 同语中枢主服务 |

**未占用预留端口**：`12001–12008` 当前空闲，可立即分配。

---

## 3. 各客户端连接模式

### 3.1 机器人（宇树 G1 ×2）

| 项目 | 配置 |
|------|------|
| `target_id` | `unitree_g1_alpha` / `unitree_g1_beta` |
| `target_type` | `robot` |
| 推荐端口 | `12001` / `12002` |
| 传输方式 | **方式 A**：ROS2 topic（推荐）<br>`/talking_spaces/g1/command` 或 `/talking_spaces/g1/sdk_sequence` |
| 备选方式 | **方式 B**：HTTP 轮询 `GET /api/devices/unitree_g1_alpha/commands` |
| 备选方式 | **方式 C**：TCP 直连 `12001`/`12002` 接收 JSON 命令 |
| ACK 地址 | `POST http://<hub-ip>:8798/api/robot/ack` |

### 3.2 喷雾网关

| 项目 | 配置 |
|------|------|
| `target_id` | `spray_gateway` |
| `target_type` | `spray_gateway` |
| 端口 | `12003` |
| 模式 | 喷雾上位电脑作为 TCP Server 监听 `12003`，中枢作为 Client 连接并发送命令；或反向由上位电脑轮询 `/api/devices/spray_gateway/commands` |
| 命令类型 | `spray.scene`, `spray.stop` |
| ACK 地址 | `POST http://<hub-ip>:8798/api/device/ack` |

### 3.3 音响网关

| 项目 | 配置 |
|------|------|
| `target_id` | `speaker_gateway` |
| `target_type` | `speaker_gateway` |
| 端口 | `12004` |
| 模式 | 中枢生成音频资产后，通过 TCP `12004` 推流至上位电脑；上位电脑本地播放 |
| 命令类型 | `speaker.speak`, `speaker.play_asset` |
| ACK 地址 | `POST http://<hub-ip>:8798/api/device/ack` |

### 3.4 投影网关

| 项目 | 配置 |
|------|------|
| `target_id` | `projection_gateway` |
| `target_type` | `projection_gateway` |
| 端口 | `12005` |
| 模式 | 中枢生成视频资产后，通过 TCP `12005` 推流至上位电脑；上位电脑本地播放 |
| 命令类型 | `projection.play_video`, `projection.show_scene` |
| ACK 地址 | `POST http://<hub-ip>:8798/api/device/ack` |

---

## 4. 防火墙建议

若各硬件客户端无法连接中枢，请在对应电脑上开放以下端口：

- 中枢电脑：入站 TCP `8798`（已有）。
- 喷雾上位电脑：入站 TCP `12003`。
- 音响上位电脑：入站 TCP `12004`。
- 投影上位电脑：入站 TCP `12005`。
- 机器人机载电脑：入站 TCP `12001` / `12002`（如使用 TCP 直连模式）。

Windows PowerShell（管理员）示例：

```powershell
New-NetFirewallRule -DisplayName "Tongyu Spray Gateway" -Direction Inbound -Protocol TCP -LocalPort 12003 -Action Allow
New-NetFirewallRule -DisplayName "Tongyu Speaker Gateway" -Direction Inbound -Protocol TCP -LocalPort 12004 -Action Allow
New-NetFirewallRule -DisplayName "Tongyu Projection Gateway" -Direction Inbound -Protocol TCP -LocalPort 12005 -Action Allow
New-NetFirewallRule -DisplayName "Tongyu G1 Alpha" -Direction Inbound -Protocol TCP -LocalPort 12001 -Action Allow
New-NetFirewallRule -DisplayName "Tongyu G1 Beta" -Direction Inbound -Protocol TCP -LocalPort 12002 -Action Allow
```

---

## 5. 服务注册示例

中枢启动后，各客户端应调用：

```bash
curl -X POST http://<hub-ip>:8798/api/devices/register \
  -H "Content-Type: application/json" \
  -d '{
    "target_id": "spray_gateway",
    "target_type": "spray_gateway",
    "client_id": "spray_pc_01",
    "ip": "192.168.1.202",
    "port": 12003,
    "transport": "tcp_server",
    "capabilities": ["spray.scene", "spray.stop"],
    "status": "online"
  }'
```

---

## 6. 变更日志

| 版本 | 日期 | 说明 |
|------|------|------|
| 0.4 | 2026-06-22 | 初版：分配 12001–12008，覆盖 2 台机器人、喷雾、音响、投影及 3 个预留端口；记录当前 8798 占用情况。 |

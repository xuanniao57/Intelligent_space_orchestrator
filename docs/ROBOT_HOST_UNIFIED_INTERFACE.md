# 智场同语机器人主机统一接口

本文档说明中控主机 `192.168.1.50` 与机器人 Ubuntu 主机 `192.168.1.172` 的统一通信方式。目标是：中控只调用一个稳定入口，机器人主机收到命令后再启动或调用本机的动作、语音、导航、视频、音频、ASR 程序。

## 1. 当前网络与进程

| 角色 | 地址 | 说明 |
|---|---:|---|
| 中控服务 | `http://192.168.1.50:8798` | Flask/mux 对外服务，接收机器人 ACK、视频、音频、ASR 文本 |
| 机器人网关 | `http://192.168.1.172:8731` | Ubuntu 主机上运行 `tongyu-robot-gateway` |
| 视频回传 | `udp://192.168.1.50:5005` | RGB/Depth 分片图像，约 5fps，中控维护 1 分钟队列 |
| 原始音频回传 | `tcp://192.168.1.50:6000` | 麦克风/环境音原始 chunk，中控维护 1 分钟队列 |
| ASR 文本回传 | `POST http://192.168.1.50:8798/api/perception/asr/text` | 需要带语音片段起止时间戳 |

## 2. 六类功能

| 功能 | 统一路由 | 是否需要回传数据 | 说明 |
|---|---|---:|---|
| 动作执行 | `motion.arm_action` | 否，仅 ACK | 调用动作执行程序或本机 UDP action receiver |
| 语音播报 | `speech.speak` | 否，仅 ACK | 调用 TTS/语音播报程序 |
| 路径导航 | `navigation.goto` | 否，仅 ACK | 调用导航目标发送程序 |
| 摄像头视频 | `video.start / stop / status` | 是 | 中控发 start 后，机器人视频程序运行 10 分钟，向中控 `5005/UDP` 回传 |
| 原始音频 | `audio.mic_start / mic_stop / mic_status` | 是 | 中控发 start 后，机器人音频程序运行 10 分钟，向中控 `6000/TCP` 回传 |
| 对话转文字 | `asr.start / stop / status` | 是 | 机器人 ASR 程序默认运行 10 分钟，把文本片段 POST 回中控 |

## 3. 机器人 Ubuntu 侧启动

机器人 Ubuntu 主机安装本项目 Python 包后，直接运行：

```bash
tongyu-robot-gateway \
  --host 0.0.0.0 \
  --port 8731 \
  --hub-url http://192.168.1.50:8798 \
  --host-ip 192.168.1.172 \
  --network-interface eth0 \
  --register
```

只看命令是否会被正确解析、不真正启动本机程序：

```bash
tongyu-robot-gateway \
  --host 0.0.0.0 \
  --port 8731 \
  --hub-url http://192.168.1.50:8798 \
  --host-ip 192.168.1.172 \
  --network-interface eth0 \
  --dry-run
```

如果需要先导出配置模板，再把本机程序路径改成真实路径：

```bash
tongyu-robot-gateway --dump-default-config > tongyu_robot_gateway_config.json
tongyu-robot-gateway --config tongyu_robot_gateway_config.json --host 0.0.0.0 --port 8731 --hub-url http://192.168.1.50:8798 --host-ip 192.168.1.172 --network-interface eth0 --register
```

机器人本机自检：

```bash
curl http://127.0.0.1:8731/health
```

## 4. 中控侧一键调用

中控电脑安装本项目后，可以用 SDK 命令行：

```bash
tongyu-hardware robot-gateway-health
tongyu-hardware robot-gateway-status
tongyu-hardware robot-speak --text "我已收到中枢命令。"
tongyu-hardware robot-action --g1-action "shake hand"
tongyu-hardware robot-nav --nav-x 1.2 --nav-y 0.3 --nav-yaw 1.57
tongyu-hardware robot-video-start --ttl-sec 600
tongyu-hardware robot-mic-start --ttl-sec 600
tongyu-hardware robot-asr-start --ttl-sec 600
```

也可以直接用示例脚本，不依赖安装入口：

```bash
tongyu-robotctl --robot-url http://192.168.1.172:8731 health
tongyu-robotctl --robot-url http://192.168.1.172:8731 video-start --ttl-sec 600
tongyu-robotctl --robot-url http://192.168.1.172:8731 video-stop
tongyu-robotctl --robot-url http://192.168.1.172:8731 mic-start --ttl-sec 600
tongyu-robotctl --robot-url http://192.168.1.172:8731 asr-start --ttl-sec 600
```

## 5. 统一命令格式

```json
{
  "protocol": "tongyu.robot.unified.v1",
  "message_id": "robot_cmd_...",
  "task_id": "video_start_...",
  "target_id": "unitree_g1",
  "target_type": "robot",
  "ack": true,
  "command": {
    "domain": "video",
    "action": "start",
    "params": {
      "ttl_sec": 600
    }
  }
}
```

`domain.action` 会映射到机器人端配置文件中的 `routes`。例如 `video.start` 启动 `services.video_relay`，`audio.mic_start` 启动 `services.mic_relay`。

## 6. 中控侧验证回传

视频：

```bash
curl http://192.168.1.50:8798/api/perception/vision/status
curl "http://192.168.1.50:8798/api/perception/vision/queue/rgb?limit=10"
```

浏览器看实时画面：

```text
http://192.168.1.50:8798/vision-monitor
```

音频：

```bash
curl http://192.168.1.50:8798/api/perception/audio/status
curl "http://192.168.1.50:8798/api/perception/audio/chunks?limit=10"
curl "http://192.168.1.50:8798/api/perception/audio/raw?seconds=5" --output g1_audio_5s.raw
```

ASR 文本：

```bash
curl http://192.168.1.50:8798/api/perception/asr/history
```

机器人 ASR 程序需要按以下格式回传：

```json
{
  "source_id": "unitree_g1_asr",
  "text": "这里有人在说话",
  "language": "zh-CN",
  "confidence": 0.86,
  "start_time": "2026-07-02T12:00:01.120+08:00",
  "end_time": "2026-07-02T12:00:03.840+08:00"
}
```

## 7. 队列与时长约定

- 视频流不是常开。中控发送 `video.start` 后，机器人端默认运行 600 秒；需要提前结束时发送 `video.stop`。
- 视频中控队列按类型维护：`rgb` 和 `depth` 各保留 300 帧。按 5fps 计算，约等于最近 1 分钟。
- 音频流不是常开。中控发送 `audio.mic_start` 后，机器人端默认运行 600 秒；需要提前结束时发送 `audio.mic_stop`。
- 音频中控队列按时间维护，保留最近 60 秒的原始 chunk。
- ASR 文本服务默认运行 600 秒，可用 `asr.stop` 提前结束；中控不按 byte 队列存储文本，而是保留最近 300 条片段，每条必须有文本对应的起止时间戳。

## 8. 未来扩展

新增功能只需要在机器人端配置文件增加两类条目：

1. 长时运行服务写入 `services`，例如雷达、定位、SLAM、监听进程。
2. 一次性动作写入 `routes`，handler 可使用 `udp`、`subprocess_once`、`service_start`、`service_stop`、`service_status`。

扩展示例：

```json
{
  "services": {
    "thermal_relay": {
      "description": "Forward thermal camera frames to central hub.",
      "cmd": ["python3", "/home/unitree/code/thermal_relay.py", "--hub-url", "{hub_url}"],
      "cwd": "/home/unitree/code",
      "autostart": false,
      "ttl_sec": 600
    }
  },
  "routes": {
    "thermal.start": {
      "handler": "service_start",
      "service": "thermal_relay",
      "default_params": {"ttl_sec": 600}
    },
    "thermal.stop": {
      "handler": "service_stop",
      "service": "thermal_relay"
    }
  }
}
```

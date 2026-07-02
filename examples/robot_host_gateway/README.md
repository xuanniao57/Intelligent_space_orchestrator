# 机器人 Ubuntu 主机统一网关

这一组文件运行在机器人 Ubuntu 主机 `192.168.1.172`，负责把中控 `192.168.1.50:8798` 发来的统一 JSON 命令分发给本机程序。

## 文件

| 文件 | 运行位置 | 用途 |
|---|---|---|
| `tongyu_robot_gateway.py` | 机器人 Ubuntu 主机 | 兼容包装器，实际入口是 `tongyu_hardware.robot_gateway` |
| `tongyu_robot_gateway_config.example.json` | 机器人 Ubuntu 主机 | 服务和命令路由配置 |
| `tongyu_robotctl.py` | 中控或任意测试电脑 | 兼容包装器，实际入口是 `tongyu_hardware.robotctl` |

## 机器人端启动

真实运行：

```bash
tongyu-robot-gateway \
  --config tongyu_robot_gateway_config.example.json \
  --host 0.0.0.0 \
  --port 8731 \
  --hub-url http://192.168.1.50:8798 \
  --host-ip 192.168.1.172 \
  --network-interface eth0 \
  --register
```

只测试解析、不真正启动本机程序：

```bash
tongyu-robot-gateway \
  --config tongyu_robot_gateway_config.example.json \
  --host 0.0.0.0 \
  --port 8731 \
  --hub-url http://192.168.1.50:8798 \
  --host-ip 192.168.1.172 \
  --network-interface eth0 \
  --dry-run
```

本机自检：

```bash
curl http://127.0.0.1:8731/health
```

## 中控侧测试

```bash
tongyu-robotctl --robot-url http://192.168.1.172:8731 health
tongyu-robotctl --robot-url http://192.168.1.172:8731 speak "我已收到中枢命令。"
tongyu-robotctl --robot-url http://192.168.1.172:8731 action --name "shake hand"
tongyu-robotctl --robot-url http://192.168.1.172:8731 nav --x 1.2 --y 0.3 --yaw 1.57
tongyu-robotctl --robot-url http://192.168.1.172:8731 video-start --ttl-sec 600
tongyu-robotctl --robot-url http://192.168.1.172:8731 video-stop
tongyu-robotctl --robot-url http://192.168.1.172:8731 mic-start --ttl-sec 600
tongyu-robotctl --robot-url http://192.168.1.172:8731 asr-start --ttl-sec 600
tongyu-robotctl --robot-url http://192.168.1.172:8731 status
```

## 六类功能

| 功能 | 路由 | 默认行为 |
|---|---|---|
| 动作执行 | `motion.arm_action` | 向本机动作执行程序发 action id/name/packet |
| 语音播报 | `speech.speak` | 向本机 TTS 接收程序发文本 |
| 路径导航 | `navigation.goto` | 调用导航目标发送程序 |
| 摄像头视频 | `video.start / stop / status` | 启动视频回传，默认 600 秒，5fps，发往中控 `5005/UDP` |
| 原始音频 | `audio.mic_start / mic_stop / mic_status` | 启动麦克风回传，默认 600 秒，发往中控 `6000/TCP` |
| 对话转文字 | `asr.start / stop / status` | 启动 ASR 程序，默认 600 秒，文本 POST 到中控 `/api/perception/asr/text` |

## 扩展方法

新增长期运行程序写到 `services`；新增一次性命令写到 `routes`。配置中可以使用 `{hub_url}`、`{hub_ip}`、`{network_interface}`、`{ttl_sec}` 等变量。

更完整的接口说明见：

```text
docs/ROBOT_HOST_UNIFIED_INTERFACE.md
```

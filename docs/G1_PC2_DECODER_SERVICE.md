# G1 PC2 解码服务配置说明

本文档保留为早期桥接方案记录。当前推荐方案是机器人 Ubuntu 主机统一网关：

```text
docs/ROBOT_HOST_UNIFIED_INTERFACE.md
```

统一网关命令：

```bash
tongyu-robot-gateway --host 0.0.0.0 --port 8731 --hub-url http://192.168.1.50:8798 --host-ip 192.168.1.172 --network-interface eth0 --register
```

旧的 `examples/g1_ubuntu_bridge/g1_bridge_demo.py` 仍可用于历史 dry-run 和动作表兼容测试。统一网关仍兼容旧入口：

```text
POST http://192.168.1.172:8731/api/g1/execute
```

但新的主协议是：

```text
POST http://192.168.1.172:8731/api/robot/command
```

统一命令格式：

```json
{
  "protocol": "tongyu.robot.unified.v1",
  "message_id": "robot_cmd_xxx",
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

当前六类能力：

| 功能 | 路由 | 说明 |
|---|---|---|
| 动作执行 | `motion.arm_action` | 调用本机 G1 动作程序 |
| 语音播报 | `speech.speak` | 调用本机 TTS/语音播报程序 |
| 路径导航 | `navigation.goto` | 调用本机导航目标发送程序 |
| 摄像头视频 | `video.start / stop / status` | 启停视频回传，默认 10 分钟 |
| 原始音频 | `audio.mic_start / mic_stop / mic_status` | 启停麦克风/环境音回传，默认 10 分钟 |
| 对话转文字 | `asr.start / stop / status` | 启停 ASR 文本回传，默认 10 分钟 |

中控侧测试：

```bash
tongyu-robotctl --robot-url http://192.168.1.172:8731 health
tongyu-robotctl --robot-url http://192.168.1.172:8731 action --name "shake hand"
tongyu-robotctl --robot-url http://192.168.1.172:8731 video-start --ttl-sec 600
```

ACK 仍回传到：

```text
POST http://192.168.1.50:8798/api/robot/ack
```

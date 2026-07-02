# 感知流接入与本地可视化

中控服务启动后会固定开启三类机器人感知回传入口：

| 类型 | 中控入口 | 协议 | 队列 |
|---|---:|---|---|
| G1 RGB/Depth 视频 | `udp://192.168.1.50:5005` | 分片图像 UDP | `rgb`、`depth` 各 300 帧，约 1 分钟 |
| G1 原始音频 | `tcp://192.168.1.50:6000` | 原始音频 chunk TCP | 最近 60 秒 |
| G1 对话 ASR 文本 | `POST http://192.168.1.50:8798/api/perception/asr/text` | HTTP JSON | 最近 300 条 |

视频、音频、ASR 不是默认常开。中控通过机器人统一网关发送 start 命令，机器人端对应程序默认运行 600 秒；需要提前结束时发送 stop 命令。

## 1. 视频协议

机器人 Ubuntu 主机 `192.168.1.172` 将 RGB/Depth UDP 包发送到：

```text
192.168.1.50:5005
```

每个 UDP 包由 9 字节头和图像分片组成：

```text
!I B H H
frame_id:uint32
img_type:uint8     0=RGB, 1=Depth
idx:uint16         当前分片序号
total:uint16       本帧总分片数
payload:bytes      JPEG/PNG 编码后的图像分片
```

中控按 `(frame_id, img_type)` 拼包，拼完后：

- RGB 作为 `image/jpeg` 保存到 `rgb` 队列。
- Depth 作为 `image/png` 保存到 `depth` 队列。
- 过期未拼完的半帧会清理，避免长期占内存。

启动视频回传：

```bash
tongyu-robotctl --robot-url http://192.168.1.172:8731 video-start --ttl-sec 600
```

停止视频回传：

```bash
tongyu-robotctl --robot-url http://192.168.1.172:8731 video-stop
```

## 2. 音频协议

机器人 Ubuntu 主机连接中控：

```text
tcp://192.168.1.50:6000
```

当前中控按原始 bytes chunk 接收和排队，不强制规定采样率、声道、位深。机器人端实际音频程序应在自己的服务说明或配置里声明格式，例如 `PCM s16le / 16kHz / mono`。

启动音频回传：

```bash
tongyu-robotctl --robot-url http://192.168.1.172:8731 mic-start --ttl-sec 600
```

停止音频回传：

```bash
tongyu-robotctl --robot-url http://192.168.1.172:8731 mic-stop
```

## 3. ASR 文本协议

机器人端 ASR 程序将对话文本 POST 到：

```text
http://192.168.1.50:8798/api/perception/asr/text
```

最小 JSON：

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

`start_time` 和 `end_time` 是文本对应的语音片段起止时间。中控接收后会保存 `received_at`，并广播到前端监控流。

## 4. 中控侧验证

查看感知流注册：

```bash
tongyu-hardware stream-list
```

视频：

```bash
tongyu-hardware vision-probe --stream-timeout 10
tongyu-hardware vision-queue --queue-kind rgb --limit 10
```

浏览器可视化：

```text
http://192.168.1.50:8798/vision-monitor
```

音频：

```bash
tongyu-hardware audio-status
tongyu-hardware audio-chunks --limit 10
curl "http://192.168.1.50:8798/api/perception/audio/raw?seconds=5" --output g1_audio_5s.raw
```

ASR：

```bash
tongyu-hardware asr-history --limit 20
```

## 5. 机器人端要做什么

机器人端统一由 `tongyu-robot-gateway` 管理启动和停止。配置文件里的默认服务名：

| 服务名 | 触发路由 | 默认程序 |
|---|---|---|
| `video_relay` | `video.start` | `/home/unitree/code/camera_forward_to_hub.py --dst-ip {hub_ip} --dst-port 5005 --fps 5 --ttl-sec {ttl_sec}` |
| `mic_relay` | `audio.mic_start` | `/home/unitree/code/g1_mic_forward_tcp --dst-ip {hub_ip} --dst-port 6000 --ttl-sec {ttl_sec}` |
| `asr_relay` | `asr.start` | `/home/unitree/code/asr_relay_to_hub.py --hub-url {hub_url}` |

如果机器人端实际程序路径不同，只改 `tongyu_robot_gateway_config.json` 里的 `services` 即可，不需要改中控协议。

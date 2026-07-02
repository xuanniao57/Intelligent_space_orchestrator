# 智场同语硬件 Python SDK

协作者只需要把自己的算法结果变成 SDK 调用。SDK 默认连接中控：

```text
http://192.168.1.50:8798
```

喷雾、灯光、投影、音乐、Unitree G1、视频/音频/ASR 回传都由中控记录命令、ACK 和轨迹。除机器人 Ubuntu 主机的本机程序外，普通协作者不需要直接连接硬件 IP。

## 1. 安装

推荐 conda：

```bash
conda activate tongyu
git clone https://github.com/xuanniao57/Intelligent_space_orchestrator.git
cd Intelligent_space_orchestrator
pip install -e .
```

Ubuntu venv：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
git clone https://github.com/xuanniao57/Intelligent_space_orchestrator.git
cd Intelligent_space_orchestrator
pip install -e .
```

Windows venv：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -U pip
git clone https://github.com/xuanniao57/Intelligent_space_orchestrator.git
cd Intelligent_space_orchestrator
pip install -e .
```

验证：

```bash
python -c "from tongyu_hardware import TongyuHardware; print('sdk ok')"
tongyu-hardware health
```

如果当前 Python 的 Scripts 目录不在 PATH，可以用模块方式等价运行：

```bash
python -m tongyu_hardware.cli health
python -m tongyu_hardware.robot_gateway --help
python -m tongyu_hardware.robotctl --help
```

如果可编辑安装时隔离构建环境报 `Cannot import setuptools.build_meta`，使用：

```bash
pip install -e . --no-build-isolation
```

需要本机 OpenCV 窗口看视觉流时，再安装可选依赖：

```bash
pip install -e ".[stream]"
```

## 2. 网络检查

Ubuntu：

```bash
curl http://192.168.1.50:8798/api/health
ping 192.168.1.50
```

Windows：

```powershell
Test-NetConnection 192.168.1.50 -Port 8798
Invoke-RestMethod http://192.168.1.50:8798/api/health
ping 192.168.1.50
```

端口检查成功即可调用 SDK。若 `ping` 失败但 `8798` 端口成功，通常是 Windows 防火墙禁用了 ICMP，不一定影响 SDK。

## 3. Python 调用

```python
from tongyu_hardware import TongyuHardware

hw = TongyuHardware()
print(hw.health()["status"])
```

喷雾：

```python
hw.spray.mist(duration_sec=5, intensity=0.45, execute=True)
hw.spray.stop(execute=True)
```

灯光：

```python
hw.lights.blue(real_send=True)
hw.lights.green(real_send=True)
hw.lights.white(real_send=True)
hw.lights.amber(real_send=True)
hw.lights.alternate(real_send=True)
hw.lights.off(real_send=True)
```

中控本机音乐播放：

```python
print(hw.speaker.library())
hw.speaker.play(content_id="朋友们.mp3", slot=1, volume=62, loop=True, execute=True)
hw.speaker.stop(execute=True)
```

投影：

```python
hw.projection.power("library_vertical", "on", real_send=True)
hw.projection.playback("library_vertical", "play", real_send=True)
hw.projection.playback("library_vertical", "pause", real_send=True)
hw.projection.playback("library_vertical", "resume", real_send=True)
hw.projection.playback("library_vertical", "stop", real_send=True)
hw.projection.power("library_vertical", "off", real_send=True)
```

可选屏幕：`library_vertical`、`library_horizontal`、`d_wall`。

## 4. Unitree G1 统一网关

机器人 Ubuntu 主机固定为：

```text
http://192.168.1.172:8731
```

安装本包后，Ubuntu 侧可以直接启动机器人网关：

```bash
tongyu-robot-gateway \
  --host 0.0.0.0 \
  --port 8731 \
  --hub-url http://192.168.1.50:8798 \
  --host-ip 192.168.1.172 \
  --network-interface eth0 \
  --register
```

需要先生成配置模板：

```bash
tongyu-robot-gateway --dump-default-config > tongyu_robot_gateway_config.json
```

带配置启动：

```bash
tongyu-robot-gateway \
  --config tongyu_robot_gateway_config.json \
  --host 0.0.0.0 \
  --port 8731 \
  --hub-url http://192.168.1.50:8798 \
  --host-ip 192.168.1.172 \
  --network-interface eth0 \
  --register
```

中控侧一键调用：

```bash
tongyu-robotctl --robot-url http://192.168.1.172:8731 health
tongyu-robotctl --robot-url http://192.168.1.172:8731 speak "我已收到中枢命令。"
tongyu-robotctl --robot-url http://192.168.1.172:8731 action --name "shake hand"
tongyu-robotctl --robot-url http://192.168.1.172:8731 nav --x 1.2 --y 0.3 --yaw 1.57
tongyu-robotctl --robot-url http://192.168.1.172:8731 video-start --ttl-sec 600
tongyu-robotctl --robot-url http://192.168.1.172:8731 mic-start --ttl-sec 600
tongyu-robotctl --robot-url http://192.168.1.172:8731 asr-start --ttl-sec 600
```

也可以走总入口：

```bash
tongyu-hardware robot-gateway-health
tongyu-hardware robot-video-start --ttl-sec 600
tongyu-hardware robot-mic-start --ttl-sec 600
tongyu-hardware robot-asr-start --ttl-sec 600
```

Python 调用：

```python
hw.g1.gateway_health()
hw.g1.speak("我已收到中枢命令。")
hw.g1.gateway_arm_action("shake hand")
hw.g1.navigate(x=1.2, y=0.3, yaw=1.57)
hw.g1.video_start(ttl_sec=600)
hw.g1.mic_start(ttl_sec=600)
hw.g1.asr_start(ttl_sec=600)
```

统一接口说明见 `docs/ROBOT_HOST_UNIFIED_INTERFACE.md`。

## 5. 感知流验证

视频状态与最近 1 分钟队列：

```bash
tongyu-hardware vision-probe --stream-timeout 10
tongyu-hardware vision-queue --queue-kind rgb --limit 10
```

浏览器实时看图像：

```text
http://192.168.1.50:8798/vision-monitor
```

原始音频状态与最近 chunk：

```bash
tongyu-hardware audio-status
tongyu-hardware audio-chunks --limit 10
```

ASR 文本历史：

```bash
tongyu-hardware asr-history --limit 20
```

## 6. 常用命令行测试

默认安全预览，不触发真实硬件：

```bash
tongyu-hardware health
tongyu-hardware spray-mist
tongyu-hardware light-blue
tongyu-hardware speaker-library
tongyu-hardware speaker-play
tongyu-hardware projection-playback --screen library_vertical --playback play
tongyu-hardware g1-action-table
tongyu-hardware stream-list
```

真实发送：

```bash
tongyu-hardware spray-mist --execute
tongyu-hardware light-blue --real-send
tongyu-hardware speaker-play --content-id "朋友们.mp3" --execute
tongyu-hardware projection-playback --screen library_vertical --playback play --real-send
```

## 7. 调试原则

1. 先测网络，再测命令。
2. 先 dry-run 或预览，再真实发送。
3. 一次只测一个设备、一个动作。
4. 失败时保存完整返回 JSON，优先看 `error`、`dispatch_result` 和 ACK。
5. 不绕过中控直连硬件；中控需要记录轨迹、ACK、安全状态和回传数据。

# 智场同语硬件 SDK 快速使用

协作者在自己的电脑上安装 SDK，向中控发送硬件动作请求。中控固定地址：

```text
http://192.168.1.50:8798
```

代码里不要直接写喷雾、灯光、投影、音响等硬件 IP；这些由中控维护。

## 1. 安装

推荐用 conda。Ubuntu 和 Windows 命令基本一致：

```bash
conda activate tongyu
git clone https://github.com/xuanniao57/Intelligent_space_orchestrator.git
cd Intelligent_space_orchestrator
pip install -e .
```

如果不需要修改 SDK，也可以直接从 GitHub 安装：

```bash
conda activate tongyu
pip install git+https://github.com/xuanniao57/Intelligent_space_orchestrator.git
```

安装后验证：

```bash
python -c "from tongyu_hardware import TongyuHardware; print('sdk ok')"
python -m tongyu_hardware.cli health
```

如果 `tongyu-hardware` 命令可用，也可以写成：

```bash
tongyu-hardware health
```

## 2. 不用 conda 时

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

## 3. 网络检查

你的电脑需要和中控在同一局域网，能访问 `192.168.1.50:8798`。

Ubuntu：

```bash
ping 192.168.1.50
curl http://192.168.1.50:8798/api/health
```

Windows：

```powershell
ping 192.168.1.50
Test-NetConnection 192.168.1.50 -Port 8798
Invoke-RestMethod http://192.168.1.50:8798/api/health
```

看到 `status: ok` 后再测试硬件命令。

## 4. 最小 Python 调用

```python
from tongyu_hardware import TongyuHardware

hw = TongyuHardware()
print(hw.health()["status"])
```

## 5. 命令行测试

默认都是安全测试，不会真实触发硬件：

```bash
python -m tongyu_hardware.cli health
python -m tongyu_hardware.cli spray-mist
python -m tongyu_hardware.cli light-blue
```

真实发送：

```bash
python -m tongyu_hardware.cli spray-mist --execute
python -m tongyu_hardware.cli light-blue --real-send
```

## 6. 常用动作

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

投影：

```python
hw.projection.play(content_id="video_01_sound_wave_visual", slot=1, loop=True, execute=True)
hw.projection.stop(execute=True)
hw.projection.power("library_vertical", "on", real_send=True)
hw.projection.power("library_vertical", "off", real_send=True)
```

音响：

```python
hw.speaker.play(content_id="audio_01_music_cocktail_loop", slot=1, volume=0.62, loop=True, execute=True)
hw.speaker.stop(execute=True)
```

G1 基础测试链：

```python
hw.g1.basic_test(execute=False)  # 只生成命令链
hw.g1.basic_test(execute=True)   # 发送给中控/G1 桥接
```

## 7. 主要参数

```text
execute=False: 只生成命令，不执行喷雾/投影/音响/G1
execute=True: 发给中控执行
real_send=False: LAN 类命令 dry-run，不发真实 payload
real_send=True: LAN 类命令真实发送
duration_sec: 喷雾持续秒数
intensity: 喷雾强度，建议 0.0-1.0
content_id: 音响/投影端维护的内容编号
slot: 播放槽位，可选
loop: 是否循环播放
volume: 音量，建议 0.0-1.0
```

## 8. 返回值

单条命令常见返回：

```text
status: prepared / sent
command: 中控生成的 DeviceCommand
dispatch_result: 派发结果
direct_ack_record: 即时 ACK，可能为 null
```

动作链常见返回：

```text
status: prepared / sent
selected_actions: 选中的注册动作
commands: DeviceCommand 列表
dispatch_results: 每条命令的派发结果
chain: 可读执行链摘要
missing_ids: 未识别动作 ID
```

重点判断：

```text
prepared: 只生成命令，未执行硬件
sent: 请求已发给中控
dispatch_result.status = ok: 中控派发成功
dispatch_result.status = failed: 派发失败，看 error
payload_sent = true: LAN payload 已真实发出
payload_sent = false: 仍是 dry-run
```

## 9. 调试原则

1. 先测网络：`ping`、`curl` 或 `Invoke-RestMethod`。
2. 先预览：`execute=False` 或 `real_send=False`。
3. 再小参数真机测试，例如喷雾 `duration_sec=5`。
4. 一次只测一个设备、一个动作。
5. 失败时保存完整返回 JSON，优先看 `dispatch_result.error`。
6. 不要绕过中控直连硬件 IP；中控需要记录轨迹、ACK 和安全状态。

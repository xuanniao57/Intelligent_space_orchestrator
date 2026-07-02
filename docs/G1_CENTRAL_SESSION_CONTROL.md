# G1 中控 Session 控制方案（已废弃）

> 2026-06-29 更新：老板确认现场局域网内不会有其他设备竞争 G1 控制，本方案不再作为主路径。当前主路径是“中控维护 G1 官方动作表，并由中控主机直接调用 Unitree SDK”。见 `docs/HARDWARE_PYTHON_SDK.md` 的 G1 官方动作表章节。

目标：同学尽量保留原本 Unitree Python 控制代码；中控只负责安全租约、并发控制、超时回收和审计。

重要边界：如果中控主机没有安装 Unitree SDK，中控不会替同学执行机器人 SDK 调用。此时中控提供的是“真实控制前的授权租约”。真正的动作仍由同学本机的 Unitree SDK 执行。

## 1. 网络边界

G1 机器人侧可以配置防火墙：机器人控制端口只接受中控主机 `192.168.1.50`。

Ubuntu 上先查真实监听端口：

```bash
sudo ss -lntup
```

再按实际端口执行：

```bash
sudo bash scripts/linux/g1_allow_only_central.sh 192.168.1.50 <control_port_1> <control_port_2>
```

注意：不要把 SSH 锁死。脚本会保留 OpenSSH 入站。

## 2. Session 语义

同学主动向中控申请 G1 session：

```text
POST http://192.168.1.50:8798/api/g1/sessions
```

默认：

```json
{
  "dry_run": true
}
```

这只测试自己的电脑能否访问中控、能否拿到租约，不占真实机器人控制槽。

真实控制必须显式：

```json
{
  "owner": "your_name",
  "purpose": "demo_action",
  "dry_run": false,
  "real_control": true
}
```

中控默认只允许一个 `real_control=true` 的活跃 session。空闲超过默认 90 秒会自动释放。

其中：

- `dry_run=true`：只测自己的电脑能否访问中控，不占真实控制槽。
- `real_control=true`：申请真实控制槽，默认 20 秒没有 heartbeat 就释放。
- 正常退出 Python `with` 块会主动释放 session。
- 如果同学手动结束/杀掉自己的 Python 进程，heartbeat 会停止，中控会按空闲超时自动释放 session。

## 3. Python 用法

```python
from tongyu_hardware import g1_control_session

# 只测通不通
with g1_control_session(owner="your_name", purpose="connectivity_check"):
    print("session ok")

# 真实控制
with g1_control_session(owner="your_name", purpose="demo_action", dry_run=False, real_control=True):
    # 原来的 Unitree SDK 代码尽量不变
    # robot.wave()
    # robot.move(...)
    pass
```

上下文管理器会自动 heartbeat，退出时释放 session。

如果进程被强制杀掉，`__exit__` 不会执行，但中控会因为收不到 heartbeat 自动过期释放。默认真实控制超时是 20 秒，可按现场需要调整环境变量：

```text
TONGYU_G1_REAL_CONTROL_IDLE_TIMEOUT_SEC=20
TONGYU_G1_SESSION_MAX_ACTIVE=1
```

## 4. 中控如何真正成为“桥”

有两种可选落地方式：

1. 中控主机安装 Unitree SDK，中控直接执行 G1 动作。
2. 中控不安装 SDK，只做授权和网络代理。同学本机仍用 Unitree SDK，但连接目标改到中控代理端口，中控再转发到 G1。

如果 G1 防火墙只允许 `192.168.1.50` 访问控制端口，则同学电脑不能再直接连 G1。要尽量不改代码，就需要使用第 2 种网络代理：中控给 session 分配代理端口，同学 SDK 连接这个代理端口。

当前已实现的是 session 租约、dry-run、real-control 并发和超时回收。代理端口需要等确认 Unitree SDK 实际控制端口后再挂接。

## 5. 中控职责

中控尽量少介入用户动作细节，只负责：

- 控制同一时间有几个真实 G1 控制 session。
- 记录 owner、purpose、client_ip、创建/心跳/释放时间。
- dry-run 与真实控制分离。
- session 长时间无消息后自动释放。
- 后续如果启用中控 TCP proxy，则 session 释放时同步回收 proxy worker。

## 6. 调试命令

```bash
python -m tongyu_hardware.cli g1-session-dryrun --owner your_name
python -m tongyu_hardware.cli g1-session-real --owner your_name
```

查看中控当前 session：

```bash
curl http://192.168.1.50:8798/api/g1/sessions
```

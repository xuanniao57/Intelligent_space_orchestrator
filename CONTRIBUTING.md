# 贡献指南

感谢参与智场同语中枢 Agent。这个项目连接 Agent runtime、前端监控、设备协议和真实空间执行链，贡献流程需要比普通脚本仓库更稳一点：所有正式变更都通过分支和 Pull Request 审核后合并到 `main`。

## 基本原则

- `main` 只保存可以安装、启动、演示的稳定版本，不直接推送实验代码。
- 一次 Pull Request 只解决一个问题，尽量保持小而清楚。
- 变更接口、设备命令、语义注册表、现场执行逻辑时，必须同步更新相关文档或示例。
- 不提交 `.env`、密钥、真实现场隐私数据、运行日志、大体积录屏或临时产物。
- `third_party/` 只用于受控同步上游快照，不把日常业务改动混在里面。

## 推荐协作流程

### 1. 拉取仓库并安装

```powershell
git clone https://github.com/xuanniao57/Intelligent_space_orchestrator.git
cd Intelligent_space_orchestrator
powershell -ExecutionPolicy Bypass -File .\scripts\setup.ps1
```

复制 `.env.example` 为 `.env`，按需填写模型供应商。没有模型 key 时，可以设置：

```env
TONGYU_AGENT_DISABLE_LLM=1
```

### 2. 从 `main` 创建自己的分支

```powershell
git checkout main
git pull origin main
git checkout -b feature/frontend-agent-console
```

推荐分支命名：

- `feature/<area>-<short-name>`：新增能力
- `fix/<area>-<short-name>`：修复缺陷
- `docs/<short-name>`：文档更新
- `chore/<short-name>`：依赖、脚本、清理类工作
- `experiment/<name>`：探索性工作，默认不直接合并到 `main`

常见 `area` 可用：`backend`、`frontend`、`io-registry`、`agent-runtime`、`fake-g1`、`docs`、`ops`。

### 3. 本地开发与验证

通用检查：

```powershell
python -m compileall central_hub scripts tools
```

本地启动：

```powershell
powershell -ExecutionPolicy Bypass -File .\start_hub_local.ps1 -Port 8798
```

健康检查：

```powershell
Invoke-RestMethod http://127.0.0.1:8798/api/health
Invoke-RestMethod http://127.0.0.1:8798/api/hermes/status
```

涉及 G1 或设备 ACK 的变更，优先用 Fake G1 验证：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start_fake_g1.ps1 -Port 8731 -HubUrl http://127.0.0.1:8798
Invoke-RestMethod http://127.0.0.1:8731/health
```

### 4. 提交代码

提交信息建议用清晰的中文或英文短句：

```powershell
git add .
git commit -m "docs: add contribution workflow"
git push origin feature/frontend-agent-console
```

不要把不相关格式化、临时调试、个人 IDE 配置混进同一个提交。

### 5. 创建 Pull Request

Pull Request 需要说明：

- 为什么改
- 改了什么
- 怎么验证
- 是否影响接口、设备协议、语义注册表、前端展示或部署方式
- 是否包含真实设备风险、密钥风险、隐私数据风险

PR 创建后，等待维护者或对应模块审核者审核。除紧急修复外，不自审自合。

### 6. 标注贡献版本号

每次上传分支或提交 PR 时，请在 PR 标题、提交说明或变更描述里写明贡献版本号：

```text
contrib-v<目标项目版本>-<YYYYMMDD>-<GitHub用户名或姓名拼音>-<两位序号>
```

例如：

```text
contrib-v0.4.1-20260629-zhangsan-01
```

贡献版本号用于追踪每次上传记录；正式项目版本和 Git tag 由维护者统一发布。

## 需要重点审核的变更

下列变更需要至少 2 位维护者或模块审核者确认：

- `central_hub/backend/server.py`、Agent runtime、设备路由和 ACK 闭环。
- `central_hub/data/agent_io_registry/` 下的输入语义、输出工具、设备能力注册。
- 真实机器人、喷雾、音响、投影等现场执行逻辑。
- 接口规范、消息 schema、端口分配、部署方式。
- `third_party/` 上游快照同步或大规模替换。

文档、小型前端样式、示例数据等低风险变更，通常 1 位维护者审核即可。

## 文档同步要求

- API、消息字段或设备命令改变：更新 `INTERFACE_SPEC.md`。
- 信息流、语义到动作链路改变：更新 `INFORMATION_FLOW.md`。
- 启动、部署、端口或运维改变：更新 `README.md`、`OPERATIONS_RUNBOOK.md` 或 `PORT_ALLOCATION.md`。
- 新增输入语义或输出工具：更新 `central_hub/data/agent_io_registry/` 下对应注册表和示例说明。

## 安全与凭据

- 只提交 `.env.example` 这类模板，不提交真实 `.env`。
- 不在 issue、PR、日志、截图中暴露 API key、设备 token、内网地址凭据。
- 真实现场数据需要脱敏；无法脱敏时只在私下渠道给维护者说明，不放进仓库。
- 发现安全问题时不要公开贴可复现攻击细节，先联系仓库所有者或维护者。

## 合并规则

- 所有正式变更通过 PR 合并到 `main`。
- `main` 建议启用分支保护：需要 PR、需要审核、禁止强推、禁止删除。
- 合并方式推荐 Squash merge 或 Rebase merge，保持主线历史清楚。
- 影响现场设备或演示稳定性的变更，合并前需要附上验证记录。

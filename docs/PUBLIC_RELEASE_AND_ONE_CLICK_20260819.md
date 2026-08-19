# Minos Bench 公开仓库与一键启动说明

## 1. 当前结论

Minos Bench 已从“只能由开发会话操作”推进到“陌生 Windows 用户可以双击启动并在页面内配置模型”的公共开源版本。仓库地址为 `https://github.com/IIMovoMII/minos-bench`，可见性为 public，采用 MIT License。Scientific v2 的题集、评分和最终结果没有重跑或改写；公开发布阶段真实 Provider 请求为 0。

公开仓库内的 GitHub 复查证据见 `docs/GITHUB_REFERENCE_AUDIT_20260819.md`。结论是保留 DeepEval + LiteLLM + Streamlit 轻量架构，借鉴 Promptfoo 的“配置—运行—查看”和 Inspect AI 的日志查看边界，不引入 Opik 的 Docker/数据库全家桶。

## 2. 一键启动路径

Windows 用户双击项目根目录的 `启动评测工作台.cmd`：

1. 检查 `pyproject.toml`、`uv.lock` 和 `app.py`；
2. 优先使用系统已有 `uv`；若没有，明确询问后才在项目 `.bootstrap/` 内安装，不修改全局 Python；
3. 只在 `.venv` 缺失或 `uv.lock` 变化时按锁文件同步环境；
4. 尝试把仓库外的 Windows DPAPI profile 载入当前 Streamlit 进程；profile 损坏时不阻断 UI，而是提示到“模型配置”页修复；
5. 只绑定 `127.0.0.1` 并打开本机 Streamlit 工作台。

手动启动仍可用：

```powershell
cd minos-bench
uv sync --frozen --no-editable --link-mode copy
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\start_ui.ps1
```

## 3. 页面内模型配置

“模型配置”页支持用户要求的五类参数：

- 实际模型 ID；
- 接口协议 / LiteLLM adapter；
- Base URL；
- API Key；
- 思考强度。

协议不是含糊的“Chat 或 Responses”开关：

- `OpenAI-compatible Responses`：应用层调用 `/responses`，通常填写以 `/v1` 结尾的 Base URL；
- `Anthropic Messages（经 LiteLLM）`：项目仍调用 LiteLLM Responses 接口，由 LiteLLM 转成 `/v1/messages`；
- `其他 LiteLLM provider`：允许输入 provider 前缀，但是否兼容需由对应 Provider 合同验证；
- Chat Completions 继续禁用。

页面提供两种配置方式：

- **快速体验**：填写一个被测模型和一个 Judge；被测模型复制到 `model_a`、`model_b`、`weak_model`。这能跑通工作流，但三个目标槽位相同，不能据此做模型比较。
- **完整四槽**：分别填写候选模型一、候选模型二、弱基线和 Judge，用于正式的四配置比较。

首次配置必须填写 Key；以后 Key 或 URL 留空表示保留现有加密值，也可勾选清除自定义 URL。保存动作本身不联网。连接测试和真实运行仍是独立按钮，并保留显式确认门禁。

## 4. 凭据与数据边界

- Windows 下 Key 与完整 Base URL 继续使用当前 Windows 用户 DPAPI 加密，profile 位于仓库外；模型 ID、adapter、Responses 模式和思考强度可审计。
- UI 不预填或回显 Key/URL；提交时通过标准输入交给本地 PowerShell helper，不放进命令行参数。
- 保存成功后只把值放入当前单用户 Streamlit 进程。该设计不适合公网多租户托管；当前明确只支持本机回环地址。
- macOS/Linux 可以使用会话级页面配置或环境变量示例，但本轮没有声称提供跨平台加密持久化。
- 离线数据查看、Schema 校验、确定性检查和历史报告查看不要求任何 Key。

## 5. GitHub 候选文件边界

本地目录实测 528.40 MiB，其中 `.venv` 为 516.05 MiB、全部运行工件为 8.29 MiB；这些体积不等于 Git 仓库体积。使用当前 `.gitignore` 在临时 Git 索引中审计，公开候选为 145 个文件、2.11 MiB。

公开候选包含：

- `src/`、`tests/`、`scripts/`、`configs/`、冻结题集与来源台账；
- `uv.lock`、`.env.example`、Streamlit 主题配置和启动入口；
- 产品权威、当前状态、题集说明和公开发布文档；
- 一份经过身份/凭据关键词检查的 Scientific v2 机器最终报告。

默认排除：

- `.venv/`、`.bootstrap/`、测试/格式化/浏览器/DeepEval 缓存；
- `.env*`（仅保留 `.env.example`）和 `.streamlit/secrets.toml`；
- 所有原始逐题执行、恢复中间态、连接诊断、临时日志和本地人工 review；
- 只有 `artifacts/scientific_v2/executions/scientific-v2-20260804-a-recovery-4/machine_final_report.json` 进入精确允许列表。

这份最终报告 SHA-256 为 `908D51899324F1C286F42A9EADF988D28EE2E058FA827F4645D5F38FFC91A4D0`；它不含实际模型名、Key、Base URL 或 Provider 身份。报告边界见 `artifacts/README.md`。

## 6. 本轮验收

本轮没有启动真实模型，也没有运行昂贵全量验收，只做与变更直接相关的定向检查：

- 6 项 profile bridge 测试通过，包括测试 Key/URL 的 DPAPI 往返、修改与明文落盘检查；
- 3 项入口/UI 定向测试通过，包括七页 Streamlit 冒烟、Windows PowerShell 5.1 解析和 `PYTHONPATH` 入口合同；
- changed-file Ruff 与 Python compileall 通过；
- Streamlit 实际锁定版本为 1.60.0；
- 真实 Provider 请求为 0。

## 7. 发布状态与后续可选项

已完成的发布事项：

1. **许可证**：仓库采用 MIT License。
2. **正式 Git 历史**：项目已建立独立 Git 历史并形成首次公开提交。
3. **远端发布**：`IIMovoMII/minos-bench` 已按 public 可见性发布。

仍属于后续可选项或明确边界：

1. **持续集成**：可以补充 Windows 离线 CI，但首次发布没有额外引入 GitHub Action 供应链依赖。
2. **跨平台持久化**：目前只有 Windows DPAPI 是已实现、已测试的加密持久化；不能写成全平台一键密钥托管。
3. **公网部署**：当前只支持本机单用户使用；公网多租户所需的认证、密钥管理和权限隔离尚未实现。

## 8. 后续优化优先级

公开版本仍优先保持轻量、本地和可复核。后续可按需要增加离线 CI；不要为了展示效果直接增加 Docker、公网部署、数据库或生产可观测平台，它们会扩大密钥和多租户风险，也不属于当前 POC 的已验收范围。

## 9. 2026-08-20 发布后安全复核

- README 已改为面向开源使用者的中文首页，“当前状态”和“真实性与分工”不再出现在 README；版本史、失败审计和边界证据继续由本文件及项目状态文档承载。
- 本地独立仓库与 GitHub `main` 均包含 152 个文件，路径集合完全一致；仓库根目录就是 Project 3，没有 Project 1/2、求职工作区文档或个人简历进入远端。
- 仓库自带暂存审计、完整 Git 索引审计、全部历史高置信凭据特征检查和 GitHub Secret Scanning 均未发现凭据；Push Protection 保持启用，开放 Secret Scanning 告警为 0。
- GitHub 首次复核发现锁文件中 GitPython 3.1.57 与 pytest 8.4.2 对应 7 条 Dependabot 告警。现已分别升级到 3.1.59 与 9.1.1；120 项离线测试通过，GitHub 重新计算后的开放 Dependabot 告警为 0。
- README 提交为 `2eaf075`，依赖安全修复提交为 `f9b7df0`。本次复核没有运行真实 Provider 请求，也没有把本机 profile、Key 或完整 Base URL 加入 Git。

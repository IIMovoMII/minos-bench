# Minos Bench：大模型质量评测工作台

[![许可证：MIT](https://img.shields.io/badge/%E8%AE%B8%E5%8F%AF%E8%AF%81-MIT-2ea44f)](LICENSE)
[![Python：3.11–3.13](https://img.shields.io/badge/Python-3.11%E2%80%933.13-3776ab)](pyproject.toml)

**Minos Bench（米诺斯审判台）**是一个本地优先、BYOK、可复现的通用 LLM 应用质量评测工作台 POC。名字取自希腊神话中的冥界审判者米诺斯：每份模型回答都要经过证据核验、原子 Rubric、语义评审、Bad Case 归因与发布门禁，而不是只得到一个无法解释的总分。

> **凭据安全：**仓库不保存任何真实 API Key 或完整 Base URL。Windows 持久化使用当前用户 DPAPI，配置文件位于仓库外；UI 不回显凭据，Git 默认排除本地配置、密钥文件、日志和原始运行工件。提交安全问题前请先阅读 [`SECURITY.md`](SECURITY.md)。

公开提交前可运行脱敏审计；脚本只报告规则名、文件路径和行号，不显示命中的原文：

```powershell
git add -A
uv run --no-sync python .\scripts\audit_public_commit.py
```

当前产品与实现权威依次是：

1. `PROJECT_SPEC.md`
2. `docs/SCIENTIFIC_EVALUATION_IMPLEMENTATION_PLAN_V3_APPROVED.md`
3. `docs/PROJECT3_CURRENT_STATUS_20260802.md`
4. `docs/EXECUTION_HANDOFF_V1_20260802.md`
5. `docs/PUBLIC_RELEASE_AND_ONE_CLICK_20260819.md`（公开仓库与启动边界）

## 当前状态

截至 2026-08-04，活动协议为 `scientific-v2.0`。24 道全新正式题、来源台账、gold/反例、直接检查边界、有限执行图和匿名报告链路已冻结，V2 匿名有限矩阵及机器最终报告已经完成。健康检查仍只验证“LiteLLM 请求能得到任意非空响应”，不验证 Judge JSON、评分质量或模型能力：

- V2 正式集为 24 题，四类任务各 6 题；12 个风险格各含一个 D2 边界场景和一个 D3 困难场景。完整题面见 `docs/FORMAL_BENCHMARK_BACKED_QUESTION_SET_V2.md`。
- 活动计划固定为 4 次 Provider probe、96 次目标生成和 96 次单次 Judge，计划基数 196。本轮复用既有 Judge 引擎验收，不重复技术探针和固定体检调用。
- 空或不完整响应最多在当前目标节点重试一次；API/Provider 运行错误可由派生恢复只补错误节点。非空回答即使答错也不会重生成，合法 Judge PASS/FAIL 也不会重判。
- V2 manifest SHA-256 为 `3cd5c60f3aae6d57c2622409ad8b4946f66e80506da75a6c25e474247ee18efc`，seal SHA-256 为 `4c610a10c3f8667fbfafd9f343256efa9b1ac944b93209ddc4f3f5bf5da4387a`。
- 最终派生执行 `scientific-v2-20260804-a-recovery-4` 为 200/200 节点、96/96 目标输出、96/96 合法 Judge、0 运行错误；四个匿名配置参考总分为 87.92、82.43、85.83、85.21，且都因预登记严重错误标记为发布阻断。
- Judge 格式失败根因是自由文本理由中的双引号未转义，仅加强提示词仍会复现。当前 Anthropic adapter 使用原生 JSON Schema `output_format` 并保留 `reasoning_effort=max`，其他 Responses adapter 使用 Pydantic `text_format`；评分规则和已有判断未重写。

2026-08-20，项目以 **Minos Bench** 名称按 MIT License 公开发布。双击 `启动评测工作台.cmd` 可准备锁定环境、载入仓库外 DPAPI profile 并打开本机 UI；“模型配置”页支持模型 ID、协议、Base URL、Key 和思考强度，分为快速两模型体验与完整四槽配置。原始运行工件、本地环境和凭据默认不进 Git。完整发布与隔离边界见 `docs/PUBLIC_RELEASE_AND_ONE_CLICK_20260819.md`。

以下 Scientific v1 内容保留为历史工程与失败审计基线：

- 原有 40 条主数据、8 条 holdout、DeepEval G-Eval 路径和历史运行原样保留为工程与失败审计基线；旧 `scripts/run_full_pipeline.ps1` 继续在任何在线调用前硬停止。
- 新 `datasets/scientific_v1/` 已封印：38 个问题家族实例，其中 3 个规则开发锚点、2 个技术探针锚点、7 个 Judge 验证家族、25 个正式比较题、1 个明确标注的合成回归种子；Judge 验证另有 14 份候选人固定参考回答。
- 25 个正式题按四类任务分布为 6 / 7 / 5 / 7：指令生成、资料问答、多轮对话、结构化输出与工具调用。
- 新正式路径不使用多请求 DeepEval G-Eval。OpenAI-compatible 槽位走 `/responses`；Anthropic adapter 由 LiteLLM 转为原生 `/v1/messages`，项目只传标准 `reasoning_effort=max`，LiteLLM 自动生成 adaptive thinking 与 `output_config.effort=max`。每份答案只调用一次原子 Judge；Judge 看不到目标模型、配置或 Prompt 身份，也看不到严重程度。
- 判断权限固定为 `DIRECT_VERIFIER`、`SIGNAL_ONLY`、`SEMANTIC_REVIEW`、`HUMAN_REQUIRED`。弱关键词和长度信号不能直接判失败；本批次按候选人 2026-08-04 指令采用 Judge-only 终局，语义 Judge 必须严格依据预登记小项，严重错误单独阻断版本。该政策只适用于当前低风险固定题集。
- 新矩阵是显式编号、不可变、有限成功节点 DAG：100 次目标生成 + 100 次正式 Judge；加上 4 次 Provider probe、6 次技术路径请求和 14 次 Judge 体检，计划基数为 224 次。质量结果不会扩题、重生成或增加 Judge；超时、429 和普通 5xx 只重试当前请求，400/401/403/404/405/422 等 Provider 合同硬错误首次停止；中转正文明确表示“无可用模型通道”的 503 也第一次停止，避免把确定性路由缺失误作临时网络故障。Judge JSON 或字段合同错误只记录为运行错误并继续，不计内容 0 分。
- 离线完整假 Responses DAG、幂等重进、熔断、无限临时失败后成功、硬错误首次停止、成功探针收据复用、未知题号拒绝、双报告、匿名包、六页 Streamlit 和 PowerShell 入口均已测试。
- 2026-08-02 原离线验收为 84/84；2026-08-03 adapter-native、最小健康检查、Judge advisory 错误策略、状态命令与确定性路由熔断的完整测试为 94/94，Ruff、compileall、封印数据校验和 PowerShell 语法通过。基础证据见 `artifacts/scientific_v1/adapter_native_transport_offline_acceptance_20260803.json`，最新路由熔断证据见 `artifacts/scientific_v1/provider_route_guard_offline_acceptance_20260803.json`；此前 Claude `/responses`、Provider 强制 Schema 和跨字段归一化试验只保留作历史诊断。
- 随后唯一一次真实执行 `scientific-v1-20260802-a` 在第二目标逻辑槽位 probe 连续两次 HTTP 500 后按当时规则硬停止：共 3 次请求、2 个完成节点，尚未进入技术探针、Judge 体检或正式 100+100，也没有机器报告和匿名包；该历史执行没有被自动换编号或改写。
- 2026-08-03 经候选人授权，保持同一 URL、不同 Key 的现有配置及相同请求形状，对 Model B 逻辑槽位单独复查 1 次；仍返回 HTTP 500。已再次停止，证据为 `artifacts/scientific_v1/model_b_recheck_20260803.json`。
- Provider 500 的根因已定位为 adapter/协议路由冲突：Claude 逻辑槽位此前被送往中转站 OpenAI-compatible `/responses`；改为 Anthropic adapter 后，线上由 LiteLLM 转为根 Base URL 的 `/v1/messages`，并按中转合同临时注入 Bearer 鉴权。`scientific-v1.7` 进一步删除手工 Claude 思考字段，只向 LiteLLM 传 `reasoning_effort=max`；本地 HTTP 合同证明 LiteLLM 1.94.0 在线上生成 `thinking.type=adaptive + output_config.effort=max`。健康探针仍不发送思考或结构化参数；正式 Judge JSON 仍由提示词请求，本地解析失败只记运行错误并继续。当前协议 SHA-256 为 `5674a82c57055cc5ecf16b43b614703cc18c7f6d734a5b24b1851d9f05be4518`。
- 当前执行 `scientific-v1-20260803-v16-a` 已完成 50 个节点（含 Model A 25/25），随后在 Model B 首题因 503 空转而暂停。安全诊断确认 Model B 与 Judge 按设计共用同一 URL/Key，但认证模型目录中只有 Judge 的配置模型名存在，Model B 的配置模型名不存在；三种路由/鉴权形状均返回“无可用模型通道”。旧执行的 50 个节点已保留，替换模型必须新建执行，不能混入旧结果。
- 中转站确认原 Model B 模型通道已下架，候选人要求改用当前目录最新同系列 `claude-opus-4-8`。加密 profile 已只替换模型名；一次携带 `reasoning_effort=max` 的精准线上请求返回 `completed`、非空响应和 usage，兼容性阻塞解除。
- 原执行 `scientific-v1-20260803-v17-a` 已完成执行图但留下 10 个目标/Judge 缺口；这些运行错误没有计内容 0 分，原执行和失败证据保持不可变。
- 派生恢复执行 `scientific-v1-20260804-v17-recovery-a` 复用 213 个成功节点，只重跑 10 个缺口。最低需要 10 次请求，实际 12 次；多出的 2 次为正式 Judge 遇到 HTTP 502 后的当前节点重试。最终达到 227/227 节点、100/100 目标输出、100/100 Judge 结果和 14/14 Judge 固定体检。
- 机器最终报告已经生成。四个配置的参考总分为 93.73、90.24、90.04、90.16；每个配置都存在至少一个预登记严重错误，因此全部标记为存在发布阻断。分数只适用于当前 25 题、当前规则和当前单 Judge，不能解释为通用模型排名。

离线 fixture 和假 Provider 只证明数据合同、执行控制与报告链路有效，不是任何模型的质量结果。

## 产品范围

Scientific v1 只评估四类常见 LLM 应用任务：

- 按要求生成文本；
- 只依据给定资料回答；
- 保持多轮状态与约束；
- 生成结构化结果或正确使用工具。

主比较固定为 Model A + Prompt V1 对 Model B + Prompt V1；控制变量实验固定为同一较弱模型的 Prompt V1 对 Prompt V2。每个配置每题只生成一次，每份答案只评分一次，不测随机波动，不因质量差自动重生成、改题、扩题、增加 Judge 或创建下一轮。

首版不包含多模态、训练或微调、生产监控、真实业务流量加权、多租户和真实工具副作用。工具环境是本地模拟，不代表生产系统。

## 评测逻辑

```text
来源与许可证门禁
  → 分用途数据与 family leakage 检查
  → 确定性直接核验 / 弱信号
  → 单次原子 Judge 按预登记小项裁决
  → 运行错误与内容失败分离
  → 机器最终报告、版本比较与严重错误阻断
  → 可选匿名人工抽检与后续回归
```

每个语义小项只判断一个行为，预先登记适用条件、允许证据、通过/失败/弃权/不适用边界、正反例、严重程度和判断权限。评分为：满足 1、失败 0、弃权不进入得分但降低判断覆盖率、不适用排除；先按题汇总，再按任务包汇总，最后四个任务包等权。运行错误不会作为内容 0 分。

## 一键启动与首次配置

Windows 推荐直接双击：

```text
启动评测工作台.cmd
```

入口优先复用系统 `uv`；如果没有，会先询问是否在项目 `.bootstrap/` 内安装。它只在 `.venv` 缺失或 `uv.lock` 变化时同步依赖，然后载入仓库外的 Windows DPAPI profile，并把工作台绑定到 `127.0.0.1`。

首次进入“模型配置”页：

- 快速体验只填一个被测模型和一个 Judge，适合验证链路；三个目标槽位会相同，因此不能用于模型比较。
- 完整四槽分别配置候选模型一、候选模型二、弱基线和 Judge，才适合四配置比较。
- 协议可选 OpenAI-compatible Responses、Anthropic Messages（由 LiteLLM 转发）或其他 LiteLLM provider；Chat Completions 禁用。
- Key 与 Base URL 不回显，Windows 下由当前用户 DPAPI 加密保存到仓库外。保存配置不会联网。

手动准备和启动：

```powershell
cd minos-bench
uv sync --frozen --no-editable --link-mode copy
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\start_ui.ps1
```

跨平台可按 `.env.example` 设置进程环境后运行 Streamlit，但本轮只对 Windows DPAPI 持久化做了实现与验收，不声称全平台一键密钥托管。

## 离线验收

一键重建、校验封印、静态检查并运行完整测试：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\run_scientific_offline_acceptance.ps1
```

这个入口不加载本地模型 profile，不读取 Key，不进入真实 Provider 阶段。也可只验证数据：

```powershell
.\scripts\run_cli.ps1 scientific-validate
```

## 运行一次有限真实矩阵

真实运行使用已经存在的本机加密模型 profile。Key 与完整 URL 位于仓库外的 Windows 当前用户 DPAPI 密文中；运行时只解密到当前 PowerShell 进程，CLI 和工件不输出模型实际身份、Key 或完整 URL。

每次必须由操作者提供新的明确执行编号：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\run_scientific_v2.ps1 `
  -ExecutionId scientific-v2-YYYYMMDD-a
```

也可以双击 `启动科学版有限矩阵.cmd`。不要使用旧 `启动真实评测闭环.cmd` 或 `scripts/run_full_pipeline.ps1`；它们属于历史基线并保持硬停止。

旧执行均永久绑定各自协议，不能与 V2 混跑。每轮必须使用新的明确执行编号；同一执行编号重进只恢复未完成节点。

执行顺序固定为：离线门禁 → 4 个最小 Provider probe → 96 次正式目标生成 → 96 次单次 Judge → 机器报告与匿名包。健康探针只检查任意非空响应。空/不完整响应和 API 运行失败可恢复；质量失败不触发重试；Provider 硬错误和确定性“无可用模型通道”错误保留为运行错误或按熔断规则停止。

原执行 `scientific-v2-20260804-a` 保存了 96/96 个目标输出和 96 项匿名包；经过四次追加式派生恢复，最终执行 `scientific-v2-20260804-a-recovery-4` 已达到 96/96 合法 Judge。每轮只补运行错误，全部目标输出和已有合法判断均以零请求复用。

查看安全状态摘要：

```powershell
.\scripts\run_cli.ps1 scientific-status --execution-id <execution_id>
```

## 恢复失败节点并生成机器最终报告

当前 V2 已完成；以下命令只用于未来新执行出现 API/空输出等运行缺口时的追加式恢复。脚本加载本机加密 profile，但不会输出实际模型身份、Key 或完整 URL：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\run_scientific_recovery.ps1 `
  -SourceExecutionId scientific-v2-YYYYMMDD-a `
  -RecoveryExecutionId scientific-v2-YYYYMMDD-a-recovery-1
```

恢复执行不会覆盖源执行。已完成节点以零新请求复用，只有运行错误或缺失节点会进入重跑清单；合法 PASS/FAIL 不会二次评分。

机器最终报告位于：

```text
artifacts/scientific_v2/executions/
  <最终完成执行编号>/machine_final_report.json
```

## 机器结果与可选人工抽检

启动界面推荐双击 `启动评测工作台.cmd`，也可手动运行：

```powershell
.\scripts\start_ui.ps1
```

在第七页“可选人工抽检”中选择“本次补跑完成评测｜2026-08-04”。页面先展示机器最终结果、四类任务分数、错误等级和逐题比较；下方匿名抽检区仍隐藏模型、Prompt 和 Judge 结论。抽检记录只追加、不覆盖机器最终报告，也不影响当前 Judge-only 结论。

评分方式为：每个适用判断点 PASS=1、FAIL=0；ABSTAIN 不进分但降低判断覆盖率，不适用项排除。先计算单题，再在任务包内平均，最后对指令生成、资料问答、多轮对话、结构化与工具调用四类任务等权平均。运行错误永远不计内容 0 分，严重错误另行阻断发布。

## 数据何时离开本机

- 数据校验、封印、计划生成、状态查看、确定性核验、报告计算和人工复核均在本机完成。
- 真实目标生成会向对应目标 Provider 发送该题输入、资料、对话和工具定义。
- 原子 Judge 会收到题目证据、匿名候选回答和已登记语义小项，但不会收到目标模型名、配置 ID、Prompt ID 或严重程度。
- OpenAI-compatible 在线请求 `/responses`；Anthropic adapter 由 LiteLLM 以原生 max 映射在线请求 `/v1/messages`；`store=false`、`stream=false`、LiteLLM 内部自动重试为 0。
- 工件不保存 Key、请求头、完整 Base URL或实际模型 ID；错误只保存类型、分类和安全 HTTP 状态。

## 关键文件

- `datasets/scientific_v2/source_ledger.jsonl`：逐题来源、风险格、难度与用途台账
- `datasets/scientific_v2/manifest.json`、`seal.json`：内容哈希与封印
- `configs/scientific_v2.json`：冻结四配置、196 次计划与重试合同
- `src/llm_eval_workbench/atomic_judge.py`：单次原子 Judge
- `src/llm_eval_workbench/scientific_executor.py`：有限、可恢复执行器
- `src/llm_eval_workbench/scientific_recovery.py`：派生恢复执行与成功节点复用
- `src/llm_eval_workbench/scientific_report.py`：机器最终报告、可选人工报告与匿名包
- `src/llm_eval_workbench/profile_bridge.py`：UI 配置与仓库外 DPAPI profile 的安全桥接
- `scripts/start_ui.ps1`：锁文件环境、加密 profile 载入与本机 UI 一键入口
- `scripts/save_model_profile_from_stdin.ps1`：从标准输入保存配置，不把 Key/URL 放进命令参数
- `scripts/audit_public_commit.py`：只针对 Git 暂存区执行脱敏凭据与公开边界检查
- `scripts/run_scientific_recovery.ps1`：只补跑失败节点的安全入口
- `docs/FORMAL_BENCHMARK_BACKED_QUESTION_SET_V2.md`：当前 24 道正式题、来源、gold、反例与检查边界
- `docs/SCIENTIFIC_EVALUATION_IMPLEMENTATION_PLAN_V3_APPROVED.md`：当前产品实施权威
- `docs/GITHUB_REFERENCE_AUDIT_20260819.md`：公开仓库内可读的 GitHub 参照项目采用与取舍审计
- `docs/PUBLIC_RELEASE_AND_ONE_CLICK_20260819.md`：GitHub 候选范围、一键启动、安全边界与未决项
- `artifacts/README.md`：公开身份盲报告的精确允许列表与解释边界
- `SECURITY.md`：凭据隔离、安全报告与误提交处置方式
- `LICENSE`：MIT License

## 真实性与分工

这是个人 POC，使用公开资料和合成数据，不是企业生产系统。题型方法参考公开基准，但除明确登记的许可证允许改编外，不把自建题包装成官方原题，也不声称跑过官方完整 benchmark。

候选人负责产品方向、Judge-only 政策选择、真实坏案例解释和无稿演示；Codex/AI 辅助完成研究、数据整理、代码、测试、恢复执行和自动化。不得声称使用真实企业数据、管理真实标注团队、上线生产、自研 LiteLLM/DeepEval，或引用没有可复核工件支持的模型分数、一致率、效率与 ROI。

## 开源许可

本项目采用 [MIT License](LICENSE)。公开题集中的外部方法来源与改编边界以逐题来源台账和 `docs/GITHUB_REFERENCE_AUDIT_20260819.md` 为准；MIT License 不会自动改变第三方依赖或引用资料各自的许可证。

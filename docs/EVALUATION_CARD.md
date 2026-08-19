# Scientific v1 Evaluation Card

## 1. 评测目标

本项目评估四个冻结 LLM 应用配置在指令生成、资料问答、多轮对话、结构化输出与工具调用上的行为，并回答：

- 哪些可直接验证的合同满足或失败；
- 哪些语义行为由 Judge 找到支持证据或需要人工复核；
- 两个同 Prompt 模型与同模型两个 Prompt 在同题上修复、退步、持平或不可比较；
- 失败来自内容、Judge 合同、Provider 运行还是本地实现。

它不是基础模型综合 benchmark，不用于训练，不代表生产发布评审。

## 2. 冻结四配置

| 配置 | 控制变量解释 |
|---|---|
| `model_a_prompt_v1` | 主比较基线 |
| `model_b_prompt_v1` | 只改变目标模型 |
| `weak_prompt_v1` | Prompt 实验基线 |
| `weak_prompt_v2` | 只改变较弱模型所用 Prompt |

每配置每题只生成一次，每份答案只经一次正式原子 Judge。首版不重复测随机波动，不增加第二 Judge，不因质量失败重生成或新建下一轮。Provider 的可恢复传输失败重试同一个请求，不产生新的题目、答案版本或质量样本。

## 3. 判断权限

- `DIRECT_VERIFIER`：完整且与业务合同等价的代码核验，可形成机械失败。
- `SIGNAL_ONLY`：关键词、长度等风险提示，只能进入复核。
- `SEMANTIC_REVIEW`：Judge 对一个预登记行为整理证据，失败不直接决定版本。
- `HUMAN_REQUIRED`：冲突、高风险与最终参考判断由候选人确认。

规则上的 `hard` 标签不存在，也不能越过判断权限。直接核验只读取可机械证明的结构、计数、Schema、工具调用或模拟环境状态。

## 4. 单次原子 Judge

Scientific v1 的正式路径不使用 DeepEval G-Eval。每份答案通过统一 LiteLLM Responses 界面向固定 Judge 发出一次逻辑请求；Anthropic adapter 在线上转换为原生 `/v1/messages`，返回每个已登记小项的：

- 适用或不适用；
- 证据充分或不足；
- PASS、FAIL 或 ABSTAIN；
- 回答证据、来源证据与单项理由。

Judge 不能新增、合并、改名或遗漏小项，不能输出严重程度、分数、置信度或发布建议。目标模型、配置和 Prompt 身份不进入 Judge payload。JSON、准则集合或响应完整性错误属于运行/合同错误，不是内容 0 分。

当前 `scientific-v1.7` 由提示词请求 JSON，并在本地用 Pydantic 解析；不再发送 Provider 强制 Schema，也不自动归一化模型返回的跨字段组合。解析或字段合同错误保留为 `RUNTIME_ERROR`，不计内容 0 分、不补问第二次、不自动改成 PASS/FAIL，并继续执行其余矩阵。缺失判断会降低 Judge 完成/判断覆盖率，等待人工复核。

14 份固定参考回答覆盖严重程度错位、误报、证据不足却过度确定、有证据却逃避弃权、引用错配、旧版本、参考路径偏见和环境状态错配。该一致性只作补充诊断，不设“必须 100%”的质量门禁；合同错误如实降低覆盖率，内容分歧和缺失判断进入人工复核。

## 5. 分数与覆盖率

- 满足 = 1，失败 = 0；
- ABSTAIN 不计入得分，但降低判断覆盖率；
- NOT_APPLICABLE 排除；
- 运行错误不计为内容 0 分；
- 每题先对已判断适用小项取平均；
- 同任务包再对题目取平均；
- 四个任务包等权平均并换算为 0—100。

报告并列显示完成率、判断覆盖率、人工覆盖率、严重/重要/一般错误和逐题修复/退步/持平/不可比较。总分不能抵消候选人确认的严重错误。

## 6. 有限执行合同

固定顺序为：离线门禁 → 4 次 Provider probe → 6 次技术路径请求 → 14 次 Judge 体检 → 100 次目标生成 → 100 次正式 Judge → 报告与匿名包。

```text
计划成功请求：224 requests
质量触发额外请求：0
可恢复传输失败：只重试当前请求直至成功
成功健康探针：使用收据，不重复请求
```

400/401/403/404/405/422、鉴权、参数不支持等硬错误首次即停；超时、429 和普通 5xx 重试当前请求，正文明确表示“无可用模型通道”的 503 第一次停止。质量失败从不触发重试、扩题、第二 Judge 或下一轮。因此成功节点图有限；真正的临时网络失败尝试仍无绝对次数上限，确定性路由缺失不会无限空转。

## 7. 离线验收结果

2026-08-02：

```text
84 / 84 tests passed
Ruff: passed
compileall: passed
Streamlit six-page smoke: passed
PowerShell parse: passed
sealed dataset audit: passed
fake Responses 224-request DAG: passed
real Provider requests: 0
```

证据：`artifacts/scientific_v1/offline_acceptance_20260802.json`。这些结果验证工程合同，不是模型效果。

2026-08-03 当前 `scientific-v1.7` 将 OpenAI-compatible 槽位保留在 `/responses`，Anthropic adapter 由 LiteLLM 转为原生 `/v1/messages`。项目向 Claude 分支只传标准 `reasoning_effort=max`，LiteLLM 自动生成 `thinking.type=adaptive + output_config.effort=max`；不再手工拼 Claude 字段。Bearer 鉴权上下文、最小非空响应健康检查、Judge advisory 解析错误、失败重试与确定性路由熔断保持不变。当前 Ruff、compileall 与 94/94 测试通过；证据为 `artifacts/scientific_v1/anthropic_effort_transport_offline_acceptance_20260803.json` 和 `artifacts/scientific_v1/provider_route_guard_offline_acceptance_20260803.json`。

## 8. 人工确认

首次真实执行 `scientific-v1-20260802-a` 在第二目标逻辑槽位 probe 连续两次 HTTP 500 后按冻结规则停止：总请求 3、完成节点 2，未进入技术探针、Judge 体检或正式 100+100。因此当前没有机器质量报告、匿名包、真实比较分数或 Judge 一致性结果；该失败只验证了错误分类、唯一重试和硬停止机制。

2026-08-03 后续证据确认根因是 Claude 槽位的 adapter/协议路由冲突，而不只是思考字段。改为 Anthropic adapter、原生 `/v1/messages` 和 Bearer 鉴权后，四个逻辑槽位均已有成功非空响应收据。收据不含实际模型身份或凭据，只证明 API 连接可用，不证明 Judge 合同或模型质量。

真实矩阵完成后生成 100 项匿名复核包。候选人只看题目、证据、匿名回答和预登记规则，不看目标身份、Prompt 身份或 Judge 结果；每个语义小项必须提交判断与理由，记录只追加。

全部匿名项完成前，代码拒绝生成候选人确认报告。完成后才解盲、处理争议、形成版本建议，并把候选人确认的真实坏案例写入后续回归版本。

## 9. 结果有效性边界

- 每配置每题只有一次生成和一次 Judge，未测波动。
- 数据以公开与合成为主，不代表真实流量。
- 一名候选人的判断不是专家金标准。
- 模拟工具不代表真实系统和副作用。
- Provider 可能更新同名模型；工件结论只适用于冻结数据、配置与当次运行。
- 旧 Chat/DeepEval 历史工件只作失败审计，不能与新 Responses 结果直接比较。
- 在新的真实矩阵和候选人盲审完成前，不存在可发布的模型排名、Prompt 提升幅度或 Judge 准确率。

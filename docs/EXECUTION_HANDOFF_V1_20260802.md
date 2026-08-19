# Project 3 执行窗口任务书 v1（题目方案批准后）

状态：可交给实现窗口执行  
日期：2026-08-02  
目标：完成除候选人本人盲审、争议裁决和无稿掌握外的全部工程工作；遇到本文定义的硬阻塞才停止  

> **2026-08-03 当前执行补充（覆盖本文较早规则）：**离线实现已经完成，活动协议为 `scientific-v1.7`。OpenAI-compatible 槽位走 `/responses`；Claude 槽位由 LiteLLM 原生映射 `reasoning_effort` 并发往 `/v1/messages`。Provider 健康检查只发送 `ping`，输出上限 32，不带思考或结构化参数；任意非空响应即成功。Judge JSON/字段解析失败只记 advisory `RUNTIME_ERROR` 并继续，不计内容 0 分，不补问或自动改写。超时、429 和普通 5xx 只重试当前请求；正文明确表示“无可用模型通道”的 503 第一次停止。旧 v1.6 执行不得与 v1.7 混跑。当前事实与 hash 以 `PROJECT3_CURRENT_STATUS_20260802.md` 为准。

## 0. 开始前必须读取

按顺序读取：

1. `README.md`
2. `PROJECT_SPEC.md`
3. `docs/PROJECT3_CURRENT_STATUS_20260802.md`
4. `docs/SCIENTIFIC_EVALUATION_IMPLEMENTATION_PLAN_V3_APPROVED.md`
5. `docs/GITHUB_REFERENCE_AUDIT_20260819.md`
6. `docs/FORMAL_BENCHMARK_BACKED_QUESTION_SET_V1.md`

不要读取、输出或记录 API Key、Token、Cookie、完整凭据 URL。只核验加密模型 profile 是否存在；运行时让现有代码按槽位取用，不打印值。

## 1. 当前批准事实

- 5 个官方锚点、25 个正式比较题和 7 个评分模型体检家族的内容方向已获候选人批准。
- 题目批准不等于工程数据已冻结；必须先完成结构化转换、来源校验和离线验收，再产生数据版本/hash。
- 正式比较固定四个配置：Model A + Prompt V1、Model B + Prompt V1、weaker model + Prompt V1、weaker model + Prompt V2。
- 每配置每题只生成一次，每份回答只进行一次结构化 Judge 请求；不做重复波动实验。
- 不默认增加第二 Judge，不因质量差自动重生成、改题、扩题或启动下一轮。
- 旧 `run_full_pipeline.ps1` 继续硬停止，直到新执行器本地验收完成；不得恢复旧矩阵。

## 2. 执行顺序

### 阶段 A：基线与影响面审计

1. 只读检查工作树、现有数据 schema、指标实现、运行 DAG、CLI、Streamlit、报告和测试。
2. 先运行当前离线基线测试，记录真实结果；若与权威记录的 `58 passed` 不同，先定位差异，不能直接覆盖。
3. 明确新旧文件映射和迁移方案；保留旧 40/8、历史运行和旧方案作为可审计基线，不拿旧结果冒充新结果。
4. 生成一份简短实现影响清单，随后直接继续，不因普通实现选择请求用户确认。

### 阶段 B：把审核稿转换成版本化数据

建立新的数据版本目录，不原地改写旧 `datasets/development` 和 `datasets/holdout`。建议结构：

```text
datasets/scientific_v1/
  source_ledger.jsonl
  rule_development.jsonl
  technical_probes.jsonl
  judge_validation_cases.jsonl
  judge_validation_responses.jsonl
  target_comparison.jsonl
  regression.jsonl
  manifest.json
  seal.json
```

数据分配：

- 3 个 IFEval 锚点 → `rule_development`；
- 2 个 BFCL 锚点 → `technical_probes`；
- 25 个 `CMP-*` → `target_comparison`；
- 7 个 `JV-*` 家族、14 份回答标本 → `judge_validation`；
- 现有合成题只作为旧工程基线或经过审计后的规则/Judge 开发材料，不进入 Judge 验证或正式比较；
- `regression` 初始不得伪装成真实坏案例。既有人工设计 seed 继续明确标注 synthetic。

每道题必须有：唯一 ID、任务包、能力、用户目标、失败行为、严重程度、测试类型、来源类型、论文/仓库、原始 case ID 或“仅方法迁移”、许可证、改编说明、数据用途、场景家族、版本、适用条件、判断权限和证据字段。

必须实现并测试以下数据门禁：

- ID 唯一；
- 25 个比较题数量和分布为 6/7/5/7；
- 7 个 Judge 体检家族各有 PASS/FAIL 两份标本；
- 场景家族不得跨数据用途；
- `synthetic_draft` 不得进入任何正式文件；
- 无许可证来源只允许 `method_transfer`，不得标成 direct adaptation；
- source ledger 缺字段即失败；
- manifest 保存文件 hash、schema 版本和来源审计版本。

### 阶段 C：重做判断权限与原子规则

1. 审计所有现有 `deterministic_checks`，逐项改为：
   - `DIRECT_VERIFIER`：完整且与题目合同等价；
   - `SIGNAL_ONLY`：关键词、正则、粗略语言/长度等弱信号；
   - `SEMANTIC_REVIEW`：需要理解事实、限定、指代、承诺、证据支持；
   - `HUMAN_REQUIRED`：冲突裁决和高风险最终确认。
2. 不允许因为已有代码叫 `hard=true` 就保留为直接核验；按真实等价性重新裁决。
3. 每个语义 criterion 只判断一个行为，保存：适用条件、PASS、FAIL、ABSTAIN、NOT_APPLICABLE、正反例、严重程度和证据要求。
4. 严重程度在看到模型答案前固定；Judge 不能修改。
5. 引用格式存在只能证明“有引用”，不能证明“引用支持结论”。
6. 关键词命中/未命中不能独立证明无建议、无隐私信息、无越权承诺或事实正确。

### 阶段 D：实现单次原子 Judge 合同

正式矩阵不能继续直接使用会为同一答案产生多次 Provider 请求的 DeepEval `GEval` 默认链路。可以保留 DeepEval 的项目结构、结果适配或展示，但正式语义评分必须使用一个可审计的自定义 scorer：同一道题的一份答案只发出一次 Judge 请求，一次返回全部适用原子小项。

固定输出合同：

```text
criterion_id
applicability: APPLICABLE | NOT_APPLICABLE
evidence_sufficiency: SUFFICIENT | INSUFFICIENT
decision: PASS | FAIL | ABSTAIN
answer_evidence
source_evidence
reason
```

要求：

- Judge 不看到目标模型名、运行别名、Prompt ID 或 Prompt 版本；
- Judge 不输出或修改严重程度；
- Judge 的 FAIL 未经直接核验或人工确认，只进入复核，不直接决定版本；
- JSON 解析失败是 Judge 运行错误，不把待测答案记 0 分；
- 每份答案恰好一次 Judge 请求，manifest 和调用追踪必须能证明；
- 不让 Judge 自由生成新评分维度或合并 criterion。

### 阶段 E：评分模型离线体检

1. 用 7 个 `JV-*` 家族的 14 份固定回答验证 scorer、证据抽取和报告链路。
2. 候选人已经批准题目方向，但 14 份参考判断仍应保留“candidate-approved/reference-version”字段；不得称专家 gold。
3. 输出逐项混淆结果，重点展示：严重误放、明显错杀、证据不足时虚假确定、证据充分时逃避判断、引用错配、旧版本误用、参考路径偏见和环境状态错配。
4. 平均一致率只是补充；不要设置“必须 100% 才继续”的错误闭环。
5. 如果 scorer 失败，先分类为合同/提示/模型局限；只有合同或代码错误必须修。单纯 Judge 能力不足记录为限制，不无限改 prompt。

### 阶段 F：实现新的可恢复有限矩阵

新执行器在正式运行前生成不可变 `execution_plan.json`，明确：

- 25 个比较题；
- 4 个目标配置；
- 正式目标生成应为 `25 × 4 = 100` 次；
- 正式 Judge 评分应为 `100` 次；
- Provider probes、必要技术探针和一次临时重试上限单独列出；
- 不存在质量触发的额外请求路径；
- 同一 execution ID 只恢复缺失节点，不重做已完成输出；
- 新一轮必须新建 execution ID，程序不能自动创建。

执行顺序：离线门禁 → Provider probes → 技术路径探针 → 四配置正式生成 → 单次 Judge 初审 → 机器报告。机械门禁通过后可以自动继续，不要求候选人逐阶段按键。

停止规则：

- 鉴权、协议、endpoint、`/responses`、不支持参数或 profile 错误：第一次即停止；
- 临时网络/timeout：只允许一次诊断性重试，同类错误再次出现即停止；
- 连续 target/Judge 运行错误达到既有熔断阈值：停止并落盘；
- 内容质量差、Judge FAIL 或低分：绝不触发自动重跑；
- 任何实际计划请求数超出 `execution_plan.json`：停止；
- 不设置 Token/费用硬门禁，但运行前显示预计范围并完整留痕。

### 阶段 G：报告、人工界面和版本建议

实现并验证：

- 机器初审报告与候选人确认报告分开、追加保存；
- 候选人盲审时隐藏目标身份和 Judge 结论，提交后才解盲；
- 参考总分按已批准公式计算，ABSTAIN 排除得分但降低判断覆盖率；
- 四个任务包等权，题目先在包内平均；
- 同时展示完成率、判断覆盖率、人工覆盖率、严重/重要/一般错误、修复/退步/持平/不可比较；
- 运行错误不算内容 0 分；
- 总分不能抵消经确认的严重错误；
- 坏案例根因先记假设，控制变量证实后才升级为根因。

候选人盲审和争议裁决是唯一不能由执行窗口代做的验收环节。真实矩阵完成并生成匿名复核包后，执行窗口应停止并明确告诉用户需要完成哪些操作；不要替用户自动提交参考判断。

### 阶段 H：文档与真实性收尾

每个实质里程碑更新拥有该事实的文件：

- 项目状态 → `PROJECT3_CURRENT_STATUS_20260802.md`；
- 产品、功能、验收与真实工件 → `PROJECT_SPEC.md`；
- 研究来源变化 → 对应 `research/` 证据；
- 实现说明和运行命令 → 项目 README/运行文档；
- 面试主张变化 → `research/INTERVIEW_STAGE_STATUS.md`。

没有全局路由变化时不要继续扩写根 `AGENTS.md`。不得把计划、fixture 或旧 Chat 工件写成真实 Responses 结果。

## 3. 离线验收清单

真实 Provider 前必须全部通过：

1. 旧基线回归无非预期退步；
2. 新数据 schema、source ledger、许可证和 family leakage 测试；
3. 直接核验与 `SIGNAL_ONLY` 权限测试；
4. 14 份 Judge 体检 fixture 的结构化单请求合同测试；
5. target identity blind 测试；
6. `/responses` 假 Provider 的普通文本、资料、多轮、JSON、工具调用和工具回传路径；
7. 100 target + 100 Judge 的静态 DAG 计数测试；
8. 幂等恢复、熔断、一次临时重试、未知题号拒绝和禁止自动新一轮测试；
9. 机器/人工双报告、参考总分和覆盖率测试；
10. Ruff、pytest、Streamlit 五页或更新后页面 smoke、PowerShell 语法检查；
11. 离线运行的真实 Provider 请求数必须为 0；
12. 文档中的数量、hash、状态与实际工件一致。

## 4. 可自动继续与必须停止的边界

执行窗口可以自动完成：代码、数据、测试、离线验收、Provider probe、一次有限正式矩阵、机器报告、匿名复核包和对应状态文档。

只有以下情况需要停下来找用户：

- 正式题目在实现时暴露业务含义冲突，且不同选择会改变正确答案；
- 需要候选人亲自完成匿名参考判断或争议裁决；
- 加密 profile 不存在/不可用，且无法在不读取凭据的前提下继续；
- 请求 DAG 超出已批准的有限结构；
- 同类 Provider 硬错误按规则触发停止；
- 需要扩大到新任务包、第二 Judge、多次波动实验或新的正式矩阵。

普通代码选择、文件结构、测试补充和兼容修复不构成用户阻塞，执行窗口自行裁决并继续。

## 5. 完成定义

在候选人介入前，执行窗口的阶段性完成定义是：

- 科学 v1 数据、来源台账和 seal 已生成；
- 新判断权限、原子 Judge 和有限矩阵已实现；
- 全部离线验收通过；
- 如果 Provider 正常，一次四配置矩阵完成且没有质量触发重跑；
- 机器报告和匿名人工复核包已生成；
- 项目状态准确更新；
- 明确停在候选人亲自盲审入口。

候选人完成盲审后，再恢复执行窗口生成最终人工确认报告、版本建议、真实坏案例回归和面试证据包。

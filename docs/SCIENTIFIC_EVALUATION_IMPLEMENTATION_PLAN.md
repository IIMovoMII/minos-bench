# Project 3 科学测评模型实施任务书

状态：已撤回的工程草案；第二轮假设审计发现基础设计问题；不得据此执行  
方案版本：EFSE v1.0-draft（等待整体重写）  
制定日期：2026-08-01；2026-08-02 根据用户审核意见修正状态  
适用项目：`projects/project3_llm_evaluation/`  

> **2026-08-02 证据修正：**本文原先写入的 24 项 calibration、现有 8 条 holdout 以及 4–8 条 Evidence-Aware Judge 实验，均不是通过统计功效或误差目标推导出的科学样本量。24 是最小覆盖网格，8 是既有 40 题的 20% 工程留出，4–8 是探索性工作量上限。它们只能用于开发、流程验证或定性演示，不得支持 Judge 可靠性、模型优越性或有效性提升主张。所有依赖这些数字的实施步骤和验收门槛暂时失效，必须在用户批准完整口语审核稿 v3 后重写。

> **第二轮审计：**`SCIENTIFIC_EVALUATION_ASSUMPTION_AUDIT_20260802.md` 又确认确定性代理被当作 oracle、开发/选择/验证数据未分开、缺少 target trial、模型与 Prompt 混杂、状态语义混合和工程默认值被过早固定等问题。本文全部实施步骤现均失效，不得局部修补后直接执行；必须等用户审核第二轮问题后整体重写。

## 1. 执行授权与读取顺序

本文件把用户关于“面试最优”的要求、Project 3 当前实现、历史失败经验和既有论文/岗位研究收束为一份工程草案。它是给 Codex 或其他执行窗口使用的技术展开，不是候选人需要直接审核的版本。

总体方向必须先以 `SCIENTIFIC_EVALUATION_REVIEW_VERSION.md` 的口语版为准，由用户逐项审核。当前尚未获得批准；其他窗口不得仅凭“继续”或收到本文件就开始改代码、冻结规则或运行正式模型比较。只有用户明确批准口语版大方向后，才可把本文件同步为可执行版本。批准后仍有下列两类事项必须停下等待用户：

1. 候选人亲自完成的人工校准标签与 8 条 holdout 盲审；
2. 真实 Provider、外部服务或凭据状态造成且安全重试无法解决的硬阻塞。

开始执行前按顺序读取：

1. `README.md`；
2. `PROJECT_SPEC.md`；
3. 本文件；
4. `docs/EVALUATION_MODEL_DECISION_GATE.md`；
5. `docs/GITHUB_REFERENCE_AUDIT_20260819.md` 与正式题集的逐题来源台账；
6. 本文件“按文件改造清单”列出的现有源码与测试。

必须继续遵守工作区真实性、安全和凭据边界，不得读取、输出或记录任何 API Key、完整 Base URL、Cookie 或登录态。

## 2. 最终产品判断

### 2.1 评测对象

评测对象不是抽象的模型品牌，而是一份版本化 LLM 应用配置：

```text
目标模型 + Prompt + 生成参数 + 数据版本 + 代码版本
```

只有数据、评测规则和 Judge 配置兼容时才允许做正式版本比较。

### 2.2 本项目支持的决策

本项目回答：

> 在同一冻结任务集上，候选配置相对基线是否表现出有证据支持的改善，是否出现不可接受的关键回归，以及哪些样本仍不足以自动裁决、需要人工检查。

它不回答：

- 哪个基础模型普遍最强；
- 模型是否可以直接投入生产；
- 40 条样本上的小幅领先是否可以推广到真实用户流量；
- Judge 分数是否等于客观真值。

### 2.3 方法名称

项目内将最终方法命名为：

```text
Evidence-First Selective Evaluation（EFSE）
证据优先的选择性评测
```

这是便于产品说明和面试表达的项目内名称，不声称为原创学术算法。

核心原则：

1. 能由代码或权威证据验证的要求，不交给 LLM 猜；
2. 开放语义拆成原子 criterion，一次只判断一个问题；
3. Judge 必须引用允许范围内的证据，并可以 `ABSTAIN`；
4. 先验证 Rubric，再验证冻结 Judge 配置，最后验证裁决策略；
5. Judge 未通过校准时缩小自动裁决权，不通过反复改 Prompt 追求全票；
6. 版本比较使用同题配对和区间，不以两个孤立总分排名；
7. 关键错误不可被文风、完整性或其他软分补偿；
8. 不确定是合法结论，`REVIEW/INCONCLUSIVE` 不是项目失败。

### 2.4 历史检索结论如何进入本方案

本方案不是从框架默认值倒推出来的。公开参照项目与取舍见 `docs/GITHUB_REFERENCE_AUDIT_20260819.md`，逐题方法来源见正式题集的 `source_ledger.jsonl`：

| 研究/市场证据 | 本方案采用的动作 |
|---|---|
| BOSS 评测岗与小红书面经共性 | 从业务决策、评测集、规则、Bad Case 和迭代闭环讲项目，不迎合单一硬件/视频 JD |
| CheckList | 用能力 × 正常/边界/扰动行为矩阵组织样本，不只报总体准确率 |
| G-Eval、RubricEval、Autorubric | 使用明确、原子、可解释的 criterion 和正反 anchor，避免整体印象分 |
| MT-Bench、LLMBar | 隐藏目标身份，检查位置、冗长和“好看但违背指令”的偏差 |
| Trust or Escalate | 允许 Judge 弃权，评价 accuracy 与 coverage 的取舍 |
| Progress Illusion | 两个版本能力接近时，不把小差异解释成确定进步 |
| Adding Error Bars to Evals | 使用同题配对、有效样本量和误差区间 |
| How to Correctly Report LLM-as-a-Judge Evaluations | 用人工标签估计 Judge false-pass/false-reject，不把 Judge 原始通过率当真实准确率 |
| PoLL 与 Geometry of LLM-as-Judge | 第二 Judge 必须证明增量价值，多模型共识不等于人类真值 |
| AJ-Bench | 证据、状态和过程优先；Judge 引用证据并接受确定性 verifier 检查 |

这些研究只决定方法选择，不把论文数据、提升幅度或行业结论复制成本项目结果。

## 3. 保留、替换与不做事项

### 3.1 原样保留的工程底座

- 四任务包、40 条主数据、32 development / 8 holdout；
- holdout 密封与显式解封；
- LiteLLM Responses 目标生成和 Judge 适配；
- `reasoning.effort=max`、`store=false`、非流式 v1；
- 目标身份盲评；
- `live / replay / deterministic-only`；
- 确定性检查、追加式工件、哈希和完整性校验；
- CLI 权威执行、Streamlit 展示；
- 人工复核、Bad Case 和版本化回归；
- `RUNTIME_ERROR` 与模型质量结论分离。

### 3.2 必须替换的工程基线

- 用包级整体 Rubric 直接得到一个 G-Eval 综合分；
- 未经人工校准的 `0.75 / 0.45`；
- 只取 Judge 重复分数平均值的稳定性判断；
- 只按 `PASS/REVIEW/FAIL` 等级升降比较版本；
- 只报简单三态一致率的 Judge—人工校准；
- 人工盲审时隐藏评分规则、依赖直觉判断的界面。

### 3.3 本轮明确不做

- 不更换 DeepEval/LiteLLM 框架；
- 不复现完整 AJ-Bench、AWS GUI 或浏览器 Agent 环境；
- 不扩展图片、音频、视频或安全红队；
- 不默认增加第二 Judge 或多数票；
- 不训练或微调 Judge；
- 不构建生产监控、登录、多租户或队列；
- 不为了获得漂亮结果修改 holdout、删除 Bad Case 或降低规则；
- 不把统计方法包装成小样本上的“可靠性保证”。

## 4. 最终评测数据合同

### 4.1 原子语义规则

新增 `SemanticCriterionSpec`，建议字段如下：

```text
criterion_id          全局唯一、版本化 ID
name                  短名称
requirement           只描述一个可观察行为
severity              critical / major / minor
decision_role         required / diagnostic
evidence_sources      允许引用的证据范围
pass_definition       满足条件
fail_definition       不满足条件
abstain_definition    证据或规则不足的条件
positive_anchor       人工确认的正例说明
negative_anchor       人工确认的反例说明
```

约束：

- 不加入默认权重；
- `required` criterion 的 `FAIL/ABSTAIN` 会把机器结论路由到 `REVIEW`；
- `diagnostic` criterion 失败只形成提示，不单独阻止 `PASS`；
- `critical` 表示后续人工确认后可形成关键回归，不代表 Judge 可直接硬失败；
- 同一要求已由确定性代码完整覆盖时，不再重复配置语义 criterion；
- 结构化输出若 Schema、字段和值已经构成完整 oracle，可以不调用 Judge。

### 4.2 配置文件组织

不修改当前 40 条主问题、输入、参考事实和 holdout 内容。新增：

```text
configs/rubrics_v2.yaml
configs/case_criteria_v2.yaml
```

`rubrics_v2.yaml` 保存 criterion 模板；`case_criteria_v2.yaml` 以 `case_id` 显式绑定适用 criterion。两者内容和 SHA-256 必须进入 `metric_config_hash` 与最终 freeze 工件。

现有 `rubric` 字段保留用于兼容旧工件和显示“本题目标”，但不再作为最终整体评分标准。

### 4.3 Judge 结构化结果

新增以下核心结构：

```text
CriterionVerdict: PASS / FAIL / ABSTAIN

EvidenceRef:
  source: input / context / expected_facts / forbidden_facts /
          tool_trace / actual_output
  locator: 可选索引或字段路径
  quote: 原文片段

CriterionAssessment:
  criterion_id
  verdict
  reason
  evidence_refs[]
  evidence_valid
  repetition
  judge_requests / tokens / cost
```

不得依赖 Judge 自报的置信度作为自动裁决依据。可观察的不确定性信号是：

- Judge 主动 `ABSTAIN`；
- 引用证据无法在允许来源中定位；
- 同一输入重复判断不一致；
- A/B 交换顺序后偏好翻转；
- Judge 与确定性规则或人工参考冲突。

### 4.4 证据校验

Judge 每项判断必须引用证据。代码对引用做确定性检查：

1. `quote` 必须能在声明的 `source` 中找到；
2. 允许做 Unicode 与空白规范化，但不得用另一个 LLM 判断“语义相似”；
3. 证据不存在、来源越权或只引用 Judge 自己的理由时，`evidence_valid=false`；
4. 必要证据无效时，该 criterion 强制改为 `ABSTAIN`，用例进入 `REVIEW`。

## 5. 四任务包的标准框架

以下是默认 criterion 池。执行时必须逐题绑定，不能强迫每题使用全部维度。

| 任务包 | 原子语义 criterion | 角色与严重度 |
|---|---|---|
| 指令与文本生成 | 内容忠实：保留决定性事实且不增加无依据信息 | required / major |
| 指令与文本生成 | 任务相关：直接完成用户要求，不答非所问 | required / major |
| 指令与文本生成 | 表达适配：语气、清晰度与目标读者匹配 | diagnostic / minor |
| Grounded QA | 结论有据：每个实质性结论均由给定资料支持或明确标为不确定 | required / critical |
| Grounded QA | 限定完整：范围、例外、优先级和附加条件没有被遗漏 | required / major |
| Grounded QA | 证据不足处理：资料不足时不外推，并指出缺少什么证据 | conditional required / critical |
| Grounded QA | 回答相关：直接回答问题，不用无关内容掩盖结论 | diagnostic / minor |
| 多轮上下文 | 有效约束保留：保留仍生效的明确事实与约束 | required / critical |
| 多轮上下文 | 更新正确：采用最新修改，不继续使用已经撤销的内容 | required / critical |
| 多轮上下文 | 冲突与缺失处理：未解决冲突或关键信息缺失时请求确认 | conditional required / critical |
| 多轮上下文 | 连贯表达：最终回答与当前任务连贯 | diagnostic / minor |
| 结构化与工具 | 工具决策：该调用时调用，不该调用时不调用 | conditional required / critical |
| 结构化与工具 | 工具结果使用：最终回答忠实、完整使用工具回传 | conditional required / critical |
| 结构化与工具 | 最终任务完成：在调用或结构化输出后完成用户目标 | required / major |

明确边界：

- JSON 是否可解析、字段类型和值是否准确继续由代码裁决；
- 工具名、参数和顺序继续由代码裁决；
- 语义 Judge 不重复给这些项目打“印象分”；
- `N/A` 不记零分，而是从该题适用 criterion 分母中排除。

## 6. 用例与项目裁决规则

### 6.1 单题机器结论

按以下顺序执行：

1. 目标或 Judge 链路未完成：`RUNTIME_ERROR`；
2. 任一确定性硬规则失败：`FAIL`；
3. 任一 required criterion 为 `FAIL` 或 `ABSTAIN`：`REVIEW`；
4. 必要证据无效、重复判断冲突或机器规则冲突：`REVIEW`；
5. 所有 required criterion `PASS`：`PASS`；
6. diagnostic criterion 的失败保留为提示，不单独改变 `PASS`。

语义 Judge 仍不能直接产生最终硬 `FAIL`。人工复核可以追加 `PASS / FAIL / NEEDS_MORE_EVIDENCE`，且不得覆盖机器原判。

### 6.2 不使用默认综合分

默认报告：

- 硬门槛通过率；
- 各 criterion 的 `PASS/FAIL/ABSTAIN`；
- 自动裁决覆盖率；
- `PASS/REVIEW/FAIL/RUNTIME_ERROR`；
- critical/major/minor 问题数量；
- 人工确认的关键回归；
- Judge 误放行、误拒绝、弃权和稳定性；
- 版本同题 `win/tie/loss` 和配对区间。

不得把四个任务包等量抽样后的总体通过率叫“线上准确率”。如果未来有真实场景分布，再在 holdout 解封前明确配置业务权重。

## 7. Rubric 验证

新增 `validate-rubrics` CLI。每条 criterion 必须通过：

1. 一次只测一个行为；
2. `PASS` 与 `FAIL` 可以区分且没有明显重叠；
3. 存在清晰 `ABSTAIN` 边界；
4. 指明允许使用的证据；
5. 有正反 anchor；
6. 不与确定性检查重复；
7. 不用“优质、合理、很好”等无锚点形容词作唯一标准；
8. 不使用模型身份、品牌或 Prompt 版本；
9. conditional criterion 的适用条件可由当前 case 数据确定；
10. criterion ID 与版本进入哈希。

Rubric 验证证明的是规则可执行，不证明 Judge 已能正确执行规则。

## 8. Judge 校准集与人工参考

### 8.1 校准集规模

新增独立数据：

```text
datasets/judge_calibration/items.jsonl
datasets/judge_calibration/proposed_labels.jsonl
datasets/judge_calibration/human_labels.jsonl
datasets/judge_calibration/seal.json
```

原草案暂拟 24 个“输出—criterion”评审单元，四任务包各 6 个：

- 2 个明确 `PASS`；
- 2 个明确 `FAIL`；
- 2 个应 `ABSTAIN` 的边界或证据不足样本。

每个单元只聚焦一个 criterion。尽量覆盖：

- 看起来流畅但违反指令；
- 冗长但没有增加有效信息；
- 关键限定条件遗漏；
- 证据不足却自行补全；
- 多轮旧约束与新约束冲突；
- 工具调用正确但误用返回结果；
- 规则本身不足以裁决的真实边界。

该 24 项设计只可作为 Rubric/界面 pilot，不是 Judge 可靠性验证集，也不再是固定实施门槛。正式 calibration/validation 数量必须从误放风险、目标精度、置信水平、分层结构和先导数据推导。Codex/AI 可以创建样本和 `proposed_labels`，但这些不得称为人工标签；候选人标签也只能按实际标注者结构准确命名。

### 8.2 校准盲审界面

新增“Judge 校准”页面或模式。候选人可见：

- 题目、上下文和候选输出；
- 当前只评的一个 criterion；
- PASS/FAIL/ABSTAIN 定义与正反 anchor；
- 允许证据范围。

候选人不可见：

- proposed label；
- Judge 结果、分数和理由；
- 目标模型或 Prompt 身份。

每项必须填写理由。记录追加保存；若修改判断，旧记录保留。样本量方案要求的项目完成后生成标签 hash，之前不得运行正式 Judge meta-eval。

### 8.3 校准统计

Judge meta-eval 至少输出：

- 三分类混淆矩阵；
- 非弃权样本上的 accuracy 与 macro-F1；
- false-pass：人工 `FAIL`、Judge `PASS`；
- false-reject：人工 `PASS`、Judge `FAIL`；
- abstain coverage：非 `ABSTAIN` 比例；
- selective accuracy：Judge 作出 PASS/FAIL 的样本中与人工一致的比例；
- evidence validity；
- 同输入三次重复一致率；
- 运行错误、调用数、Token、费用和延迟。

置信区间按校准 item/case 重采样，不把同一题的多个 criterion 或重复运行当成完全独立样本。最小覆盖 pilot 只用于调试，统计全部标为描述性证据，不声称生产级保证；正式样本量另行推导。

### 8.4 Judge 策略选择

至少比较：

- P0：单次判断 + 强制证据；
- P1：三次判断，只有全体一致才自动裁决，否则 `ABSTAIN`；
- P2：三次多数判断，分歧作为稳定性标记。

不预先规定 P1/P2 一定更好。按以下字典序选择最简单策略：

1. 优先使人工标为 critical `FAIL` 的样本出现 0 个“观察到的误放行”；
2. 再减少全部 false-pass；
3. 再减少总错误；
4. 再提高自动覆盖率；
5. 仍相同时选择调用更少、解释更简单的策略。

“0 个观察到的误放行”只描述实际校准样本，不得写成真实风险为零；必须同时报告对应分母和区间上界。

若没有任何策略满足第一项：

- critical 语义 criterion 禁止自动 PASS；
- Judge 只作初筛并统一进入 `REVIEW`；
- 不继续无上限修改 Judge Prompt。

第二 Judge 只在后续另有配置且相对人工标签显示独立增量时加入；不作为本轮完成门槛。

## 9. Judge 与行为扰动测试

除人工校准外，建立行为测试夹具：

1. **重复性**：同一输入三次；
2. **顺序偏差**：pairwise A/B 与 B/A；
3. **冗长偏差**：语义相同、只增加无用长度；
4. **措辞不变性**：不改变事实的同义改写；
5. **错误敏感性**：人为加入一个决定性错误，结论必须发生预期变化；
6. **证据缺失**：删除决定性证据，Judge 应 `ABSTAIN`；
7. **身份盲化**：Judge payload 继续不含模型、别名和 Prompt 身份。

这些测试分别报告，不压缩成一个“Judge 可信度分数”。

## 10. 版本比较与统计

### 10.1 比较主链

主比较继续使用相同 40 条任务：

1. Model A + Prompt V1；
2. Model B + Prompt V1；
3. weaker model + Prompt V2。

前两组是同 Prompt 模型对比；第三组同时改变模型和 Prompt，只能解释为提示补偿实验。

### 10.2 同题分类

每题比较输出：

```text
improved
regressed
unchanged
critical_regression
not_comparable
```

判定优先级：

1. 数据/metric hash 不兼容或任一运行错误：`not_comparable`；
2. 基线没有、候选出现新的确定性或人工确认 critical 失败：`critical_regression`；
3. 依据相同 criterion 的逐题状态与人工最终裁决判断改善/退化；
4. 两边绝对结果相同但语义质量仍需比较时，才调用身份盲化 pairwise Judge；
5. pairwise 必须执行 A/B 与 B/A 顺序交换，翻转则进入 `REVIEW`，不强判胜负。

### 10.3 统计输出

新增 case-level 配对统计：

- `win/tie/loss`；
- 候选—基线的逐题差异；
- 固定随机种子的 case-level paired bootstrap 95% 区间；
- 按四任务包分层的描述性结果；
- 有效可比样本量和 `not_comparable` 数量；
- critical regression 单独列出。

如果区间覆盖 0，结论必须为 `INCONCLUSIVE`，不能按点估计强行排名。建议最终比较结论枚举：

```text
SUPPORTED_IMPROVEMENT
INCONCLUSIVE
SUPPORTED_REGRESSION
BLOCKED_BY_CRITICAL_REGRESSION
NOT_COMPARABLE
```

40 条数据的区间可能很宽，这是正常结果，不得通过删题或调阈值缩窄。

## 11. Holdout 人工盲审改造

现有盲审把 Rubric 也隐藏，容易让候选人凭直觉判断。改为“身份盲化、规则可见”：

候选人可见：

- 输入、上下文、对话和工具信息；
- 适用原子 criterion、定义与 anchor；
- 评审所必需的来源事实和确定性检查说明；
- 候选输出。

候选人不可见：

- 目标模型、Prompt 和运行别名；
- 机器 `PASS/REVIEW/FAIL`；
- Judge verdict、理由和分数；
- 另一个模型的输出。

现有 8 项全部提交前不展示机器—人工对比。它们只验证密封和盲审流程；不得单独用于 Judge 或模型的统计有效性主张。完成后报告：

- case-level 三态一致；
- criterion-level false-pass/false-reject/abstain；
- 自动裁决覆盖率；
- `REVIEW` 中人工确认问题的比例；
- 每项分歧原因。

只有一位候选人标注时，不报告 inter-annotator agreement 或 Cohen's kappa；应明确这是单评审者 POC 限制。

## 12. 按文件改造清单

### 12.1 新增文件

```text
configs/rubrics_v2.yaml
configs/case_criteria_v2.yaml
datasets/judge_calibration/items.jsonl
datasets/judge_calibration/proposed_labels.jsonl
src/llm_eval_workbench/rubric_service.py
src/llm_eval_workbench/metrics/atomic_judge.py
src/llm_eval_workbench/judge_meta_eval.py
src/llm_eval_workbench/statistics.py
src/llm_eval_workbench/pairwise_service.py
tests/test_rubric_contract.py
tests/test_atomic_judge.py
tests/test_judge_meta_eval.py
tests/test_statistics.py
tests/test_pairwise_service.py
```

人工完成后再生成：

```text
datasets/judge_calibration/human_labels.jsonl
datasets/judge_calibration/seal.json
configs/evaluation_model_freeze.json
```

### 12.2 修改文件

`src/llm_eval_workbench/schemas.py`

- 新增 severity、decision role、criterion verdict、evidence、criterion assessment、校准标签和比较结论 Schema；
- 保留旧 `judge_score_*` 字段以读取历史工件；新字段使用默认值，禁止破坏旧 artifacts；
- `JudgeConfig.threshold/review_floor` 标记为 legacy，最终策略不再依赖它们。

`src/llm_eval_workbench/metrics/deepeval_metrics.py`

- 提取可复用 Responses Judge 模型适配与 usage 跟踪；
- 保留旧 G-Eval 用于历史兼容和可选诊断；
- 最终裁决改由 atomic metric 驱动；
- payload 继续执行 `target-identity-blind-v1`，并增加自动测试。

`src/llm_eval_workbench/metrics/atomic_judge.py`

- 以 DeepEval 自定义 metric 或等价受测试封装执行一个 criterion；
- 使用 Responses 结构化输出；
- 只提供该 criterion 需要的证据；
- 支持 `PASS/FAIL/ABSTAIN`；
- 校验证据引用并追踪调用/Token/费用；
- 不把目标模型身份写入 Prompt。

`src/llm_eval_workbench/evaluator.py`

- 确定性硬规则先执行；
- 按 case assignment 逐条执行原子 criterion；
- 实现 required/diagnostic 和证据无效路由；
- 删除以 G-Eval 平均分直接判 PASS 的最终逻辑；
- 旧行为只在 legacy profile 下保留。

`src/llm_eval_workbench/run_service.py`

- 加载 rubric 与 case assignment；
- rubric、assignment、Judge policy 和证据策略进入 metric hash；
- manifest 记录 `evaluation_model_version` 与 freeze hash；
- 正式 live 必须验证 freeze 内容与当前哈希一致；
- 运行中仍逐题追加写入，不能因 Judge 异常损坏目标输出。

`src/llm_eval_workbench/review_service.py`

- 增加 calibration review；
- holdout 盲审改为规则可见、身份和机器结果隐藏；
- 扩展 criterion-level alignment；
- 记录所有人工修订而不覆盖旧记录。

`src/llm_eval_workbench/analysis.py`

- 保留旧比较入口兼容历史；
- 新增 critical regression、criterion delta、pairwise W/T/L 和不可比原因；
- 调用 case-level bootstrap；
- 不再以 Judge 平均分差作为主要结论。

`src/llm_eval_workbench/report_service.py`

- 报告原子 criterion、证据、Judge meta-eval、覆盖率和分歧；
- 删除“Mean Judge score”作为报告首要指标；
- 加入数据规模、有效样本量、区间与 `INCONCLUSIVE` 说明；
- 继续保留运行错误、usage、费用和工件哈希。

`src/llm_eval_workbench/cli.py`

至少新增：

```text
validate-rubrics
review-calibration
judge-meta-eval
freeze-evaluation-model
pairwise-compare（或扩展现有 compare）
```

`app.py`

- 增加 Judge 校准入口；
- 展示 atomic criteria 与证据；
- holdout 规则可见、机器身份和结论隐藏；
- 结果页展示混淆矩阵、覆盖率、W/T/L、critical regression 和区间；
- 不用一个仪表盘总分代表模型质量。

`scripts/run_full_pipeline.ps1`

- provider probe 保留；
- freeze 校验必须验证 rubric、assignment、人工校准标签和 Judge policy hash；
- 正式运行后执行新比较与报告；
- 仍在候选人 8 条 holdout 盲审处停止；
- 不读取或回显任何凭据。

## 13. 测试矩阵

至少覆盖以下自动测试：

1. criterion 缺少正反定义、证据范围或重复 ID 时校验失败；
2. conditional criterion 适用性正确；
3. 不适用 criterion 不进入分母；
4. 一个 Judge 请求只评价一个 criterion；
5. Judge payload 不含模型、运行别名和 Prompt 身份；
6. 证据 quote 可定位时有效；
7. 伪造或越权证据强制 `ABSTAIN/REVIEW`；
8. hard deterministic fail 仍直接 `FAIL`；
9. required semantic fail 进入 `REVIEW` 而不是硬 FAIL；
10. diagnostic fail 不单独阻止 PASS；
11. Judge runtime error 仍为 `RUNTIME_ERROR`；
12. 重复判断冲突进入 `REVIEW`；
13. P0/P1/P2 聚合规则可复现；
14. 校准混淆矩阵、false-pass、false-reject、coverage 计算正确；
15. bootstrap 使用固定 seed，可重复且按 case 重采样；
16. 数据或 metric hash 不同禁止比较；
17. critical regression 优先于普通分数改善；
18. pairwise A/B 交换后翻转进入 REVIEW；
19. holdout 盲审显示规则但隐藏模型、机器结果和 Judge 结果；
20. 人工记录追加保存、不覆盖旧记录；
21. freeze hash 不匹配时阻断正式 live；
22. 旧运行工件仍能加载和生成 legacy 报告；
23. 所有工件不含 Key、完整 URL 或请求头；
24. Streamlit 全页面冒烟无异常。

每阶段完成后运行：

```powershell
pytest
ruff check .
ruff format --check .
uv pip check
```

测试通过数使用实际结果写入状态文档，不预填新数字。

## 14. 分阶段执行顺序

| 阶段 | 工作 | 退出条件 |
|---|---|---|
| 0 基线锁定 | 保存当前测试结果、数据 hash 和代码状态；不动历史工件 | 当前 46 tests 等既有事实重新核验 |
| 1 数据合同 | 新增 atomic criterion Schema、rubric/assignment 配置和校验 | 本地合同测试全过，40 条问题内容不变 |
| 2 Judge 引擎 | 实现结构化 atomic Judge、证据校验和新路由 | 假 Judge/假 Responses 合同测试全过 |
| 3 校准工作流 | 先确定错误/置信目标并推导样本量，再创建校准集、盲审 UI、标签密封和 meta-eval | 执行窗口停在经批准的人工标签门禁 |
| 4 策略冻结 | 标签完成后比较 P0/P1/P2，生成校准报告并选择策略 | 用户执行指令已确认方向；freeze 含全部 hash |
| 5 比较统计 | 实现 criterion 差异、critical regression、pairwise 与 bootstrap | 固定夹具产生可复核的 W/T/L 和区间 |
| 6 界面与报告 | 更新 Streamlit、JSON/CSV/Markdown 和面试展示 | 全页面冒烟通过，报告无伪总分 |
| 7 离线验收 | 完整 pytest/Ruff/fixture/replay/integrity | 新离线验收工件和 hash 保存 |
| 8 在线正式运行 | Responses probes，三组 40 条 live、replay、比较 | 无未处理运行错误；工件完整 |
| 9 Holdout | 候选人完成现有 8 条规则可见、身份盲化流程复核；科学验证另用经推导的独立验证集 | 8/8 可证明密封流程完成，不单独生成有效性主张 |
| 10 回归闭环 | 选择至少一个真实、人工确认的 Bad Case 加入新回归版本 | 新回归可重复执行，旧版本保留 |
| 11 面试交付 | 更新项目权威、数据卡、评测卡、演示和问答 | 所有说法绑定真实工件 |

阶段 3 与阶段 9 是合法人工门禁，不允许 Codex 冒充候选人完成。

## 15. 冻结工件

`configs/evaluation_model_freeze.json` 至少保存：

```text
version / status / candidate_confirmed / confirmed_at
decision_scope
evaluation_method: evidence-first-selective-evaluation-v1
dataset_hash
holdout_seal_hash
rubric_profile_hash
case_assignment_hash
calibration_items_hash
human_labels_hash
judge_policy
judge_config_hash
judge_meta_eval_artifact_hash
case_adjudication_policy
comparison_policy
blind_policy_version
code_hash
known_limitations
```

freeze 工件只保存非敏感配置与 hash。若当前代码、Rubric、标签或 Judge policy 与 freeze 不一致，正式运行必须拒绝启动。

## 16. 在线运行与失败处理

1. 只运行 `/responses`、`store=false`、非流式和当前配置的 `reasoning.effort=max`；
2. 先做四个最小 probe；
3. Probe 失败只按协议、参数、Provider、超时等工程错误处理，不修改评分标准；
4. 每题目标输出先落盘，再执行 Judge；
5. Judge 失败不丢目标输出，可在 replay 补评；
6. 不把超时、限流或空响应算模型能力失败；
7. 不读取或显示加密 profile 的值；
8. 旧 Chat 运行只保留为历史诊断，不进入新比较。

## 17. 防止再次陷入无限返工

历史 Project 1/2 的核心教训必须变成执行约束：

1. 不以“所有 Judge 都说通过”作为项目完成标准；
2. 不因单题失败特化全局 Prompt；
3. 数据、规则、实现、Judge 和 Provider 一次只改变一个变量；
4. 每个失败先归因到数据、硬规则、目标生成、Judge、人工标准、比较统计或运行环境；
5. Judge Prompt 在 development calibration 上最多进行两轮有证据的修改；
6. 两轮后仍有问题时，缩小自动裁决范围或提高 REVIEW，而不是继续追分；
7. holdout 解封后不得调 Rubric、阈值或 Judge policy；
8. 任何小样本微小领先都必须允许结论为 INCONCLUSIVE；
9. 在线模型能力不足不阻断工程验收，系统是否正确路由和留证才是验收对象；
10. 每个里程碑立即更新拥有事实的状态文档，不等全部结束后补写。

## 18. 可选亮点：Evidence-Aware Judge

只有阶段 0–11 全部完成后再做，不能阻断核心项目。

从 Grounded QA 或 Function Call 选择已有人工作为参考的案例。若只做原草案所说的 4–8 条，只能作为探索性链路演示；若要比较有效性，样本量必须根据目标改进和配对差异另行估算：

- A：静态 Judge 只看输入、回答和简化上下文；
- B：Judge 可调用 2–3 个只读 verifier，例如 JSON Schema、引用定位、工具轨迹或冻结工件读取；
- 两者使用相同底座、criterion 和目标输出；
- 比较 false-pass、false-reject、coverage、稳定性、运行错误、成本和延迟；
- 没有稳定增量就不纳入主流程。

不得声称复现 AJ-Bench，也不得迁移其论文提升数字。

## 19. 最终验收标准

### 19.1 工程验收

- 所有新旧测试、Ruff、格式、依赖检查和 Streamlit 冒烟通过；
- 40 条主数据内容与来源仍可核验；
- rubric/assignment、校准标签、freeze、结果和代码均有 hash；
- 旧工件可读；
- 所有敏感信息检查通过；
- 运行中断、Judge 错误与 replay 恢复可验证。

### 19.2 测评模型验收

- 经批准样本量方案要求的候选人人工 calibration 标签完成；
- Judge meta-eval 报告包含混淆矩阵、false-pass、false-reject、coverage、稳定性和错误；
- Judge policy 按预声明字典序选择，未通过时明确缩权；
- 不再依赖任意 `0.75/0.45` 作最终裁决；
- 每个 Judge verdict 有可验证证据或 ABSTAIN；
- 版本比较包含 W/T/L、critical regression、有效样本量和配对区间；
- 区间覆盖 0 时输出 INCONCLUSIVE。

### 19.3 真实运行验收

- 三个 Responses 运行各覆盖冻结的 40 条；
- 运行错误单独报告并处理，不混入质量失败；
- 现有 8/8 候选人 holdout 流程盲审完成；若报告统计有效性，另有满足样本量方案的独立验证证据；
- 至少一个真实、人工确认的 Bad Case 进入新回归版本；
- 最终数字全部来自保存工件；
- 候选人能亲自完成约 10 分钟演示并解释一个分歧案例。

项目成功不要求被测模型全对，也不要求 Judge 与人工全一致。

## 20. 文档与面试更新

完成对应里程碑后更新：

- `PROJECT_SPEC.md`：最终方法和范围；
- `docs/EVALUATION_MODEL_DECISION_GATE.md`：记录用户确认与 freeze；
- `docs/DATA_CARD.md`：校准集、单评审者限制和新 hash；
- `docs/EVALUATION_CARD.md`：原子 Rubric、Judge meta-eval 与配对统计；
- `docs/IMPLEMENTATION_STATUS.md`：实际完成项与工件；
- `docs/DEMO_GUIDE.md`：新版 10 分钟演示；
- `docs/INTERVIEW_QA.md`：全部改为口语化回答；
- 项目 `README.md` 与工作区 `README.md`：状态和导航。

面试主线应收束为：

> 我不是直接相信一个 Judge 总分，而是先检查评分标准能不能区分好坏，再用人工参考和扰动测试检查冻结 Judge 配置能不能稳定执行标准。可验证项交给代码，开放语义拆成原子规则，证据不足允许弃权；最后用同题配对和区间比较版本。评测器校准不理想时，我缩小自动裁决范围，而不是为了通过不断改 Prompt。

在真实三模型运行与人工盲审完成前，只能说“方案与工作流已实现”，不能声称已经得到某模型排名、Judge 准确率或提升数字。

## 21. 执行窗口最终交付清单

执行窗口最终必须交付：

1. 修改文件清单；
2. 新数据、Rubric、calibration、freeze 和代码 hash；
3. 测试、Ruff、UI 与离线验收原始结果；
4. Provider probe 和三个正式 run_id；
5. Judge meta-eval 工件；
6. 两组正式比较工件；
7. 8 条 holdout 完成状态；
8. 新回归版本；
9. 更新后的项目状态、演示和口语面试材料；
10. 尚未完成或必须由候选人亲自完成的事项。

如果执行在人工校准或 holdout 处停止，应明确给出打开哪个页面、完成多少项以及完成后的恢复命令，不得把人工门禁描述成工程失败。

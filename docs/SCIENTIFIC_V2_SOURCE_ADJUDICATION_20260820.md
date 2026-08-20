# Scientific v2 历史输出源证据裁决

日期：2026-08-20
状态：当前有效；只用于历史诊断，不构成新 Benchmark 分数

## 结果

Codex 逐题对照题面、证据、工具前置状态和 96 份保存回答后，将历史输出重新分为：

| 状态 | 数量 | 含义 |
|---|---:|---|
| PASS | 82 | 未发现题面明示标准下的实质错误 |
| FAIL | 2 | 存在明确、可复核的实质错误 |
| INVALID_CASE | 12 | 题面或 runner 不足以公平裁决模型 |

12 个无效输出来自 `CMP-GQ-22`、`CMP-ST-21`、`CMP-ST-22` 三道整题，每题四个配置。剩余 84 个可裁决输出中，82 个通过、2 个失败。该比例不能解释为准确率、模型排名或发布结论。

## 逐题矩阵

| 题目 | A | B | C | D | 关键说明 |
|---|---|---|---|---|---|
| CMP-IG-21 | PASS | PASS | PASS | PASS | 明示格式与事实边界满足 |
| CMP-IG-22 | PASS | PASS | PASS | PASS | 短样本与缺口保留 |
| CMP-IG-23 | PASS | **FAIL** | PASS | PASS | B 虚构日期、回归完成与上线事实 |
| CMP-IG-24 | PASS | PASS | PASS | PASS | 引文越权指令未执行 |
| CMP-IG-25 | PASS | PASS | PASS | PASS | 匿名与待验证边界满足 |
| CMP-IG-26 | PASS | PASS | PASS | PASS | “待完成”与“仍未完成”等义 |
| CMP-GQ-21 | PASS | PASS | PASS | PASS | 结论与证据链成立 |
| CMP-GQ-22 | **INVALID** | **INVALID** | **INVALID** | **INVALID** | 新旧规则有生效日，题面却缺交易/结算日期 |
| CMP-GQ-23 | PASS | PASS | PASS | PASS | 证据不足边界成立 |
| CMP-GQ-24 | PASS | PASS | PASS | PASS | 决定性门禁与引用成立 |
| CMP-GQ-25 | PASS | PASS | PASS | PASS | 反证和排除条款已纳入 |
| CMP-GQ-26 | PASS | PASS | PASS | PASS | 最终结论有源证据支持 |
| CMP-MT-21 | PASS | PASS | PASS | PASS | 跨轮约束保留 |
| CMP-MT-22 | PASS | **FAIL** | PASS | PASS | B 违反题面明确的三行合同；C 是否定句误杀 |
| CMP-MT-23 | PASS | PASS | PASS | PASS | 当前有效信息使用正确 |
| CMP-MT-24 | PASS | PASS | PASS | PASS | 背景时间不是必答字段 |
| CMP-MT-25 | PASS | PASS | PASS | PASS | 自定精确前缀不是题面合同 |
| CMP-MT-26 | PASS | PASS | PASS | PASS | 自定四行前缀不是题面合同 |
| CMP-ST-21 | **INVALID** | **INVALID** | **INVALID** | **INVALID** | runner 未执行工具并回传结果继续下一轮 |
| CMP-ST-22 | **INVALID** | **INVALID** | **INVALID** | **INVALID** | runner 缺少同一迭代工具循环 |
| CMP-ST-23 | PASS | PASS | PASS | PASS | 工具、参数和状态满足 |
| CMP-ST-24 | PASS | PASS | PASS | PASS | 顺序澄清属于合理行为 |
| CMP-ST-25 | PASS | PASS | PASS | PASS | 工具边界满足 |
| CMP-ST-26 | PASS | PASS | PASS | PASS | 句末标点不改变备注语义 |

## 两个明确失败

- `CMP-IG-23` 配置 B：在“事实”行虚构 `2025年1月15日`，并声称回归完成、已经上线。随后解释“此描述为虚构”不能撤销已经输出的假事实。
- `CMP-MT-22` 配置 B：正确守住退款证据门禁，但题面明确要求最终回复固定三行；它额外增加一个非空首行，因此违反明确格式合同。

## 三道无效题

- `CMP-GQ-22`：规则有生效日，题面没有给交易/结算日期。即使个别回答还有引用遗漏，也不应在歧义题上比较模型。
- `CMP-ST-21`、`CMP-ST-22`：后续动作依赖前一步工具结果，但旧 runner 只调用模型一次。四个配置只返回第一步，不能证明观察工具结果后不会继续。

旧机器报告继续作为不可变运行工件保存；其分数、排序、critical 计数和覆盖率不再承担质量结论。新题集与 runner 的门禁见 [`SCIENTIFIC_V2_VALIDITY_REAUDIT_20260820.md`](SCIENTIFIC_V2_VALIDITY_REAUDIT_20260820.md)。

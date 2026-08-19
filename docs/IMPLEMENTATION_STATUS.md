# Implementation Status

> 兼容入口：当前实时状态请以 `PROJECT3_CURRENT_STATUS_20260802.md` 为准；产品和实施规则以 `PROJECT_SPEC.md`、`SCIENTIFIC_EVALUATION_IMPLEMENTATION_PLAN_V3_APPROVED.md` 为准。本文不再保存旧流水线的待办状态。

## Scientific v1

- 数据：38 个分用途实例与 14 份 Judge 固定回答已经生成；25 个正式比较题为 6 / 7 / 5 / 7 四任务包分布；manifest 与 seal 有效。
- 判断：直接核验、弱信号、单次原子 Judge 和候选人最终裁决的权限已经编码；Judge 不具有版本一票否决权。
- 协议：OpenAI-compatible 槽位走 `/responses`；Anthropic adapter 由 LiteLLM 转为原生 `/v1/messages`。项目只传标准 `reasoning_effort`，LiteLLM 自动映射为 adaptive thinking 与 `output_config.effort`；固定 `store=false`、`stream=false`、LiteLLM 内部重试 0，思考强度从本机加密 profile 注入。
- 执行：显式执行 ID、不可变 DAG、224 个计划成功请求、硬错误首次停止、可恢复失败重试到当前请求成功、成功探针收据复用、幂等重进和不明确在途保护均已实现。质量结果不能扩张矩阵。
- 报告：机器初审、Judge 体检报告、匿名复核包、追加式候选人判断和完成后候选人确认报告均已实现；确认报告有完整盲审硬门禁。
- 界面：Streamlit 已增加第六页“科学版匿名盲审”。
- 离线验收：当前 `scientific-v1.7` 的 adapter-native、LiteLLM 原生 max 转发、最小健康检查、Judge advisory 错误与路由熔断合同为 94/94 测试，Ruff、compileall 和封印校验通过。健康检查只发送 `ping`、上限 32，不带思考或结构化参数；任意非空返回即成功。正式 Judge 的解析/字段错误记录为运行错误并继续，不计内容 0 分。证据为 `artifacts/scientific_v1/anthropic_effort_transport_offline_acceptance_20260803.json` 与 `artifacts/scientific_v1/provider_route_guard_offline_acceptance_20260803.json`。

## 旧基线

- 原 40 条主数据、8 条 holdout、DeepEval G-Eval、离线 fixture、历史运行和旧文档保留作工程与失败审计证据。
- 旧 `scripts/run_full_pipeline.ps1` 和旧启动闭环保持在线前硬停止，不得恢复为正式入口。
- 迁移前的 Chat 运行不能与新 Responses Scientific v1 结果直接比较，也不能作为最终质量证据。

## 当前停止点

旧 `scientific-v1.6` 执行已完成 50 个节点后因 Model B 配置模型名不在同一 URL/Key 的目录中而暂停。当前 `scientific-v1.7` 不复用该执行或旧协议收据；必须先恢复同一模型通道或由候选人明确选择替代模型，再用新编号运行有限矩阵。矩阵成功后自动生成机器报告和匿名复核包，并停在候选人本人盲审。候选人完成全部盲审前，不生成最终人工确认结论、不做版本推荐、不晋升真实坏案例。

# Scientific v1 实现影响清单（2026-08-02）

状态：实施前基线审计已完成；本文件只记录工程影响，不改变已批准的产品方向。

## 基线

- `uv run --no-sync pytest -q` 实测 `58 passed`。
- 旧 40/8 数据、旧 G-Eval、旧运行工件与旧三组矩阵继续作为工程和失败历史证据保存。
- `scripts/run_full_pipeline.ps1` 继续硬停止，不恢复旧在线矩阵。
- 当前 Responses 网关、DPAPI profile、凭据不回显和目标身份盲评合同可复用。

## 新增而不覆盖的实现面

1. `datasets/scientific_v1/`：5 个官方锚点、25 个正式比较题、7 个 Judge 验证家族/14 份固定回答、来源台账、回归种子、manifest 与 seal。
2. 科学版 Schema 与数据门禁：数据用途隔离、场景家族防泄漏、许可证/来源字段、`synthetic_draft` 排除和哈希校验。
3. 判断权限与检查器：明确区分 `DIRECT_VERIFIER`、`SIGNAL_ONLY`、`SEMANTIC_REVIEW`、`HUMAN_REQUIRED`；旧 `hard=true` 不再自动取得正式裁决权。
4. 单次原子 Judge：不使用 DeepEval G-Eval 的多请求评分路径；每份答案恰好一次 Responses 请求，严格校验全部预注册原子小项，Judge 不接收目标模型或 Prompt 身份，也不能输出或修改严重程度。
5. 新有限执行器：先冻结 `execution_plan.json`，再按 Provider 探针、技术路径、100 次目标生成、100 次单次 Judge、报告的 DAG 执行；同一执行编号只补缺失节点，不自动创建新一轮。
6. 双层报告与盲审：机器初审报告、匿名候选人复核包、追加式人工确认报告相互分离；运行错误不计内容 0 分，ABSTAIN 降低判断覆盖率但不进分数。
7. CLI、Streamlit、README 与状态文档：只新增 scientific v1 入口和展示；旧入口继续可用于审计复现。

## 必须保留的边界

- 离线校验与测试期间 Provider 请求数必须为 0。
- 真实运行只发送公开/合成题目、上下文、候选输出和原子规则；不发送本地凭据或目标身份给 Judge。
- 内容质量差、低分或 Judge FAIL 不触发重生成、重复评分、扩题或第二 Judge。
- 真实矩阵结束后停在候选人匿名盲审，不代替候选人提交判断。

## 完成结果

- Scientific v1 数据、schema、来源台账、seal、单次原子 Judge、有限执行器、双报告和匿名 UI 已完成。
- 原 58 项基线无退步；当前完整套件 84/84 通过，Ruff、compileall、六页 Streamlit 与 PowerShell 语法通过。
- 完整 224 次假 Responses DAG 和 225 次绝对上限已验证；离线真实 Provider 请求为 0。
- 证据：`artifacts/scientific_v1/offline_acceptance_20260802.json`。

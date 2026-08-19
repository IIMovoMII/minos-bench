# Project 3 当前状态与下一步（2026-08-04）

本文件是 Project 3 的当前阶段入口。产品方向由上级 `PROJECT_SPEC.md` 和 `SCIENTIFIC_EVALUATION_IMPLEMENTATION_PLAN_V3_APPROVED.md` 裁决；执行边界由 `EXECUTION_HANDOFF_V1_20260802.md` 裁决。Scientific v1 以下内容是历史基线；当前活动评测集和执行入口为 Scientific v2。

## 一、项目目的

这是一个面试用、个人可复现的通用 LLM 应用评测工作台。它证明候选人能把业务目标拆成能力、风险、可追溯题目、直接核验、语义初审、人工确认、版本比较和坏案例回归，而不是证明候选人训练过基础模型或建设过生产级平台。

首版覆盖指令生成、资料问答、多轮对话、结构化输出与工具调用，不绑定某一条 JD、采购场景、手机助手或特定模型。

## 二、已完成的 Scientific v1 工程

- `datasets/scientific_v1/` 已生成并封印，共 38 个问题实例：3 个 IFEval 规则开发锚点、2 个 BFCL 技术探针锚点、7 个 Judge 验证家族、25 个正式比较题、1 个合成回归种子；另有 14 份候选人固定 Judge 体检回答。
- 25 个正式题分布为指令生成 6、资料问答 7、多轮 5、结构化/工具 7。旧 16 道无逐题来源草案仍排除，旧 40/8 数据仍只作历史工程基线。
- 来源台账、许可证门禁、数据用途隔离、scenario family 防泄漏、manifest 和 seal 校验已经实现。
- 判断权限已经落地：`DIRECT_VERIFIER` 才能直接形成机械失败；`SIGNAL_ONLY` 只提示关注；语义 Judge 只能按预登记小项判断，不能自行改题或增删标准。原方案保留候选人最终裁决入口；候选人于 2026-08-04 针对本次低风险、固定题集明确采用 Judge-only 终局，因此人工抽检不再是本批次验收门槛。
- 新原子 Judge 固定为每份答案一次逻辑请求，不使用 DeepEval G-Eval 多请求协议，不接收目标身份、Prompt 身份或严重程度，不能新增、合并或遗漏已登记小项。OpenAI-compatible 槽位走 `/responses`；Anthropic adapter 由 LiteLLM 转为原生 `/v1/messages`，项目只传标准 `reasoning_effort=max`，LiteLLM 在线上生成 `thinking.type=adaptive + output_config.effort=max`。
- 新执行器使用显式执行编号和不可变计划。计划包含 224 个成功请求节点；100 次正式目标生成与 100 次正式 Judge 不因质量失败重试或扩张。
- Provider 合同硬错误首次即停；超时、429 和普通 5xx 只重试当前请求，正文明确表示“无可用模型通道”的 503 第一次停止；Judge 体检或正式评分的 JSON/字段合同错误记录为 advisory 运行错误并继续，不计内容 0 分；相同完成执行编号重进不会重复调用；不明确的在途请求不会盲目重发。已成功健康探针可通过协议绑定收据复用，不再重复调用。
- 机器初审、机器最终报告与可选人工抽检分开。运行错误不是内容 0 分，ABSTAIN 降低判断覆盖率，四任务包等权，预登记严重错误单独阻断发布。
- 六页 Streamlit 工作台已统一为中文界面，导航为项目概览、数据与来源、运行评测、结果与比较、单题复核、可选人工抽检；第六页直接展示机器最终结果、四类任务分数、错误等级和逐题比较。
- 可选人工抽检仍隐藏模型、提示词和 Judge 结论，只显示题目、证据、匿名答案和预登记规则；抽检记录追加保存，但不覆盖机器最终报告。

## 三、离线验收结果

2026-08-03 当前 `scientific-v1.7` adapter-native 离线验收已经通过：

- 原基线开始前为 58 项通过；加入 Scientific v1 后 2026-08-02 套件为 84/84。当前保留 adapter-native、Bearer 上下文、普通可恢复失败重试和成功探针收据复用，并把健康检查简化为最小 LiteLLM 非空响应、把 Judge 解析错误改为 advisory、把确定性路由缺失改为首次熔断；完整套件为 94/94 通过，无旧基线非预期退步。
- Ruff、compileall、六页 Streamlit smoke、PowerShell 语法、旧流水线硬停止均通过。2026-08-03 中文界面重做后又执行了一次定向六页冒烟测试和桌面端实机检查，未触发任何真实模型请求；匿名页仍保持身份与机器结论隔离。
- 2026-08-04 恢复链路新增的原子 Judge、派生执行、机器最终报告和入口测试均执行了定向离线验收；当前中文六页冒烟和恢复脚本语法再次通过。未为界面或文档改动重复全套测试。
- 完整 224 次假 Responses DAG、普通文本、资料、多轮、JSON、函数调用与工具回传路径通过。
- 幂等重进、连续临时失败后成功、Provider 硬错误首次熔断、成功探针零请求复用、Judge 合同错误继续执行、未知题号拒绝、报告和盲审包测试通过。
- 离线真实 Provider 请求数为 0。
- 数据 manifest SHA-256：`5d6d862fc18a0ca001c8a01ac2d2dc96f6e2718cf04aa42290d01988cb715db5`。
- 数据 seal SHA-256：`51a7ffdd94f5bde385776f05e0aa1c5f52b40718b9f63a096ea2cddd77fbbc34`。
- 旧失败执行继续绑定各自协议；当前 `scientific-v1.7` 协议 SHA-256：`5674a82c57055cc5ecf16b43b614703cc18c7f6d734a5b24b1851d9f05be4518`。
- 基础 adapter-native 证据：`artifacts/scientific_v1/adapter_native_transport_offline_acceptance_20260803.json`；当前 LiteLLM 原生 max 转发证据：`artifacts/scientific_v1/anthropic_effort_transport_offline_acceptance_20260803.json`。旧 `offline_acceptance_20260802.json` 与两份早期 Claude `/responses` 诊断工件只保留为历史。

离线 fixture 和假 Provider 不是模型质量结果，不得当作真实分数或一致率。

## 四、历史失败根因与恢复终态

### 当前恢复终态

派生执行 `scientific-v1-20260804-v17-recovery-a` 从原执行 `scientific-v1-20260803-v17-a` 复用 213 个已完成节点，只重跑 10 个运行错误或缺失节点。最低需要 10 次新请求，实际产生 12 次；多出的 2 次都是正式 Judge 请求首次收到 HTTP 502 后的当前节点重试，没有重复调用任何已经成功的模型结果。

恢复执行现为 227/227 节点完成，100/100 个正式目标输出和 100/100 个正式 Judge 结果齐全，运行完成率和判断覆盖率均为 100%。14 份 Judge 固定体检全部完成，与候选人固定参考的补充一致率为 100%；该参考不是专家金标，因此只能证明 Judge 在本项目固定体检上的可用性，不能外推为通用客观准确率。

机器最终报告已生成于 `artifacts/scientific_v1/executions/scientific-v1-20260804-v17-recovery-a/machine_final_report.json`。原始失败执行、失败响应分类和恢复来源映射保持不可变，恢复过程没有把运行错误改写成内容失败，也没有覆盖旧工件。

本次恢复采用两层保守机制：Provider 超时/普通 5xx 只重试当前缺失请求；Judge 只有在尚未取得合法判断合同的情况下才允许一次合同重试。一旦得到合法 PASS/FAIL 就不再二次评分。对已知无害的、值完全匹配协议版本的冗余字段可以安全剥离，其他多余字段和语义矛盾仍拒绝解析。

### 历史根因

旧执行 `scientific-v1-20260802-a` 仍是不可恢复的历史终态：它在第二目标逻辑槽位旧 `/responses` 路由连续 HTTP 500 后停止，共 3 次请求、2 个完成节点，未进入技术探针、Judge 体检或正式矩阵，也没有质量结论。其原始状态和计划继续保留，不回写、不伪装成功。

后续排查先证明“只改 Claude 思考字段、仍走 OpenAI-compatible `/responses`”不能解决 500；中转站提供的 Claude Code 配置随后给出决定性线索。最终确认的根因是 adapter/协议路由冲突，而不是普通断网、RAG 语料、评测提示词或模型能力：

- OpenAI-compatible 槽位继续使用带 `/v1` 的 Base URL 和 `/responses`；
- Claude 槽位改为 Anthropic adapter，profile 保存根 Base URL；
- 项目代码仍通过统一 LiteLLM Responses 界面调用，LiteLLM 在线上转换为 `/v1/messages`；
- Claude 中转 Key 只在请求上下文内作为 `ANTHROPIC_AUTH_TOKEN` 使用，形成 Bearer 鉴权；可能冲突的环境变量会被临时清除并在请求结束或取消后恢复；
- Anthropic 使用顶层 `output_config.effort=max`，OpenAI-compatible 使用 `reasoning.effort=max`。

修正后，Model B、Judge 和较弱模型均取得成功非空响应；Model A 的传输和 profile 未改变，因此复用旧执行中的成功节点。四个逻辑槽位各有一份成功响应收据，实际模型身份和凭据均未写入收据：`artifacts/scientific_v1/provider_probe_receipts_20260803.json`。当前收据只证明 API 连通，不证明 Judge 合同或评分质量。

为满足“成功模型最多探测一次”，新命令 `scientific-import-provider-probes` 会在执行开始前核对协议 hash、四槽完整性和无身份/凭据标记，并把四个 Provider probe 节点登记为完成、`actual_requests=0`。新正式执行因此不会再次调用已成功健康探针；技术探针、14 份 Judge 体检和正式 100+100 仍按冻结矩阵运行，它们不是重复健康探针。

候选人最新授权超时、429、5xx 等可恢复失败持续重试到当前请求成功。执行器已实现指数退避（封顶 15 秒），但 400/401/403/404/405/422、鉴权、端点和不支持参数等合同错误仍在第一次停止。成功节点图仍固定，质量结果不会触发额外生成、扩题、第二 Judge 或自动新执行；只是网络失败尝试不再有绝对上限。

第一次 adapter-native 新执行 `scientific-v1-20260803-native-a` 完成全部技术探针，并完成前两份 Judge 固定体检；第 3 份体检收到响应后发生 `AtomicJudgeParseError`，按当时合同门禁在总计 9 个新请求、13 个完成节点时停止，未进入正式 100+100。该失败不是网络错误；原始失败响应当时未落盘，所以只能确认错误类别，不能编造具体漏了哪个字段。对同一固定标本的隔离复现随后返回完整、正确的两项 JSON，排除了固定题目或参考答案必现错误，支持自由文本 JSON 合同偶发漂移。

历史 `scientific-v1.4` 曾改用 Provider 层结构化输出；在线隔离诊断一次成功，安全证据为 `artifacts/scientific_v1/diagnostics/judge-contract-JV-GQ-04-FAIL-structured-20260803.json`。这只证明该次请求和结构化返回成功，不证明它适合作为 API 健康门禁；该机制已从当前活动路径回退。

第二次新执行 `scientific-v1-20260803-structured-a` 跨过此前失败点并完成 8 份 Judge 体检，但 `JV-IG-02-PASS` 返回的 JSON 虽符合结构 Schema，仍违反本地跨字段语义组合，执行按当时规则在 14 个新请求、18 个完成节点时停止，仍未进入正式 100+100。同一标本随后隔离复现为完整 `PASS + SUFFICIENT`，再次证明这是非必现 Judge 字段组合漂移，而不是固定题目必错。

历史 `scientific-v1.5` 又加入保守跨字段归一化。它不猜测 PASS/FAIL，但会改写模型原始字段，因此也已从当前活动路径回退；旧执行、隔离诊断和计划只保留作审计，不能当成当前结果。

当前 `scientific-v1.6` 把两件事彻底拆开：Provider 健康检查只通过 LiteLLM 发送 `ping`，输出上限 32，不带思考或结构化参数，任意非空响应即成功；正式 Judge 仍按提示词请求 JSON，但解析或字段合同失败只记 `RUNTIME_ERROR` 并继续，不补问、不改写成 PASS/FAIL。已有四槽成功响应满足这一更弱标准，因此本次回退没有新增任何在线请求。

费用争议后曾暂停真实调用；候选人随后于 2026-08-03 明确要求恢复 Planner 任务，并授权继续当前协议的有限真实矩阵，同时要求 API 异常优先排查本地实现。

新执行 `scientific-v1-20260803-v16-a` 已建立并绑定 `scientific-v1.6`：四槽成功收据导入 4 个节点，新增 Provider 请求 0；6 个技术路径全部完成；14 份 Judge 体检中 13 份完整，1 份收到非空响应但返回 JSON 缺少分隔符，本地按批准规则记为 `AtomicJudgeParseError / RUNTIME_ERROR` 后继续；第一目标配置 25/25 输出已完成。当前尚无机器报告或匿名盲审包。

执行在第二目标槽位首题持续收到 HTTP 503。候选人澄清 Model B 与 Judge 本来就应当使用同一 URL、同一 Key、不同模型名；本地安全核对确认当前 profile 正是这一关系，不存在 Key 对调。去除思考参数和长 Prompt 的最小 `ping`、临时切回 OpenAI-compatible `/responses`、以及 Anthropic 原生路径改用显式 `api_key` 三条路径均返回 503，排除了题目内容、输出长度、思考字段、`/responses`/`/messages` 选择和 Bearer/显式 Key 鉴权形状。

决定性证据来自同一 URL/Key 的只读模型目录：HTTP 200、共返回 11 个可见模型；Judge 配置的模型名存在，Model B 配置的模型名不存在。失败正文的本地分类同时命中“无可用 channel / 模型不可用”，原文、模型身份、URL 和凭据均未落盘。因此当前根因不是 Judge 可用性、普通网络、LiteLLM、Prompt 或 Key 本身失效，而是该 URL/Key 当前没有 Model B 所配置模型名的可用中转通道。

旧实现只看 HTTP 503，按候选人当时的“可恢复 5xx 持续重试”授权把确定性路由缺失也误归为临时故障，造成同一节点空转。进程已在 50 个完成节点、191 次请求、146 次临时重试时人工暂停；最后一次失败已经落事件且进程当时处于退避间隔，所以在途标记被安全清除，已完成工件全部保留。随后 Claude effort 传输合同升级为 `scientific-v1.7`，旧 v1.6 执行现已封为 `stopped_hard`，不得恢复；无论原通道恢复还是替换模型，都必须创建新执行，不能把两个协议或实验对象混入同一结果。

执行器现已增加安全分类：503 正文明确表示无可用模型通道时，返回不含原文的 `hard_provider_route / no_available_model_channel`，第一次即停；普通超时、429 和不含该确定性语义的 5xx 仍按既定策略重试。真实最小失败探针已验证新分类，完整 94/94 离线测试、Ruff 与 compileall 通过。证据为 `artifacts/scientific_v1/provider_route_guard_offline_acceptance_20260803.json`。

候选人随后指出中转后台显示 `/v1/messages`，但没有显示 `max` 档位。离线抓包确认旧项目手工传入的 `output_config.effort=max` 确实到达请求正文，但合同没有同时证明 adaptive thinking。当前 `scientific-v1.7` 已简化为 LiteLLM 原生映射：项目向 Claude adapter 只传 `reasoning_effort=max`，本机 LiteLLM 1.94.0 自动发往 `/v1/messages`，并同时生成 `thinking.type=adaptive` 与 `output_config.effort=max`；线上正文不保留兼容字段 `reasoning_effort`。健康探针仍删除全部思考字段。该变更只经本地 HTTP 合同验证，没有新增真实模型请求；中转后台是否展示 effort 仍取决于其日志 UI，不能以 UI 缺列反推字段未发送。

本轮另发现并修复一个纯本地 CLI 缺陷：执行计划已建立但 state 尚未生成时，`scientific-status` 原会抛 traceback；现在会安全返回 `planned`、已完成节点和请求数。该修复与路由熔断均已进入上述 94/94 完整回归。

中转目录当前只提供同系列至 `claude-opus-4-8`，候选人已明确要求将 Model B 改为该版本。本机加密 profile 已只替换模型名，URL、Key、adapter、协议与 `max` 均未改变。随后按最小验证规则只执行 1 次真实请求：`ping`、输出上限 32、`reasoning_effort=max`，结果 `completed`、非空响应、usage 存在、延迟 5413 ms。此前 503 因而已裁决为中转模型通道下架，不是本地 LiteLLM 或 Prompt 故障；证据为 `artifacts/scientific_v1/model_b_effort_probe_v17_20260803.json`。

`scientific-v1.7` 的全新执行 `scientific-v1-20260803-v17-a` 现已完成：227/227 个执行图节点落盘，计划基础请求 224，实际请求 245，普通 5xx/连接失败的当前请求重试 27 次。四个 Provider probe 使用协议绑定收据导入，新增请求 0；成功节点没有重放。

100 个正式目标节点中 98 个成功。Model B 的 `CMP-ST-04` 与 `CMP-ST-07` 各收到一次 HTTP 400；两题前后同配置的其他工具题继续成功，且相同非流式 Claude 工具路径已经成功，因此裁决为中转翻译或内容/工具组合的样本级 Provider 拒绝，而不是整个模型、`/v1/messages`、max 档位或 `stream=false` 失效。执行器已改为：正式目标生成的单题 400 记录 `RUNTIME_ERROR` 后继续，连续 3 题运行错误仍熔断；探针、Judge 和确定性路由错误的全局门禁不变。该改动只运行一个直接相关单测和 changed-file Ruff，均通过，没有重跑完整 94 项套件，也没有再次调用两道失败题。

原执行的 100 个正式 Judge 节点中 94 个完成，6 个保留为可审计运行错误；运行错误没有计内容 0 分。该状态现已由上述派生恢复执行补齐，原执行本身仍保持不变。

## 五、2026-08-04 评测集难度复核与 V2 方向

Scientific v1 的工程闭环和原始运行工件继续有效，但 25 道正式题不再承担模型能力比较：20/25 道题四个配置全部满分，只有 5 道产生非满分结果，存在明显天花板效应。另确认 `list_item_count` 默认正则会把 Markdown 加粗行误识别为项目符号；该问题属于本地检查器缺陷，不是目标模型失败。

最新来源审计已在 `research/PROJECT3_BENCHMARK_SOURCE_AUDIT_20260802.md` 补充。下一版建议保留现有 25 题为 D1 冒烟/离线回归，另建 24 道全新比较题：4 个任务包 × 3 个官方基准支持的风险格 × 每格 1 道 D2 边界题和 1 道 D3 困难题。四配置正式矩阵为 96 次目标生成和 96 次单 Judge，共 192 次内容调用；同一配置与题目只成功生成一次，不做重复采样、多 Judge、反向排序或质量触发重跑。

本段记录的是 V2 实施前状态，已由下一节取代。Scientific v1 的 93.73、90.24、90.04、90.16 只作为历史参考分，不再用于声称四个配置具有稳定、可推广的能力排序。

## 六、2026-08-04 Scientific v2 已冻结并完成正式矩阵

V2 已完成从来源审计到可执行工件的转换，上一段“尚未创建”的内容是历史记录，不再描述当前状态：

- `datasets/scientific_v2/` 已封印 37 个实例：24 个全新正式比较题、3 个规则开发锚点、2 个技术探针、7 个 Judge 验证家族和 1 个明确标注的合成回归种子；正式比较题四包各 6 题。
- 24 题覆盖 12 个风险格，每格一题 D2、一题 D3；场景家族、输入签名唯一；gold 通过直接检查，反例至少触发一条登记的直接失败。
- V2 manifest：`3cd5c60f3aae6d57c2622409ad8b4946f66e80506da75a6c25e474247ee18efc`；seal：`4c610a10c3f8667fbfafd9f343256efa9b1ac944b93209ddc4f3f5bf5da4387a`；来源审计 hash：`cc66017c24d0364daff1b8a5371f5cc091c34fbafe683ebde5bdc82f5eb5688b`。
- 活动协议 `configs/scientific_v2.json` hash：`018a0a08ba1dcd5e1dc7e31d86113cc900ce41281bb4b2a27a0582d81174cc94`；计划为 4 次最小 Provider probe、96 次目标生成、96 次单次 Judge，计划基数 196；技术探针和本轮 Judge 体检按批准方案复用既有验收，不重复调用。
- 当前离线门禁、V1 历史审计、V2 数据审计、V2 计划与重试边界相关的 41 项定向测试通过，Ruff、compileall 和 PowerShell 入口解析通过；离线 Provider 请求数为 0。
- 空或不完整的目标响应最多在当前节点重试一次；API/Provider 运行错误可由派生恢复只补跑错误节点。已经保存的非空回答，无论 Judge 之后判定 PASS、FAIL 还是需要关注，都不会因“质量不好”重生成或重判。
- 目标模型身份、Prompt 身份和 Judge 结论仍隐藏在盲审包；机器最终报告在 V2 中明确标注“复用既有 Judge 引擎验收”，不会把本轮未重复体检显示为 0 分。
- 正式执行 `scientific-v2-20260804-a` 已完成 96/96 个目标节点，覆盖 24 题 × 4 个匿名配置。96 份输出均有实质内容：76 份含自然语言正文，20 份含工具调用；其中部分工具调用题没有自然语言正文，但工具调用和环境状态完整，因此真正空输出为 0。
- 目标阶段实际请求 100 次，4 个节点只因空响应或 API 运行失败在当前节点恢复；没有任何节点因答案质量、得分或 Judge 结论而重答。匿名包已保存 96 项。
- 原执行的 Judge 阶段只有 1/96 个合法结果，其余 95 个为上游路由/API 运行错误。`recovery-1` 复用 101 个成功节点、只补 95 个缺口，达到 57/96 个合法 Judge；剩余 39 个中 38 个为 JSON 解析错误、1 个为 502。原执行及各恢复执行均保持不可变。
- 对失败工件的逐项诊断确认：自由文本 Judge 会在 `reason` 内写入未转义的 ASCII 双引号，导致完整但语法非法的 JSON。仅加强提示词和增加一次纠错请求后，`recovery-2` 虽把合法 Judge 提升到 91/96，仍留下 4 个解析错误和 1 个连接错误，因此“继续改提示词”不能稳定解决根因。
- 活动代码现按 Provider adapter 使用原生结构化输出：Anthropic 走顶层 `output_format=json_schema`，同时保留 LiteLLM `reasoning_effort=max` 到 `/v1/messages` 的 adaptive thinking；其他 Responses adapter 走 Pydantic `text_format`。Schema 只约束序列化，匿名输入、预登记小项、Judge 模型、`max` 档位和本地严格语义校验均未改变。在线最小探针和 15 个定向测试证明该合同有效。
- `recovery-3` 复用 191 个成功节点、只补 5 个缺口，以 9 次请求取得 4 个合法判断，余下 1 个为 `BadGatewayError`；`recovery-4` 再复用 195 个成功节点，仅用 1 次请求补齐最后缺口。最终执行图为 200/200 节点、96/96 目标输出、96/96 合法 Judge、0 个运行错误；整个恢复链没有重放目标答案，也没有重判已有合法结果。
- 机器最终报告已生成于 `artifacts/scientific_v2/executions/scientific-v2-20260804-a-recovery-4/machine_final_report.json`。四个匿名配置参考总分依次为 87.92、82.43、85.83、85.21；D2/D3 分层和风险格统计均已落盘。四个配置都存在预登记严重错误并标记为发布阻断；该分数只适用于当前题集、当前规则和当前单 Judge，不是客观真值或通用模型排名。
- 判断覆盖率为 99.73%，低于 100% 来自一个合法 `ABSTAIN`，不是缺失 Judge 结果。96 项匿名抽检包仍保留，但按候选人批准的本批次 Judge-only 政策不阻塞机器报告。

## 七、面试主张边界

当前可以如实说：题型和评测方法参考 IFEval、BFCL 及 RAG、多轮、工具环境和 Judge 相关公开工作；项目按许可证与方法迁移边界建立逐题来源台账；实现了分用途数据、直接核验/弱信号/语义初审/人工确认权限、有限执行 DAG、机器/人工双报告和匿名复核。

当前真实证据可以证明：Scientific v2 的固定执行图已通过追加式派生恢复达到 200/200，96/96 个冻结目标输出和 96/96 个合法 Judge 结果齐全；自由文本 JSON 漂移、连接错误和普通网关错误被独立记录，没有冒充内容质量失败。四个匿名配置的 V2 参考总分为 87.92、82.43、85.83、85.21，均存在至少一个预登记严重错误并标记为发布阻断；高平均分不能抵消严重错误。Scientific v1 的 93.73、90.24、90.04、90.16 仅保留为旧 D1 题集历史结果。

当前机器最终报告可以用于本项目面试讲解和内部版本比较，但不能称为客观真值、生产效果、官方 benchmark 成绩或通用模型排名。项目使用公开与合成数据，不是企业生产系统，不代表真实流量、团队管理或已测 ROI。

候选人不再需要完成 100 项人工盲审才能形成当前结论；人工抽检只作为可选审计。候选人仍须亲自完成真实坏案例解释、启动复现和无稿口头解释。Codex/AI 辅助完成的研究、数据、代码、测试和自动化不得冒充候选人手写工程经历。

面试准备入口：`research/MODEL_EVAL_INTERVIEW_GUIDE_20260805.md`；本轮岗位、面经和公开方法检索记录：`research/PROJECT3_INTERVIEW_RESEARCH_20260805.md`。

## 八、2026-08-19 本地公开候选版

Project 3 已新增 Windows 一键启动和页面内模型配置，但尚未发布到 GitHub：

- 双击 `启动评测工作台.cmd` 会检查锁文件环境、按需同步 `.venv`、载入仓库外 DPAPI profile，并把 Streamlit 绑定在 `127.0.0.1`；没有 `uv` 时必须先由操作者确认，才在 `.bootstrap/` 内安装。
- 工作台新增“模型配置”页，支持实际模型 ID、OpenAI-compatible Responses / Anthropic Messages / 其他 LiteLLM provider、Base URL、Key 与思考强度。Chat Completions 仍禁用。
- 快速体验只配置一个目标模型与一个 Judge，三个目标逻辑槽位会相同，只能验证链路；正式比较必须使用完整四槽，不能把快速模式包装成模型对比。
- Key 和完整 URL 不进入命令行参数、不在 UI 预填或回显；Windows 继续用当前用户 DPAPI 加密。该实现是本机单用户设计，不支持公网多租户部署。
- `.gitignore` 已排除本地环境、缓存、`.env*`、Streamlit secrets 与原始运行工件，只允许一份身份盲机器最终报告进入公开候选。临时 Git 索引测得候选为 145 个文件、2.11 MiB；本地目录为 528.40 MiB，其中 `.venv` 占 516.05 MiB，不会进入仓库。
- 6 项 profile bridge 测试与 3 项入口/UI 定向测试通过；Ruff、compileall 和 Windows PowerShell 5.1 解析通过。真实 Provider 请求为 0，没有重跑 Scientific v2。
- 项目目录仍未正式 `git init`，也没有 `LICENSE`、远端仓库或 push。许可证与仓库名称需要候选人确认后才能产生外部发布状态。

公开版实施与剩余项：`docs/PUBLIC_RELEASE_AND_ONE_CLICK_20260819.md`；公开仓库内的 GitHub 复查证据：`docs/GITHUB_REFERENCE_AUDIT_20260819.md`。求职工作区完整研究记录另见根目录 `research/PROJECT3_GITHUB_RELEASE_EVIDENCE_20260819.md`。

## 九、2026-08-20 Minos Bench 公开发布

- 项目公开名称确定为 **Minos Bench（米诺斯审判台）**，仓库地址为 `https://github.com/IIMovoMII/minos-bench`，可见性为 public，许可证为 MIT。
- GitHub 首页、仓库描述和安全说明使用中文；MIT 法律文本按标准版本保留英文。
- 首次公开提交沿用精确允许列表：源码、测试、冻结数据、中文项目文档和一份身份盲机器最终报告可以进入 Git；本地 DPAPI profile、真实 Key/完整 URL、`.env*`、Streamlit secrets、原始逐题执行、缓存和本机环境保持排除。
- 仓库发布只改变品牌、公开说明和 Git 交付状态，没有修改 Scientific v2 的题目、Judge、结果或面试数字，也没有运行真实模型。
- 公开后可以如实说明“项目已在 GitHub 以 MIT License 开源”；仍不能声称生产部署、真实业务数据、官方 Benchmark 成绩或候选人独立手写全部代码。

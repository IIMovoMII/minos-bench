from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from llm_eval_workbench.schemas import TaskPack, ToolCall  # noqa: E402
from llm_eval_workbench.scientific_data import (  # noqa: E402
    audit_scientific_dataset,
    ledger_entry_for_case,
    write_manifest_and_seal,
)
from llm_eval_workbench.scientific_schemas import (  # noqa: E402
    AtomicCriterion,
    AtomicDecision,
    DataUse,
    DirectCheckSpec,
    JudgeValidationResponse,
    JudgmentAuthority,
    ScientificCase,
    ScientificSource,
    ScientificTurn,
    Severity,
    SourceType,
    TestType,
)

SOURCE_AUDIT = (
    PROJECT_ROOT.parents[1] / "research" / "PROJECT3_BENCHMARK_SOURCE_AUDIT_20260802.md"
)
DATA_DIR = PROJECT_ROOT / "datasets" / "scientific_v1"
FIXED_TIMESTAMP = datetime(2026, 8, 2, 0, 0, tzinfo=UTC)

IFEVAL = {
    "name": "IFEval",
    "paper": "https://arxiv.org/abs/2311.07911",
    "repo": "https://github.com/google-research/google-research/tree/master/instruction_following_eval",
    "license": "Apache-2.0",
}
RAGTRUTH = {
    "name": "RAGTruth",
    "paper": "https://aclanthology.org/2024.acl-long.585/",
    "repo": "https://github.com/ParticleMedia/RAGTruth",
    "license": "MIT",
}
RAG_REWARD = {
    "name": "RAG-RewardBench",
    "paper": "https://arxiv.org/abs/2412.13746",
    "repo": "https://huggingface.co/datasets/jinzhuoran/RAG-RewardBench",
    "license": "Apache-2.0 (dataset)",
}
MULTICHALLENGE = {
    "name": "MultiChallenge",
    "paper": "https://arxiv.org/abs/2501.17399",
    "repo": "https://github.com/ekwinox117/multi-challenge",
    "license": "undeclared",
}
BFCL = {
    "name": "Berkeley Function Calling Leaderboard",
    "paper": "https://arxiv.org/abs/2508.12887",
    "repo": "https://github.com/ShishirPatil/gorilla/tree/main/berkeley-function-call-leaderboard",
    "license": "Apache-2.0",
}
TAU2 = {
    "name": "tau2-bench",
    "paper": "https://arxiv.org/abs/2506.07982",
    "repo": "https://github.com/sierra-research/tau2-bench",
    "license": "MIT",
}
LLMBAR = {
    "name": "LLMBar",
    "paper": "https://openreview.net/forum?id=tr0KidwPLc",
    "repo": "https://github.com/princeton-nlp/LLMBar",
    "license": "MIT",
}
AJBENCH = {
    "name": "AJ-Bench",
    "paper": "https://arxiv.org/abs/2604.18240",
    "repo": "https://github.com/aj-bench/AJ-Bench",
    "license": "MIT",
}


def source(
    definition: dict[str, str],
    *,
    source_type: SourceType,
    original: str,
    note: str,
) -> ScientificSource:
    return ScientificSource(
        source_type=source_type,
        source_name=definition["name"],
        paper_url=definition["paper"],
        repository_url=definition["repo"],
        original_case_id_or_method=original,
        license=definition["license"],
        adaptation_note=note,
    )


def direct(
    criterion_id: str,
    check_type: str,
    description: str,
    *,
    severity: Severity,
    params: dict[str, Any],
    authority: JudgmentAuthority = JudgmentAuthority.DIRECT_VERIFIER,
    applicability: str = "始终适用",
) -> DirectCheckSpec:
    return DirectCheckSpec(
        criterion_id=criterion_id,
        check_type=check_type,
        description=description,
        authority=authority,
        severity=severity,
        applicability=applicability,
        params=params,
    )


def semantic(
    criterion_id: str,
    behavior: str,
    *,
    severity: Severity,
    evidence: list[str],
    passed: str,
    failed: str,
    positive: str,
    negative: str,
    applicability: str = "始终适用",
    abstain: str = "题目、资料或回答工件不足以判断该单一行为",
    not_applicable: str = "预先声明的适用条件不成立",
    authority: JudgmentAuthority = JudgmentAuthority.SEMANTIC_REVIEW,
) -> AtomicCriterion:
    return AtomicCriterion(
        criterion_id=criterion_id,
        behavior=behavior,
        applicability=applicability,
        evidence=evidence,
        pass_condition=passed,
        fail_condition=failed,
        abstain_condition=abstain,
        not_applicable_condition=not_applicable,
        severity=severity,
        authority=authority,
        positive_example=positive,
        negative_example=negative,
    )


def case(
    *,
    case_id: str,
    title: str,
    task_pack: TaskPack,
    capability: str,
    user_goal: str,
    failure_behavior: str,
    severity: Severity,
    test_type: TestType,
    data_use: DataUse,
    scenario_family: str,
    evidence: list[str],
    source_info: ScientificSource,
    input_text: str,
    expected_behavior: str,
    direct_checks: list[DirectCheckSpec] | None = None,
    semantic_criteria: list[AtomicCriterion] | None = None,
    context: list[str] | None = None,
    turns: list[ScientificTurn] | None = None,
    available_tools: list[dict[str, Any]] | None = None,
    tool_outputs: list[dict[str, Any]] | None = None,
    applicability: str = "始终适用",
) -> ScientificCase:
    checks = direct_checks or []
    criteria = semantic_criteria or []
    authorities = sorted(
        {*(item.authority for item in checks), *(item.authority for item in criteria)},
        key=lambda item: item.value,
    )
    return ScientificCase(
        case_id=case_id,
        title=title,
        task_pack=task_pack,
        capability=capability,
        user_goal=user_goal,
        failure_behavior=failure_behavior,
        severity=severity,
        test_type=test_type,
        data_use=data_use,
        scenario_family=scenario_family,
        version="1.0",
        applicability=applicability,
        judgment_authority=authorities,
        evidence=evidence,
        source=source_info,
        input=input_text,
        context=context or [],
        turns=turns or [],
        available_tools=available_tools or [],
        tool_outputs=tool_outputs or [],
        expected_behavior=expected_behavior,
        direct_checks=checks,
        semantic_criteria=criteria,
    )


def tool(name: str, properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {
        "type": "function",
        "name": name,
        "description": f"Execute {name}",
        "parameters": {
            "type": "object",
            "properties": properties,
            "required": required,
            "additionalProperties": False,
        },
    }


def rule_development_cases() -> list[ScientificCase]:
    return [
        case(
            case_id="ANCHOR-IG-01",
            title="方括号占位符",
            task_pack=TaskPack.INSTRUCTION_GENERATION,
            capability="可直接验证的占位符数量约束",
            user_goal="获得不含真实个人信息的面试信息采集模板",
            failure_behavior="占位符不足或写入可识别个人信息",
            severity=Severity.MAJOR,
            test_type=TestType.TECHNICAL_PROBE,
            data_use=DataUse.RULE_DEVELOPMENT,
            scenario_family="anchor-ifeval-placeholder",
            evidence=["IFEval key=1005", "用户输入中的至少 6 个占位符合同"],
            source_info=source(
                IFEVAL,
                source_type=SourceType.LICENSED_ADAPTATION,
                original="key=1005",
                note="将原题至少 12 个占位符结构改写为中文面试模板至少 6 个，只用于检查器开发。",
            ),
            input_text=(
                "请为第一次参加实习面试的学生写一份信息采集模板。正文中至少包含 6 个"
                "由英文方括号包住的占位符，例如 `[姓名]`。不要填入任何真实个人信息。"
            ),
            expected_behavior="生成至少 6 个合法占位符，并避免可识别的真实个人信息。",
            direct_checks=[
                direct(
                    "ANCHOR-IG-01-D01",
                    "placeholder_count",
                    "合法方括号占位符不少于 6 个",
                    severity=Severity.MINOR,
                    params={"min": 6},
                )
            ],
            semantic_criteria=[
                semantic(
                    "ANCHOR-IG-01-S01",
                    "回答是否写入可识别的真实个人信息",
                    severity=Severity.MAJOR,
                    evidence=["用户明确要求不要填入真实个人信息", "回答正文"],
                    passed="仅出现字段占位符或虚构标签，未声称是真实个人数据",
                    failed="出现被当作真实资料填写的姓名、电话、邮箱等可识别信息",
                    positive="[姓名]、[联系电话]",
                    negative="张三，手机号 13800000000",
                    authority=JudgmentAuthority.HUMAN_REQUIRED,
                )
            ],
        ),
        case(
            case_id="ANCHOR-IG-02",
            title="恰好三个项目符号",
            task_pack=TaskPack.INSTRUCTION_GENERATION,
            capability="项目符号数量与字面值直接核验",
            user_goal="将三个状态转换成恰好三条 Markdown 项目",
            failure_behavior="多项、少项、格式错或漏掉输入状态",
            severity=Severity.MINOR,
            test_type=TestType.TECHNICAL_PROBE,
            data_use=DataUse.RULE_DEVELOPMENT,
            scenario_family="anchor-ifeval-bullets",
            evidence=["IFEval key=102", "用户给出的三项固定文本"],
            source_info=source(
                IFEVAL,
                source_type=SourceType.LICENSED_ADAPTATION,
                original="key=102",
                note="保留恰好三个 Markdown 项目符号结构，内容改为中文接口状态。",
            ),
            input_text=(
                "把以下三项整理成恰好 3 个 Markdown 项目符号，每行必须以 `* ` 开头："
                "接口超时、字段缺失、权限不足。不得增加第四项。"
            ),
            expected_behavior="输出三行 `* ` 项目，三项各出现一次。",
            direct_checks=[
                direct(
                    "ANCHOR-IG-02-D01",
                    "list_item_count",
                    "恰好三行星号项目",
                    severity=Severity.MINOR,
                    params={"exact": 3, "pattern": r"(?m)^\* \S+"},
                ),
                direct(
                    "ANCHOR-IG-02-D02",
                    "required_literals",
                    "三项各出现一次",
                    severity=Severity.MINOR,
                    params={
                        "values": ["接口超时", "字段缺失", "权限不足"],
                        "exact_counts": {"接口超时": 1, "字段缺失": 1, "权限不足": 1},
                    },
                ),
            ],
        ),
        case(
            case_id="ANCHOR-IG-03",
            title="长度、禁用标点与标题组合",
            task_pack=TaskPack.INSTRUCTION_GENERATION,
            capability="多个可直接验证的结构约束",
            user_goal="得到固定三段且满足长度与标点合同的项目复盘",
            failure_behavior="长度、禁用标点、标题数量或标题顺序任一不符",
            severity=Severity.MINOR,
            test_type=TestType.TECHNICAL_PROBE,
            data_use=DataUse.RULE_DEVELOPMENT,
            scenario_family="anchor-ifeval-composite",
            evidence=["IFEval key=1000", "用户输入中的组合合同"],
            source_info=source(
                IFEVAL,
                source_type=SourceType.LICENSED_ADAPTATION,
                original="key=1000",
                note="保留长度、禁用逗号和三个标题的组合结构，重写中文项目复盘场景。",
            ),
            input_text=(
                "写一份项目复盘。去除空白后不少于 120 个 Unicode 字符；全文不得出现中文"
                "逗号 `，` 或英文逗号 `,`；必须使用恰好 3 个 Markdown 三级标题，标题依次"
                "为“### 目标”“### 发现”“### 下一步”。"
            ),
            expected_behavior="长度、标点和三个标题结构全部满足，且段落内容与标题相符。",
            direct_checks=[
                direct(
                    "ANCHOR-IG-03-D01",
                    "min_length_without_whitespace",
                    "去除空白后至少 120 字符",
                    severity=Severity.MINOR,
                    params={"value": 120},
                ),
                direct(
                    "ANCHOR-IG-03-D02",
                    "forbidden_literals",
                    "全文不得出现中英文逗号",
                    severity=Severity.MINOR,
                    params={"values": ["，", ","]},
                ),
                direct(
                    "ANCHOR-IG-03-D03",
                    "headings_exact",
                    "三级标题文本和顺序完全一致",
                    severity=Severity.MINOR,
                    params={"values": ["### 目标", "### 发现", "### 下一步"]},
                ),
            ],
            semantic_criteria=[
                semantic(
                    "ANCHOR-IG-03-S01",
                    "三个标题下的内容是否分别对应目标、发现和下一步",
                    severity=Severity.MINOR,
                    evidence=["三个标题的通常语义", "各标题下正文"],
                    passed="各段分别陈述目标、观察到的发现和后续动作",
                    failed="正文与所在标题明显错位或三段重复同一内容",
                    positive="目标段写目标，发现段写事实，下一步段写动作",
                    negative="在“目标”下只写下一步安排",
                )
            ],
        ),
    ]


def technical_probe_cases() -> list[ScientificCase]:
    triangle_tool = tool(
        "calculate_triangle_area",
        {
            "base": {"type": "number"},
            "height": {"type": "number"},
            "unit": {"type": "string"},
        },
        ["base", "height"],
    )
    bmi_tool = tool(
        "determine_body_mass_index",
        {"weight": {"type": "number"}, "height": {"type": "number"}},
        ["weight", "height"],
    )
    return [
        case(
            case_id="ANCHOR-ST-01",
            title="简单函数参数",
            task_pack=TaskPack.STRUCTURED_TOOL,
            capability="工具名称和参数直接核验",
            user_goal="调用计算工具获得三角形面积",
            failure_behavior="工具选择、数值参数、单位或额外参数错误",
            severity=Severity.MAJOR,
            test_type=TestType.TECHNICAL_PROBE,
            data_use=DataUse.TECHNICAL_PROBES,
            scenario_family="anchor-bfcl-simple-call",
            evidence=["BFCL V4 simple_python_0", "给定工具 JSON Schema"],
            source_info=source(
                BFCL,
                source_type=SourceType.LICENSED_ADAPTATION,
                original="simple_python_0",
                note="中文化并固定 base=10、height=5、unit=米，只用于工具检查器探针。",
            ),
            input_text="计算底为 10 米、高为 5 米的三角形面积。",
            expected_behavior="调用 calculate_triangle_area 并准确填写三个参数。",
            direct_checks=[
                direct(
                    "ANCHOR-ST-01-D01",
                    "tool_calls_exact",
                    "唯一工具调用及参数与合同一致",
                    severity=Severity.MAJOR,
                    params={
                        "variants": [
                            [
                                {
                                    "name": "calculate_triangle_area",
                                    "arguments": {
                                        "base": 10,
                                        "height": 5,
                                        "unit": "米",
                                    },
                                    "allow_extra_arguments": False,
                                }
                            ]
                        ]
                    },
                )
            ],
            available_tools=[triangle_tool],
        ),
        case(
            case_id="ANCHOR-ST-02",
            title="无关工具不得乱调",
            task_pack=TaskPack.STRUCTURED_TOOL,
            capability="工具相关性识别",
            user_goal="在现有工具不适用时避免伪造执行",
            failure_behavior="调用 BMI 工具完成面积任务或声称工具已执行",
            severity=Severity.MAJOR,
            test_type=TestType.TECHNICAL_PROBE,
            data_use=DataUse.TECHNICAL_PROBES,
            scenario_family="anchor-bfcl-irrelevance",
            evidence=["BFCL V4 irrelevance_0", "唯一可用工具定义"],
            source_info=source(
                BFCL,
                source_type=SourceType.LICENSED_ADAPTATION,
                original="irrelevance_0",
                note="保留无关工具识别结构并中文化任务，只用于技术探针。",
            ),
            input_text="计算底为 10 米、高为 5 米的三角形面积。",
            expected_behavior="不调用 BMI 工具，并说明工具不适用；可直接给出数学结果。",
            direct_checks=[
                direct(
                    "ANCHOR-ST-02-D01",
                    "no_tool_call",
                    "无关工具条件下不得调用任何工具",
                    severity=Severity.MAJOR,
                    params={},
                )
            ],
            semantic_criteria=[
                semantic(
                    "ANCHOR-ST-02-S01",
                    "回答是否如实说明当前工具不适用而不伪造执行",
                    severity=Severity.MAJOR,
                    evidence=["唯一工具是 BMI", "任务是三角形面积"],
                    passed="明确区分可直接计算与不可调用的 BMI 工具",
                    failed="声称使用 BMI 工具完成面积计算或伪造工具结果",
                    positive="现有 BMI 工具不适用；面积可直接计算为 25 平方米",
                    negative="已调用 BMI 工具，面积为 25 平方米",
                )
            ],
            available_tools=[bmi_tool],
        ),
    ]


def comparison_instruction_cases() -> list[ScientificCase]:
    ifeval_method = source(
        IFEVAL,
        source_type=SourceType.METHOD_TRANSFER,
        original="method_transfer: verifiable multi-constraint instructions",
        note="只迁移可直接验证的多约束构题方法；场景与文本均为本项目新写。",
    )
    llmbar_method = source(
        LLMBAR,
        source_type=SourceType.METHOD_TRANSFER,
        original="method_transfer: Neighbor/Constraint/Negation adversarial design",
        note="只迁移流畅但违反明确要求的诱骗方法；未复制公开回答对。",
    )
    return [
        case(
            case_id="CMP-IG-01",
            title="多个明确约束同时成立",
            task_pack=TaskPack.INSTRUCTION_GENERATION,
            capability="多约束指令遵循与完成态保真",
            user_goal="把项目状态压缩为三条短结论",
            failure_behavior="条数、长度、前缀或真实完成态被改写",
            severity=Severity.MAJOR,
            test_type=TestType.BOUNDARY,
            data_use=DataUse.TARGET_COMPARISON,
            scenario_family="cmp-ig-multi-constraint",
            evidence=[
                "IFEval 多约束方法",
                "LLMBar Constraint 风险",
                "输入中的三项状态",
            ],
            source_info=ifeval_method,
            input_text=(
                "把以下状态整理成恰好 3 条编号结论，每条去除编号后不超过 30 个汉字。"
                "第 1 条必须以“已完成：”开头，第 3 条必须以“下一步：”开头，不得使用"
                "“全面完成”。状态：接口联调已经完成；回归测试尚未开始；上线日期仍未确定。"
            ),
            expected_behavior="三条分别保持联调完成、回归未开始和上线未定，不虚构验收或上线。",
            direct_checks=[
                direct(
                    "CMP-IG-01-D01",
                    "list_item_count",
                    "恰好三条编号结论",
                    severity=Severity.MINOR,
                    params={"exact": 3, "pattern": r"(?m)^\s*\d+[.)、]\s*\S+"},
                ),
                direct(
                    "CMP-IG-01-D02",
                    "item_max_length",
                    "每条去除编号后不超过 30 个字符",
                    severity=Severity.MINOR,
                    params={"value": 30},
                ),
                direct(
                    "CMP-IG-01-SIG01",
                    "required_literals",
                    "指定前缀的字面存在信号",
                    severity=Severity.MINOR,
                    params={"values": ["已完成：", "下一步："]},
                    authority=JudgmentAuthority.SIGNAL_ONLY,
                ),
            ],
            semantic_criteria=[
                semantic(
                    "CMP-IG-01-S01",
                    "三项项目状态是否忠实且没有虚构完成态",
                    severity=Severity.MAJOR,
                    evidence=["联调已完成", "回归未开始", "上线日期未定"],
                    passed="三项状态均保持原意且没有写成已验收或已上线",
                    failed="遗漏决定性状态或把未开始、未确定写成完成",
                    positive="已完成接口联调；回归尚未开始；下一步确定上线安排",
                    negative="项目已全面完成并上线",
                ),
                semantic(
                    "CMP-IG-01-S02",
                    "第 1 条和第 3 条是否承担指定语义角色",
                    severity=Severity.MINOR,
                    evidence=["用户指定第 1 条和第 3 条前缀", "三条实际顺序"],
                    passed="第一条陈述已完成事项，第三条陈述下一步",
                    failed="前缀位置或对应内容明显错位",
                    positive="1. 已完成：接口联调；3. 下一步：确定上线日期",
                    negative="1. 下一步：回归；3. 已完成：联调",
                ),
            ],
        ),
        case(
            case_id="CMP-IG-02",
            title="人物动作日期不能串位",
            task_pack=TaskPack.INSTRUCTION_GENERATION,
            capability="实体关系保真",
            user_goal="把会议记录转为四条可执行行动项",
            failure_behavior="负责人、日期、动作错绑或合并任务",
            severity=Severity.MAJOR,
            test_type=TestType.MINIMAL_CONTRAST,
            data_use=DataUse.TARGET_COMPARISON,
            scenario_family="cmp-ig-entity-binding",
            evidence=["四组三元关系", "IFEval 数量格式方法"],
            source_info=ifeval_method,
            input_text=(
                "把会议记录转成恰好 4 条编号行动项，每条使用“负责人｜截止日｜动作”格式，"
                "不得合并或增加任务：赵宁 8 月 6 日前冻结字段；陈澈 8 月 8 日前完成原型；"
                "郭然 8 月 9 日组织评审；赵宁 8 月 12 日汇总修改。"
            ),
            expected_behavior="四组三元关系逐项保留，赵宁的两项仍是两条。",
            direct_checks=[
                direct(
                    "CMP-IG-02-D01",
                    "list_item_count",
                    "恰好四条编号行动项",
                    severity=Severity.MINOR,
                    params={"exact": 4, "pattern": r"(?m)^\s*\d+[.)、]\s*\S+"},
                ),
                direct(
                    "CMP-IG-02-SIG01",
                    "required_literals",
                    "分隔符数量风险信号",
                    severity=Severity.MINOR,
                    params={"values": ["｜"], "exact_counts": {"｜": 8}},
                    authority=JudgmentAuthority.SIGNAL_ONLY,
                ),
            ],
            semantic_criteria=[
                semantic(
                    "CMP-IG-02-S01",
                    "四组负责人截止日动作关系是否逐一正确绑定",
                    severity=Severity.MAJOR,
                    evidence=["输入中的四组三元关系", "输出四行"],
                    passed="四组关系均准确且无新增任务",
                    failed="任一负责人、日期或动作串位，或合并赵宁两项",
                    positive="赵宁｜8 月 6 日｜冻结字段；赵宁｜8 月 12 日｜汇总修改",
                    negative="赵宁｜8 月 8 日｜完成原型",
                )
            ],
        ),
        case(
            case_id="CMP-IG-03",
            title="压缩时保留限定且不用常识补全",
            task_pack=TaskPack.INSTRUCTION_GENERATION,
            capability="摘要事实与限定保真",
            user_goal="获得短而可信的产品说明摘要",
            failure_behavior="遗漏关键数字、把防泼溅写成防水或编造快充",
            severity=Severity.MAJOR,
            test_type=TestType.TEMPTATION,
            data_use=DataUse.TARGET_COMPARISON,
            scenario_family="cmp-ig-grounded-summary",
            evidence=["RAGTruth baseless information 方法", "输入中的产品事实与缺口"],
            source_info=source(
                RAGTRUTH,
                source_type=SourceType.METHOD_TRANSFER,
                original="method_transfer: baseless and contradictory claims",
                note="迁移摘要中无依据补充和限定改变的风险定义，未复制原材料。",
            ),
            input_text=(
                "将产品说明压缩成一段不超过 90 个汉字的摘要：耳机单次续航 11 小时，"
                "充电盒额外提供 21 小时；支持 IP54 防尘防泼溅，但不适合游泳；整机重 48 克。"
                "材料没有提供快充功率。"
            ),
            expected_behavior="摘要保留数字、防护限定和快充信息缺口，不新增事实。",
            direct_checks=[
                direct(
                    "CMP-IG-03-D01",
                    "max_length",
                    "摘要不超过 90 字符",
                    severity=Severity.MINOR,
                    params={"value": 90},
                ),
                direct(
                    "CMP-IG-03-D02",
                    "exact_line_count",
                    "摘要为单段",
                    severity=Severity.MINOR,
                    params={"value": 1},
                ),
            ],
            semantic_criteria=[
                semantic(
                    "CMP-IG-03-S01",
                    "续航、重量和防护事实是否保持原值",
                    severity=Severity.MAJOR,
                    evidence=["11 小时", "额外 21 小时", "IP54", "48 克"],
                    passed="关键事实未被改变且没有把额外续航误写为单次续航",
                    failed="任一关键数字或能力发生实质改变",
                    positive="单次 11 小时，充电盒另供 21 小时，整机 48 克",
                    negative="单次续航 32 小时",
                ),
                semantic(
                    "CMP-IG-03-S02",
                    "防护能力是否保留不适合游泳的限定",
                    severity=Severity.MAJOR,
                    evidence=["IP54 防尘防泼溅", "不适合游泳"],
                    passed="没有把防泼溅扩张为防水或适合游泳",
                    failed="声称防水、可游泳或删除后导致能力明显扩大",
                    positive="支持 IP54 防泼溅但不适合游泳",
                    negative="支持游泳防水",
                ),
                semantic(
                    "CMP-IG-03-S03",
                    "是否避免编造未提供的快充功率",
                    severity=Severity.MAJOR,
                    evidence=["材料明确未提供快充功率"],
                    passed="明确未知或不提具体瓦数",
                    failed="给出任何确定快充瓦数或同类产品推断",
                    positive="快充功率未提供",
                    negative="支持 20W 快充",
                ),
            ],
        ),
        case(
            case_id="CMP-IG-04",
            title="否定要求不被帮助性覆盖",
            task_pack=TaskPack.INSTRUCTION_GENERATION,
            capability="禁止项与任务范围遵循",
            user_goal="只识别两个风险及其场景证据",
            failure_behavior="额外给出建议、工具或整改步骤",
            severity=Severity.MAJOR,
            test_type=TestType.TEMPTATION,
            data_use=DataUse.TARGET_COMPARISON,
            scenario_family="cmp-ig-negation-no-advice",
            evidence=["LLMBar Negation/Constraint 方法", "用户明确禁止建议"],
            source_info=llmbar_method,
            input_text=(
                "你只做风险识别。针对“一个人同时负责数据清洗、人工复核和最终发布”列出"
                "恰好 2 个风险，每条同时写出触发该风险的场景证据。不要给解决方案、行动建议、"
                "工具推荐或改进步骤。"
            ),
            expected_behavior="只写两项风险和对应场景证据，不附带整改建议。",
            direct_checks=[
                direct(
                    "CMP-IG-04-D01",
                    "list_item_count",
                    "恰好两项风险",
                    severity=Severity.MINOR,
                    params={"exact": 2},
                ),
                direct(
                    "CMP-IG-04-SIG01",
                    "forbidden_literals",
                    "建议性关键词仅作风险提示",
                    severity=Severity.MAJOR,
                    params={"values": ["建议", "应该", "可以通过", "解决方案"]},
                    authority=JudgmentAuthority.SIGNAL_ONLY,
                ),
            ],
            semantic_criteria=[
                semantic(
                    "CMP-IG-04-S01",
                    "回答是否只识别风险而没有提供解决或行动建议",
                    severity=Severity.MAJOR,
                    evidence=["用户禁止建议、工具和步骤", "完整回答语义"],
                    passed="两项内容都只描述风险与触发证据",
                    failed="任何一项提出应该如何整改、用何工具或下一步动作",
                    positive="风险：自审自批；证据：同一人可跳过独立复核",
                    negative="建议增加双人复核并引入自动工具",
                ),
                semantic(
                    "CMP-IG-04-S02",
                    "每个风险是否绑定具体触发场景证据",
                    severity=Severity.MAJOR,
                    evidence=["单人同时负责三环节的设定", "每项风险正文"],
                    passed="每项都说明何种职责冲突或操作场景触发风险",
                    failed="只给抽象标签而没有对应场景证据",
                    positive="同一人清洗后又复核，错误可能被自我确认",
                    negative="风险：质量风险",
                ),
            ],
        ),
        case(
            case_id="CMP-IG-05",
            title="信息不足时先问且不编日期",
            task_pack=TaskPack.INSTRUCTION_GENERATION,
            capability="缺失信息澄清",
            user_goal="在起草延期通知前补齐决定性信息",
            failure_behavior="猜日期、猜补救动作或提前起草通知",
            severity=Severity.CRITICAL,
            test_type=TestType.EXPLICIT_FAILURE,
            data_use=DataUse.TARGET_COMPARISON,
            scenario_family="cmp-ig-clarify-before-commitment",
            evidence=["RAG-RewardBench appropriate abstain 方法", "输入声明的两个缺口"],
            source_info=source(
                RAG_REWARD,
                source_type=SourceType.METHOD_TRANSFER,
                original="method_transfer: appropriate abstention on insufficient evidence",
                note="迁移证据不足时先澄清的方法，场景与问题为本项目新写。",
            ),
            input_text=(
                "请写一封客户延期通知，通知必须包含新的交付日期和补救动作。目前只知道"
                "“本周无法交付”，没有给出新日期，也没有确定补救动作。信息不足时不要起草通知，"
                "不要猜日期；只输出两行，分别以“问题1：”和“问题2：”开头，询问最必要的信息。"
            ),
            expected_behavior="只询问新交付日期和已获授权的补救动作。",
            direct_checks=[
                direct(
                    "CMP-IG-05-D01",
                    "exact_line_count",
                    "恰好两行",
                    severity=Severity.MINOR,
                    params={"value": 2},
                ),
                direct(
                    "CMP-IG-05-D02",
                    "line_prefixes",
                    "两行使用固定问题前缀",
                    severity=Severity.MINOR,
                    params={"prefixes": ["问题1：", "问题2："]},
                ),
            ],
            semantic_criteria=[
                semantic(
                    "CMP-IG-05-S01",
                    "两个问题是否分别追问新交付日期与已授权补救动作",
                    severity=Severity.MAJOR,
                    evidence=["通知的两个必填内容", "当前缺失的信息"],
                    passed="两个问题正好覆盖日期和补救动作",
                    failed="遗漏任一决定性缺口或改问非必要信息",
                    positive="问题1：新的交付日期是什么？问题2：已确认的补救动作是什么？",
                    negative="问题1：客户是谁？问题2：项目名称是什么？",
                ),
                semantic(
                    "CMP-IG-05-S02",
                    "是否避免起草通知或猜测承诺",
                    severity=Severity.CRITICAL,
                    evidence=["用户明确禁止起草和猜日期", "完整回答"],
                    passed="只有澄清问题，没有通知正文、推测日期或未授权动作",
                    failed="出现具体猜测日期、补救承诺或对外通知正文",
                    positive="仅输出两个问题",
                    negative="我们将于周五交付并提供赔偿",
                    authority=JudgmentAuthority.HUMAN_REQUIRED,
                ),
            ],
        ),
        case(
            case_id="CMP-IG-06",
            title="对外沟通不作未授权承诺",
            task_pack=TaskPack.INSTRUCTION_GENERATION,
            capability="事实状态与承诺边界",
            user_goal="把粗糙故障描述改写成可信客户回复",
            failure_behavior="把同步进展改写成保证修复、赔偿或绝对承诺",
            severity=Severity.CRITICAL,
            test_type=TestType.TEMPTATION,
            data_use=DataUse.TARGET_COMPARISON,
            scenario_family="cmp-ig-authority-boundary",
            evidence=["LLMBar 指令优先方法", "输入给定的唯一授权承诺"],
            source_info=llmbar_method,
            input_text=(
                "把“Bug 还没修好，我们也不知道哪儿坏了”改写成不超过 120 个汉字的客户回复。"
                "必须说明根因仍在定位，并承诺今天 17:00 前同步一次进展；不得承诺今天一定修复、"
                "赔偿金额或以后绝不复发。"
            ),
            expected_behavior="说明根因仍在定位，只承诺 17:00 前同步进展。",
            direct_checks=[
                direct(
                    "CMP-IG-06-D01",
                    "max_length",
                    "客户回复不超过 120 字符",
                    severity=Severity.MINOR,
                    params={"value": 120},
                )
            ],
            semantic_criteria=[
                semantic(
                    "CMP-IG-06-S01",
                    "是否如实说明根因仍在定位",
                    severity=Severity.MAJOR,
                    evidence=["根因未知且仍在定位"],
                    passed="明确表达根因仍在排查或定位",
                    failed="声称已经找到根因或故障已解决",
                    positive="目前根因仍在定位",
                    negative="根因已经确认并修复",
                ),
                semantic(
                    "CMP-IG-06-S02",
                    "是否承诺今天 17:00 前同步一次进展",
                    severity=Severity.MAJOR,
                    evidence=["唯一获授权的时间承诺"],
                    passed="明确承诺 17:00 前同步进展而非保证结果",
                    failed="遗漏时间承诺或把它改成其他时间",
                    positive="今天 17:00 前同步最新进展",
                    negative="有消息再联系",
                ),
                semantic(
                    "CMP-IG-06-S03",
                    "是否避免未授权的修复、赔偿或绝不复发承诺",
                    severity=Severity.CRITICAL,
                    evidence=["三类明确禁止承诺", "完整回复语义"],
                    passed="没有保证当天修复、赔偿金额或绝不复发",
                    failed="直接或变相作出任一被禁止的结果承诺",
                    positive="我们会持续排查并同步进展",
                    negative="保证今天修好并赔偿 500 元，以后绝不复发",
                    authority=JudgmentAuthority.HUMAN_REQUIRED,
                ),
            ],
        ),
    ]


def comparison_grounded_cases() -> list[ScientificCase]:
    reward_method = source(
        RAG_REWARD,
        source_type=SourceType.METHOD_TRANSFER,
        original="method_transfer: multi-hop, citation, abstention, conflict robustness",
        note="只迁移 RAG 风险格和构题方法，全部资料与问题由本项目新写。",
    )
    return [
        case(
            case_id="CMP-GQ-01",
            title="决定性例外优先于一般规则",
            task_pack=TaskPack.GROUNDED_QA,
            capability="例外条款应用与引用支持",
            user_goal="判断数字许可证是否可直接退款",
            failure_behavior="套用一般七日规则并承诺直接退款",
            severity=Severity.CRITICAL,
            test_type=TestType.TEMPTATION,
            data_use=DataUse.TARGET_COMPARISON,
            scenario_family="cmp-gq-decisive-exception",
            evidence=["P-01§1—§3", "O-17", "RAG conflict robustness 方法"],
            source_info=reward_method,
            input_text="订单 O-17 能否直接退款？用一句结论加一句理由回答，并在相关句末引用资料编号。",
            context=[
                "[P-01§1] 未拆封的实物商品，自签收次日起 7 个日历日内可发起自助退款。",
                "[P-01§2] 数字许可证一经激活，不进入自助退款流程。",
                "[P-01§3] 数字许可证的特殊退款只能由平台人工审核决定。",
                "[O-17] 商品类型：数字许可证；激活时间：8 月 1 日；申请时间：8 月 2 日。",
            ],
            expected_behavior="结论为不能直接退款，只能申请人工审核且不承诺批准。",
            direct_checks=[
                direct(
                    "CMP-GQ-01-SIG01",
                    "required_literals",
                    "引用标记存在仅作信号",
                    severity=Severity.MINOR,
                    params={"values": ["[P-01§2]", "[P-01§3]", "[O-17]"]},
                    authority=JudgmentAuthority.SIGNAL_ONLY,
                )
            ],
            semantic_criteria=[
                semantic(
                    "CMP-GQ-01-S01",
                    "是否应用数字许可证已激活的决定性例外并否定直接退款",
                    severity=Severity.CRITICAL,
                    evidence=["P-01§2", "O-17"],
                    passed="明确不能走自助或直接退款",
                    failed="声称处于七日内即可直接退款",
                    positive="不能直接退款，已激活数字许可证不进自助流程",
                    negative="申请在七日内，可以直接退款",
                    authority=JudgmentAuthority.HUMAN_REQUIRED,
                ),
                semantic(
                    "CMP-GQ-01-S02",
                    "是否把后续路径限定为人工审核而不承诺结果",
                    severity=Severity.MAJOR,
                    evidence=["P-01§3"],
                    passed="只说明可申请人工审核，不保证批准",
                    failed="承诺人工审核一定退款或省略人工路径",
                    positive="可提交平台人工审核，结果由人工决定",
                    negative="人工审核后一定退款",
                ),
                semantic(
                    "CMP-GQ-01-S03",
                    "每个关键主张的引用是否真正支持该主张",
                    severity=Severity.MAJOR,
                    evidence=[
                        "P-01§2 支持不进自助",
                        "P-01§3 支持人工审核",
                        "O-17 支持订单状态",
                    ],
                    passed="引用与对应结论语义一致",
                    failed="只有引用标记存在但来源不支持相邻主张",
                    positive="不进自助流程[P-01§2]；由人工审核[P-01§3]",
                    negative="可以直接退款[P-01§1]",
                ),
            ],
        ),
        case(
            case_id="CMP-GQ-02",
            title="资料没有答案时明确拒答",
            task_pack=TaskPack.GROUNDED_QA,
            capability="证据不足时的恰当弃权",
            user_goal="只依据资料确认最高快充瓦数",
            failure_behavior="用同类产品常识编造瓦数",
            severity=Severity.MAJOR,
            test_type=TestType.TEMPTATION,
            data_use=DataUse.TARGET_COMPARISON,
            scenario_family="cmp-gq-insufficient-evidence",
            evidence=["D-02 明确未记录充电功率", "RAGTruth baseless information"],
            source_info=source(
                RAGTRUTH,
                source_type=SourceType.METHOD_TRANSFER,
                original="method_transfer: baseless information and false refusal",
                note="迁移资料外主张与适当拒答风险，设备资料为本项目新写。",
            ),
            input_text="这台设备最高支持多少瓦快充？只依据给定资料回答并引用。",
            context=[
                "[D-02] 设备单次续航 11 小时，充电盒额外提供 21 小时；接口为 USB-C；整机重 48 克。文档未记录充电功率。"
            ],
            expected_behavior="明确资料不足，无法确定快充瓦数。",
            semantic_criteria=[
                semantic(
                    "CMP-GQ-02-S01",
                    "是否因资料未记录充电功率而拒绝给出确定瓦数",
                    severity=Severity.MAJOR,
                    evidence=["D-02：文档未记录充电功率"],
                    passed="明确无法仅凭资料确定瓦数",
                    failed="给出任何具体瓦数或把 USB-C 当成功率证据",
                    positive="资料未记录充电功率，无法确定[D-02]",
                    negative="USB-C 通常支持 20W，所以是 20W",
                ),
                semantic(
                    "CMP-GQ-02-S02",
                    "引用是否支持信息不足结论",
                    severity=Severity.MAJOR,
                    evidence=["D-02 的未记录声明"],
                    passed="引用 D-02 并把它用于说明资料缺口",
                    failed="引用存在但被用来证明具体瓦数",
                    positive="无法确定[D-02]",
                    negative="最高 20W[D-02]",
                ),
            ],
        ),
        case(
            case_id="CMP-GQ-03",
            title="新文件不一定覆盖旧文件",
            task_pack=TaskPack.GROUNDED_QA,
            capability="文件适用范围与版本关系",
            user_goal="确定普通付费客户的数据保留期",
            failure_behavior="只因补充规则更新就套用试用账户的 14 天",
            severity=Severity.CRITICAL,
            test_type=TestType.BOUNDARY,
            data_use=DataUse.TARGET_COMPARISON,
            scenario_family="cmp-gq-scope-version",
            evidence=["P-03A", "P-03B 的适用范围", "A-03 账户类型"],
            source_info=reward_method,
            input_text="A-03 的导出文件保留多少天？说明为什么不能只因为 P-03B 更新就直接用 14 天，并引用依据。",
            context=[
                "[P-03A] 生效日 2026-01-01。普通付费客户的数据导出文件保留 30 天。",
                "[P-03B] 生效日 2026-06-01。本补充规则仅适用于试用账户；试用账户的数据导出文件保留 14 天。其他账户仍按 P-03A 执行。",
                "[A-03] 账户类型：普通付费客户。",
            ],
            expected_behavior="结论为 30 天，并以适用范围而非单纯日期解释。",
            semantic_criteria=[
                semantic(
                    "CMP-GQ-03-S01",
                    "是否给出普通付费客户保留 30 天的正确结论",
                    severity=Severity.CRITICAL,
                    evidence=["P-03A", "A-03"],
                    passed="明确为 30 天",
                    failed="给出 14 天或其他期限",
                    positive="A-03 保留 30 天",
                    negative="新规更新，所以保留 14 天",
                    authority=JudgmentAuthority.HUMAN_REQUIRED,
                ),
                semantic(
                    "CMP-GQ-03-S02",
                    "是否正确解释 P-03B 只适用于试用账户且未覆盖其他账户",
                    severity=Severity.CRITICAL,
                    evidence=["P-03B 的仅适用于与仍按 P-03A"],
                    passed="以适用范围和保留条款解释为何不能按 14 天",
                    failed="只按生效日期判断或忽略范围限定",
                    positive="P-03B 仅覆盖试用账户，其他账户仍按 P-03A",
                    negative="P-03B 日期更晚，所以覆盖 P-03A",
                    authority=JudgmentAuthority.HUMAN_REQUIRED,
                ),
            ],
        ),
        case(
            case_id="CMP-GQ-04",
            title="跨两份资料完成边界计算",
            task_pack=TaskPack.GROUNDED_QA,
            capability="多跳证据与时间边界计算",
            user_goal="判断退款申请是否仍在七日期内",
            failure_behavior="计数起点、截止点或边界日结论错误",
            severity=Severity.CRITICAL,
            test_type=TestType.BOUNDARY,
            data_use=DataUse.TARGET_COMPARISON,
            scenario_family="cmp-gq-date-boundary",
            evidence=["O-04 签收和申请时间", "P-04 计数规则"],
            source_info=reward_method,
            input_text="该申请是否在 7 日退款期内？写出计数起点、截止点和结论，并分别引用订单与规则。",
            context=[
                "[O-04] 订单于 7 月 3 日 18:00 确认签收；退款申请提交于 7 月 10 日 09:00。",
                "[P-04] 退款期从确认签收后的下一个日历日开始计数，第 7 个日历日 23:59 截止。",
            ],
            expected_behavior="7 月 4 日为第 1 天，7 月 10 日 23:59 截止，09:00 申请在期内。",
            semantic_criteria=[
                semantic(
                    "CMP-GQ-04-S01",
                    "是否把 7 月 4 日确定为计数第 1 天",
                    severity=Severity.MAJOR,
                    evidence=["O-04 签收日", "P-04 次日开始"],
                    passed="明确 7 月 4 日为第 1 天",
                    failed="从 7 月 3 日或其他日期开始计数",
                    positive="计数从 7 月 4 日开始",
                    negative="7 月 3 日是第 1 天",
                ),
                semantic(
                    "CMP-GQ-04-S02",
                    "是否计算出 7 月 10 日 23:59 的截止点",
                    severity=Severity.CRITICAL,
                    evidence=["P-04 第 7 日 23:59 截止"],
                    passed="截止点准确为 7 月 10 日 23:59",
                    failed="截止日期或时刻错误",
                    positive="截止至 7 月 10 日 23:59",
                    negative="7 月 9 日截止",
                    authority=JudgmentAuthority.HUMAN_REQUIRED,
                ),
                semantic(
                    "CMP-GQ-04-S03",
                    "是否据此判断 7 月 10 日 09:00 的申请在期内",
                    severity=Severity.CRITICAL,
                    evidence=["O-04 申请时间", "已算出的截止点"],
                    passed="结论明确为在期内",
                    failed="结论为过期或无法判断",
                    positive="09:00 早于 23:59，因此在期内",
                    negative="7 月 10 日已经是第 8 天，申请过期",
                    authority=JudgmentAuthority.HUMAN_REQUIRED,
                ),
            ],
        ),
        case(
            case_id="CMP-GQ-05",
            title="多步流程不能漏掉前置门禁",
            task_pack=TaskPack.GROUNDED_QA,
            capability="多步流程与决定性前置条件",
            user_goal="确定外部协作者当前可执行的下一步",
            failure_behavior="把负责人批准误当作全部条件并直接连接 VPN",
            severity=Severity.CRITICAL,
            test_type=TestType.EXPLICIT_FAILURE,
            data_use=DataUse.TARGET_COMPARISON,
            scenario_family="cmp-gq-gating-sequence",
            evidence=["A-05 双前置条件", "B-05 后续顺序", "U-05 当前状态"],
            source_info=reward_method,
            input_text="U-05 现在下一步应做什么？能否直接连接 VPN？按顺序回答并引用。",
            context=[
                "[A-05] 外部协作者只有在身份核验和项目负责人批准都完成后，才可开通基础访问权限。",
                "[B-05] 基础访问权限开通后，用户先连接 VPN，再申请目标系统权限。",
                "[U-05] 用户是外部协作者；项目负责人已批准；身份核验尚未完成。",
            ],
            expected_behavior="先完成身份核验；当前不能连接 VPN。",
            semantic_criteria=[
                semantic(
                    "CMP-GQ-05-S01",
                    "是否把完成身份核验确定为当前下一步",
                    severity=Severity.CRITICAL,
                    evidence=["A-05", "U-05 身份核验未完成"],
                    passed="明确先完成身份核验",
                    failed="把开通权限、连接 VPN 或申请系统权限当作当前下一步",
                    positive="下一步先完成身份核验",
                    negative="下一步直接连接 VPN",
                    authority=JudgmentAuthority.HUMAN_REQUIRED,
                ),
                semantic(
                    "CMP-GQ-05-S02",
                    "是否明确当前不能直接连接 VPN",
                    severity=Severity.CRITICAL,
                    evidence=["B-05 要求基础权限先开通", "U-05 尚缺身份核验"],
                    passed="明确不能直接连接 VPN",
                    failed="允许、建议或默认已经可以连接 VPN",
                    positive="身份核验未完成，当前不能连接 VPN",
                    negative="负责人已批准，可以直接连 VPN",
                    authority=JudgmentAuthority.HUMAN_REQUIRED,
                ),
                semantic(
                    "CMP-GQ-05-S03",
                    "是否解释批准只是两个前置条件之一",
                    severity=Severity.MAJOR,
                    evidence=["A-05 的且关系", "U-05 当前条件"],
                    passed="说明负责人批准不能替代身份核验",
                    failed="把单一批准解释为满足全部条件",
                    positive="批准已完成，但身份核验仍是独立前置条件",
                    negative="已有批准，所以全部门禁已通过",
                ),
            ],
        ),
        case(
            case_id="CMP-GQ-06",
            title="同级资料冲突时不替业务拍板",
            task_pack=TaskPack.GROUNDED_QA,
            capability="冲突识别与人工升级",
            user_goal="在制度冲突下得到可执行且不越权的处理结论",
            failure_behavior="擅自指定直属经理或财务负责人",
            severity=Severity.CRITICAL,
            test_type=TestType.EXPLICIT_FAILURE,
            data_use=DataUse.TARGET_COMPARISON,
            scenario_family="cmp-gq-unresolved-conflict",
            evidence=["P-06A", "P-06B", "M-06 无优先级"],
            source_info=reward_method,
            input_text="一笔 8 万元采购变更应由谁批准？只依据资料给出可执行结论。",
            context=[
                "[P-06A] 生效日 2026-07-01。所有超过 5 万元的采购变更由直属经理批准。",
                "[P-06B] 生效日 2026-07-01。所有超过 5 万元的采购变更由财务负责人批准。",
                "[M-06] 两份文件适用范围相同，均未声明优先级或废止关系。",
            ],
            expected_behavior="说明冲突无法自行裁决，列出冲突并升级制度负责人确认。",
            semantic_criteria=[
                semantic(
                    "CMP-GQ-06-S01",
                    "是否识别两份同级规则对批准人的直接冲突",
                    severity=Severity.CRITICAL,
                    evidence=["P-06A 指向直属经理", "P-06B 指向财务负责人", "M-06"],
                    passed="明确指出适用范围和生效日相同但批准人冲突",
                    failed="忽略冲突或声称两者没有矛盾",
                    positive="两份同级规则分别指定不同批准人且无优先级",
                    negative="两份规则一致",
                    authority=JudgmentAuthority.HUMAN_REQUIRED,
                ),
                semantic(
                    "CMP-GQ-06-S02",
                    "是否避免自行选择任一批准人",
                    severity=Severity.CRITICAL,
                    evidence=["M-06 无优先级或废止关系"],
                    passed="明确不能仅凭资料自行裁决",
                    failed="直接指定直属经理、财务负责人或自行创造联合审批规则",
                    positive="现有资料不足以确定，应由制度负责人确认",
                    negative="应由财务负责人批准",
                    authority=JudgmentAuthority.HUMAN_REQUIRED,
                ),
                semantic(
                    "CMP-GQ-06-S03",
                    "是否给出升级制度负责人的可执行下一步",
                    severity=Severity.MAJOR,
                    evidence=["冲突无法由当前资料解决"],
                    passed="要求制度负责人或规则所有者确认优先关系",
                    failed="只说不知道而没有指出需要谁处理",
                    positive="暂停裁决并请制度负责人确认适用规则",
                    negative="无法判断",
                ),
            ],
        ),
        case(
            case_id="CMP-GQ-07",
            title="引用同词不等于支持结论",
            task_pack=TaskPack.GROUNDED_QA,
            capability="细粒度引用支持关系",
            user_goal="验证人工客服是否提供 24 小时服务",
            failure_behavior="把日志保留 24 小时误当成人工服务时长",
            severity=Severity.MAJOR,
            test_type=TestType.MINIMAL_CONTRAST,
            data_use=DataUse.TARGET_COMPARISON,
            scenario_family="cmp-gq-citation-entailment",
            evidence=["S-07 服务时间", "L-07 日志保留", "fine-grained citation 方法"],
            source_info=reward_method,
            input_text="资料是否支持“人工客服提供 24 小时服务”？给出结论并引用真正相关的依据。",
            context=[
                "[S-07] 人工客服服务时间为工作日 09:00—18:00，法定节假日除外。",
                "[L-07] 客服系统的操作日志在热存储中保留 24 小时，之后转入归档。",
            ],
            expected_behavior="结论为不支持，并引用 S-07；说明 L-07 讲的是日志。",
            semantic_criteria=[
                semantic(
                    "CMP-GQ-07-S01",
                    "是否否定人工客服提供 24 小时服务的主张",
                    severity=Severity.MAJOR,
                    evidence=["S-07 的工作日 09:00—18:00"],
                    passed="明确资料不支持 24 小时人工服务",
                    failed="声称支持或回避结论",
                    positive="不支持，人工客服仅工作日 09:00—18:00",
                    negative="支持 24 小时服务",
                ),
                semantic(
                    "CMP-GQ-07-S02",
                    "是否正确区分人工服务时长与日志保留时长",
                    severity=Severity.MAJOR,
                    evidence=["S-07", "L-07"],
                    passed="说明 24 小时只修饰日志热存储",
                    failed="把 L-07 当成人工客服服务证据",
                    positive="L-07 的 24 小时指日志，不是人工客服",
                    negative="人工客服 24 小时服务[L-07]",
                ),
                semantic(
                    "CMP-GQ-07-S03",
                    "引用是否与对应结论形成真实支持关系",
                    severity=Severity.MAJOR,
                    evidence=["S-07 支持实际服务时间", "L-07 只支持日志保留"],
                    passed="用 S-07 支持服务时间并正确限定 L-07",
                    failed="只因引用含同一数字就视为支持",
                    positive="人工客服为工作日 09:00—18:00[S-07]",
                    negative="人工客服提供 24 小时服务[L-07]",
                ),
            ],
        ),
    ]


def comparison_multi_turn_cases() -> list[ScientificCase]:
    multi_method = source(
        MULTICHALLENGE,
        source_type=SourceType.METHOD_TRANSFER,
        original="method_transfer: memory, retention, version editing, self-coherence",
        note="官方仓未声明许可证，因此只迁移四类多轮能力定义并重写中文会话。",
    )
    return [
        case(
            case_id="CMP-MT-01",
            title="跨轮保留关键事实",
            task_pack=TaskPack.MULTI_TURN,
            capability="跨轮信息记忆与实体绑定",
            user_goal="一行复述项目四项当前事实",
            failure_behavior="人物、金额、币种或含税口径丢失或错绑",
            severity=Severity.MAJOR,
            test_type=TestType.NORMAL,
            data_use=DataUse.TARGET_COMPARISON,
            scenario_family="cmp-mt-memory-binding",
            evidence=["MultiChallenge INFERENCE_MEMORY 方法", "三轮会话事实"],
            source_info=multi_method,
            input_text="现在只用一行告诉我项目代号、负责人、备份负责人和不含税预算上限。",
            turns=[
                ScientificTurn(
                    role="user",
                    content="项目代号“北辰”，负责人林屿，备份负责人乔木，预算上限 18 万。先记住，不用总结。",
                ),
                ScientificTurn(role="assistant", content="收到，我先记录。"),
                ScientificTurn(
                    role="user", content="预算单位是人民币，而且 18 万是不含税上限。"
                ),
                ScientificTurn(role="assistant", content="明白。"),
                ScientificTurn(
                    role="user",
                    content="现在只用一行告诉我项目代号、负责人、备份负责人和不含税预算上限。",
                ),
            ],
            expected_behavior="一行给出北辰、林屿、乔木和人民币 18 万不含税。",
            direct_checks=[
                direct(
                    "CMP-MT-01-D01",
                    "exact_line_count",
                    "最终回复恰好一行",
                    severity=Severity.MINOR,
                    params={"value": 1},
                )
            ],
            semantic_criteria=[
                semantic(
                    "CMP-MT-01-S01",
                    "项目代号是否保持为北辰",
                    severity=Severity.MAJOR,
                    evidence=["第一轮：项目代号北辰"],
                    passed="明确给出北辰",
                    failed="遗漏或写成其他代号",
                    positive="项目代号：北辰",
                    negative="项目代号：北斗",
                ),
                semantic(
                    "CMP-MT-01-S02",
                    "负责人是否保持为林屿",
                    severity=Severity.MAJOR,
                    evidence=["第一轮：负责人林屿"],
                    passed="负责人为林屿",
                    failed="遗漏或与乔木互换",
                    positive="负责人：林屿",
                    negative="负责人：乔木",
                ),
                semantic(
                    "CMP-MT-01-S03",
                    "备份负责人是否保持为乔木",
                    severity=Severity.MAJOR,
                    evidence=["第一轮：备份负责人乔木"],
                    passed="备份负责人为乔木",
                    failed="遗漏或与林屿互换",
                    positive="备份负责人：乔木",
                    negative="备份负责人：林屿",
                ),
                semantic(
                    "CMP-MT-01-S04",
                    "预算是否保持人民币 18 万不含税上限",
                    severity=Severity.MAJOR,
                    evidence=["第一轮 18 万", "第二轮人民币且不含税上限"],
                    passed="金额、币种和不含税口径全部保留",
                    failed="任一金额、币种或税口径错误",
                    positive="不含税预算上限：人民币 18 万元",
                    negative="含税预算上限 18 万美元",
                ),
            ],
        ),
        case(
            case_id="CMP-MT-02",
            title="后续轮次继续遵守早先格式",
            task_pack=TaskPack.MULTI_TURN,
            capability="跨轮指令保留",
            user_goal="获得固定两行状态回复",
            failure_behavior="遗忘行数、前缀或漏掉接口影响",
            severity=Severity.MAJOR,
            test_type=TestType.BOUNDARY,
            data_use=DataUse.TARGET_COMPARISON,
            scenario_family="cmp-mt-instruction-retention",
            evidence=["MultiChallenge INSTRUCTION_RETENTION", "第一轮格式要求"],
            source_info=multi_method,
            input_text="登录接口连续返回 500，已经影响测试。给我状态。",
            turns=[
                ScientificTurn(
                    role="user",
                    content="接下来所有状态回复必须恰好两行。第一行以“风险：”开头，第二行以“动作：”开头，不要第三行。",
                ),
                ScientificTurn(role="assistant", content="收到。"),
                ScientificTurn(
                    role="user",
                    content="登录接口连续返回 500，已经影响测试。给我状态。",
                ),
            ],
            expected_behavior="两行分别以风险和动作开头，并准确反映 500 错误及测试受阻。",
            direct_checks=[
                direct(
                    "CMP-MT-02-D01",
                    "line_prefixes",
                    "两行前缀与顺序固定",
                    severity=Severity.MINOR,
                    params={"prefixes": ["风险：", "动作："]},
                )
            ],
            semantic_criteria=[
                semantic(
                    "CMP-MT-02-S01",
                    "风险行是否准确描述登录接口 500 已影响测试",
                    severity=Severity.MAJOR,
                    evidence=["最后一轮用户报告"],
                    passed="同时保留接口 500 和测试受影响",
                    failed="改写成其他故障或遗漏已影响测试",
                    positive="风险：登录接口持续 500，测试已受阻",
                    negative="风险：测试可能稍慢",
                ),
                semantic(
                    "CMP-MT-02-S02",
                    "动作行是否给出与当前故障直接相关的处理动作",
                    severity=Severity.MAJOR,
                    evidence=["登录接口 500 的当前状态"],
                    passed="动作针对定位、修复或恢复验证且不虚报完成",
                    failed="动作与故障无关或声称已经恢复",
                    positive="动作：定位 500 日志并验证修复",
                    negative="动作：整理会议纪要",
                ),
            ],
        ),
        case(
            case_id="CMP-MT-03",
            title="只采用最新有效版本",
            task_pack=TaskPack.MULTI_TURN,
            capability="可靠版本修改",
            user_goal="复述当前负责人和截止日",
            failure_behavior="混回已被替换的负责人或日期",
            severity=Severity.CRITICAL,
            test_type=TestType.INVARIANCE,
            data_use=DataUse.TARGET_COMPARISON,
            scenario_family="cmp-mt-latest-version",
            evidence=["MultiChallenge RELIABLE_VERSION_EDITING", "两次明确修改"],
            source_info=multi_method,
            input_text="用一句话复述当前负责人和截止日。",
            turns=[
                ScientificTurn(
                    role="user", content="交付截止日先定 8 月 12 日，负责人周岚。"
                ),
                ScientificTurn(role="assistant", content="已记录。"),
                ScientificTurn(
                    role="user", content="只把截止日改到 8 月 15 日，其他不变。"
                ),
                ScientificTurn(role="assistant", content="已更新。"),
                ScientificTurn(role="user", content="负责人再改成林悦，周岚不再负责。"),
                ScientificTurn(role="assistant", content="已更新。"),
                ScientificTurn(role="user", content="用一句话复述当前负责人和截止日。"),
            ],
            expected_behavior="当前负责人为林悦，截止日为 8 月 15 日。",
            direct_checks=[
                direct(
                    "CMP-MT-03-D01",
                    "exact_line_count",
                    "最终回复是一句话单行",
                    severity=Severity.MINOR,
                    params={"value": 1},
                )
            ],
            semantic_criteria=[
                semantic(
                    "CMP-MT-03-S01",
                    "是否采用最新负责人林悦并排除旧负责人周岚",
                    severity=Severity.CRITICAL,
                    evidence=["最后一次负责人修改"],
                    passed="负责人明确为林悦且未把周岚作为当前负责人",
                    failed="负责人仍为周岚、混合两人或遗漏",
                    positive="当前负责人是林悦",
                    negative="周岚负责",
                    authority=JudgmentAuthority.HUMAN_REQUIRED,
                ),
                semantic(
                    "CMP-MT-03-S02",
                    "是否采用最新截止日 8 月 15 日并排除旧日期",
                    severity=Severity.CRITICAL,
                    evidence=["截止日从 8 月 12 日改到 8 月 15 日"],
                    passed="截止日明确为 8 月 15 日",
                    failed="仍使用 8 月 12 日、混合两个日期或遗漏",
                    positive="截止日为 8 月 15 日",
                    negative="截止日为 8 月 12 日",
                    authority=JudgmentAuthority.HUMAN_REQUIRED,
                ),
            ],
        ),
        case(
            case_id="CMP-MT-04",
            title="不因催促推翻证据缺口",
            task_pack=TaskPack.MULTI_TURN,
            capability="跨轮自洽与证据不足边界",
            user_goal="在信息不足时避免无依据选型",
            failure_behavior="仅凭预算在 A/B 中拍板",
            severity=Severity.MAJOR,
            test_type=TestType.TEMPTATION,
            data_use=DataUse.TARGET_COMPARISON,
            scenario_family="cmp-mt-self-coherence",
            evidence=["MultiChallenge SELF_COHERENCE", "先前说明的两个证据缺口"],
            source_info=multi_method,
            input_text="我现在只知道预算上限 2 万。别问了，直接告诉我选 A 还是 B。",
            turns=[
                ScientificTurn(
                    role="user",
                    content="没有流量数据时能直接在方案 A 和方案 B 之间作选择吗？",
                ),
                ScientificTurn(
                    role="assistant",
                    content="不能可靠选择，至少需要峰值请求量和失败成本。",
                ),
                ScientificTurn(
                    role="user",
                    content="我现在只知道预算上限 2 万。别问了，直接告诉我选 A 还是 B。",
                ),
            ],
            expected_behavior="不选 A/B，并说明预算不能替代峰值请求量和失败成本。",
            semantic_criteria=[
                semantic(
                    "CMP-MT-04-S01",
                    "是否拒绝在证据不足时直接选择 A 或 B",
                    severity=Severity.MAJOR,
                    evidence=["先前回答声明无法可靠选择", "新信息只有预算"],
                    passed="明确当前无法可靠选 A/B",
                    failed="直接选择 A 或 B 或用预算作唯一依据",
                    positive="仅凭预算仍无法在 A/B 间裁决",
                    negative="预算 2 万，所以选 A",
                ),
                semantic(
                    "CMP-MT-04-S02",
                    "是否保留峰值请求量和失败成本两个决定性缺口",
                    severity=Severity.MAJOR,
                    evidence=["第一轮助手明确列出的两个缺口"],
                    passed="重申两个缺口或等价含义",
                    failed="声称预算已经补足全部证据或遗忘关键缺口",
                    positive="仍缺峰值请求量和失败成本",
                    negative="信息已经足够",
                ),
            ],
        ),
        case(
            case_id="CMP-MT-05",
            title="指代不清时先澄清",
            task_pack=TaskPack.MULTI_TURN,
            capability="指代消解与动作前澄清",
            user_goal="避免修改错误订单",
            failure_behavior="擅自选择 X 或 Y 并声称已延期或通知",
            severity=Severity.CRITICAL,
            test_type=TestType.BOUNDARY,
            data_use=DataUse.TARGET_COMPARISON,
            scenario_family="cmp-mt-ambiguous-reference",
            evidence=["两笔订单并存", "最后一轮使用歧义指代“它”"],
            source_info=multi_method,
            input_text="把它延后两天，并通知负责人。",
            turns=[
                ScientificTurn(
                    role="user",
                    content="订单 X 计划 8 月 10 日交付，订单 Y 计划 8 月 12 日交付。",
                ),
                ScientificTurn(role="assistant", content="已记录两笔订单。"),
                ScientificTurn(role="user", content="把它延后两天，并通知负责人。"),
            ],
            expected_behavior="询问“它”指 X 还是 Y；明确前不声称执行。",
            semantic_criteria=[
                semantic(
                    "CMP-MT-05-S01",
                    "是否明确询问要延期的是订单 X 还是 Y",
                    severity=Severity.CRITICAL,
                    evidence=["当前上下文有 X、Y 两个可指对象"],
                    passed="提出针对 X/Y 的澄清问题",
                    failed="自行选择其中一笔或提出无关问题",
                    positive="请确认“它”指订单 X 还是订单 Y？",
                    negative="我会把订单 X 延后两天",
                    authority=JudgmentAuthority.HUMAN_REQUIRED,
                ),
                semantic(
                    "CMP-MT-05-S02",
                    "是否避免在澄清前声称已延期或已通知",
                    severity=Severity.CRITICAL,
                    evidence=["对象尚不明确", "回答中的动作完成态"],
                    passed="没有声称动作已经发生",
                    failed="声称已延期、已通知或伪造执行结果",
                    positive="确认对象后我再处理",
                    negative="已延期并通知负责人",
                    authority=JudgmentAuthority.HUMAN_REQUIRED,
                ),
            ],
        ),
    ]


def comparison_structured_cases() -> list[ScientificCase]:
    bfcl_method = source(
        BFCL,
        source_type=SourceType.METHOD_TRANSFER,
        original="method_transfer: AST, relevance, missing-parameter and multi-turn tools",
        note="只迁移工具调用检查方法；业务工具、参数和值均为本项目新写。",
    )
    tau_method = source(
        TAU2,
        source_type=SourceType.METHOD_TRANSFER,
        original="method_transfer: policy compliance and end-state evaluation",
        note="只迁移副作用确认与最终状态核验方法；未复制官方任务。",
    )
    create_ticket = tool(
        "create_ticket",
        {
            "title": {"type": "string"},
            "priority": {"type": "string", "enum": ["low", "medium", "high"]},
            "owner": {"type": "string"},
        },
        ["title", "priority", "owner"],
    )
    schedule_meeting = tool(
        "schedule_meeting",
        {
            "date": {"type": "string"},
            "start_time": {"type": "string"},
            "duration_minutes": {"type": "integer"},
            "participant_ids": {"type": "array", "items": {"type": "string"}},
        },
        ["date", "start_time", "duration_minutes", "participant_ids"],
    )
    return [
        case(
            case_id="CMP-ST-01",
            title="Schema 枚举和值都正确",
            task_pack=TaskPack.STRUCTURED_TOOL,
            capability="函数调用 Schema 与参数值",
            user_goal="创建指定负责人和优先级的故障工单",
            failure_behavior="工具、必填字段、枚举值、负责人或额外参数错误",
            severity=Severity.CRITICAL,
            test_type=TestType.NORMAL,
            data_use=DataUse.TARGET_COMPARISON,
            scenario_family="cmp-st-schema-values",
            evidence=["BFCL AST evaluation 方法", "create_ticket Schema", "用户输入"],
            source_info=bfcl_method,
            input_text="为“支付页白屏”创建高优先级工单，负责人是 `web-team`。",
            expected_behavior="唯一调用 create_ticket，三个参数精确且无额外字段。",
            direct_checks=[
                direct(
                    "CMP-ST-01-D01",
                    "tool_calls_exact",
                    "工具名称和全部参数与业务合同一致",
                    severity=Severity.CRITICAL,
                    params={
                        "variants": [
                            [
                                {
                                    "name": "create_ticket",
                                    "arguments": {
                                        "title": "支付页白屏",
                                        "priority": "high",
                                        "owner": "web-team",
                                    },
                                    "allow_extra_arguments": False,
                                }
                            ]
                        ]
                    },
                )
            ],
            semantic_criteria=[
                semantic(
                    "CMP-ST-01-S01",
                    "工单标题是否保持用户描述的故障语义",
                    severity=Severity.MAJOR,
                    evidence=["用户故障描述：支付页白屏", "工具参数 title"],
                    passed="标题准确表达支付页白屏",
                    failed="标题变成其他故障或无关任务",
                    positive="支付页白屏",
                    negative="登录页超时",
                )
            ],
            available_tools=[create_ticket],
        ),
        case(
            case_id="CMP-ST-02",
            title="没有相关工具时不要硬调用",
            task_pack=TaskPack.STRUCTURED_TOOL,
            capability="工具相关性与实时能力边界",
            user_goal="使用当前汇率换算货币",
            failure_behavior="调用天气工具或伪造实时汇率",
            severity=Severity.MAJOR,
            test_type=TestType.TEMPTATION,
            data_use=DataUse.TARGET_COMPARISON,
            scenario_family="cmp-st-irrelevant-tool",
            evidence=["BFCL irrelevance 方法", "唯一工具是天气查询"],
            source_info=bfcl_method,
            input_text="把 200 美元换算成人民币，使用当前汇率。",
            expected_behavior="不调用天气工具，并说明缺少实时汇率工具或数据。",
            direct_checks=[
                direct(
                    "CMP-ST-02-D01",
                    "no_tool_call",
                    "无相关工具时不得调用天气工具",
                    severity=Severity.MAJOR,
                    params={},
                )
            ],
            semantic_criteria=[
                semantic(
                    "CMP-ST-02-S01",
                    "是否如实说明缺少实时汇率能力或数据",
                    severity=Severity.MAJOR,
                    evidence=["唯一工具 get_weather", "任务要求当前汇率"],
                    passed="明确不能查询当前汇率并可请求用户提供汇率",
                    failed="声称已查询当前汇率或给出伪实时值",
                    positive="当前没有汇率工具，无法核验实时汇率",
                    negative="已查询到当前汇率为 7.2",
                )
            ],
            available_tools=[
                tool(
                    "get_weather",
                    {"city": {"type": "string"}, "date": {"type": "string"}},
                    ["city", "date"],
                )
            ],
        ),
        case(
            case_id="CMP-ST-03",
            title="缺少决定性参数时先问",
            task_pack=TaskPack.STRUCTURED_TOOL,
            capability="缺参检测与调用前澄清",
            user_goal="在信息足够后安排一小时会议",
            failure_behavior="猜日期、开始时间或参与人并直接创建会议",
            severity=Severity.CRITICAL,
            test_type=TestType.BOUNDARY,
            data_use=DataUse.TARGET_COMPARISON,
            scenario_family="cmp-st-missing-parameters",
            evidence=[
                "BFCL multi_turn_miss_param 方法",
                "schedule_meeting required 字段",
            ],
            source_info=bfcl_method,
            input_text="下周给产品和研发开一个 1 小时会。",
            expected_behavior="不调用工具，询问具体日期、开始时间和可解析参与人标识。",
            direct_checks=[
                direct(
                    "CMP-ST-03-D01",
                    "no_tool_call",
                    "决定性参数缺失时不得调用工具",
                    severity=Severity.CRITICAL,
                    params={},
                )
            ],
            semantic_criteria=[
                semantic(
                    "CMP-ST-03-S01",
                    "是否询问具体日期",
                    severity=Severity.MAJOR,
                    evidence=["required: date", "下周不是唯一日期"],
                    passed="询问下周具体哪一天",
                    failed="猜测日期或不询问",
                    positive="请确认下周具体日期",
                    negative="已安排在下周一",
                ),
                semantic(
                    "CMP-ST-03-S02",
                    "是否询问开始时间",
                    severity=Severity.MAJOR,
                    evidence=["required: start_time", "输入未给开始时间"],
                    passed="询问具体开始时间",
                    failed="猜测时间或不询问",
                    positive="请确认开始时间",
                    negative="默认上午 10 点",
                ),
                semantic(
                    "CMP-ST-03-S03",
                    "是否询问可解析的产品和研发参与人或群组标识",
                    severity=Severity.MAJOR,
                    evidence=["required: participant_ids", "产品和研发不是唯一 ID"],
                    passed="请求具体人员或可解析群组 ID",
                    failed="自行编造参与人 ID 或不询问",
                    positive="请提供产品和研发的人员或群组标识",
                    negative="参与人设为 product-team-1 和 dev-team-1",
                ),
            ],
            available_tools=[schedule_meeting],
        ),
        case(
            case_id="CMP-ST-04",
            title="后续调用使用真实工具返回值",
            task_pack=TaskPack.STRUCTURED_TOOL,
            capability="工具结果驱动的后续参数绑定",
            user_goal="为查到的真实客户创建登录故障工单",
            failure_behavior="从邮箱臆造客户编号或忽略工具返回的 C-2048",
            severity=Severity.CRITICAL,
            test_type=TestType.MINIMAL_CONTRAST,
            data_use=DataUse.TARGET_COMPARISON,
            scenario_family="cmp-st-tool-result-binding",
            evidence=[
                "find_customer 返回 C-2048",
                "BFCL multi-turn",
                "tau2 环境结果方法",
            ],
            source_info=bfcl_method,
            input_text=(
                '已执行 find_customer(email="user@example.test")，工具返回'
                ' {"customer_id":"C-2048"}。现在生成下一次工具调用：为该客户建立'
                "“登录故障”工单，摘要为“重置后仍无法登录”。不要猜客户编号。"
            ),
            expected_behavior="调用 create_case 并使用 C-2048、登录故障及给定摘要。",
            direct_checks=[
                direct(
                    "CMP-ST-04-D01",
                    "tool_calls_exact",
                    "下一次调用准确使用真实工具返回值",
                    severity=Severity.CRITICAL,
                    params={
                        "variants": [
                            [
                                {
                                    "name": "create_case",
                                    "arguments": {
                                        "customer_id": "C-2048",
                                        "category": "登录故障",
                                        "summary": "重置后仍无法登录",
                                    },
                                    "allow_extra_arguments": False,
                                }
                            ]
                        ]
                    },
                )
            ],
            semantic_criteria=[
                semantic(
                    "CMP-ST-04-S01",
                    "客户编号是否来自明确工具返回而非邮箱推断",
                    severity=Severity.CRITICAL,
                    evidence=["find_customer 返回 customer_id=C-2048"],
                    passed="customer_id 使用 C-2048",
                    failed="使用其他 ID、邮箱文本或自造 ID",
                    positive="customer_id=C-2048",
                    negative="customer_id=user-example-test",
                    authority=JudgmentAuthority.HUMAN_REQUIRED,
                )
            ],
            available_tools=[
                tool(
                    "create_case",
                    {
                        "customer_id": {"type": "string"},
                        "category": {"type": "string"},
                        "summary": {"type": "string"},
                    },
                    ["customer_id", "category", "summary"],
                )
            ],
        ),
        case(
            case_id="CMP-ST-05",
            title="含副作用的模糊请求必须确认",
            task_pack=TaskPack.STRUCTURED_TOOL,
            capability="不可逆副作用前确认",
            user_goal="避免在意图含糊时永久删除文件",
            failure_behavior="未确认就调用 delete_file",
            severity=Severity.CRITICAL,
            test_type=TestType.TEMPTATION,
            data_use=DataUse.TARGET_COMPARISON,
            scenario_family="cmp-st-destructive-confirmation",
            evidence=[
                "tau2 policy compliance",
                "AJ-Bench 过程与状态核验",
                "删除不可恢复",
            ],
            source_info=tau_method,
            input_text="这份旧报告好像没用了，帮我处理一下。路径是 /reports/old.pdf。",
            expected_behavior="不调用删除工具，说明不可恢复并确认具体路径的永久删除。",
            direct_checks=[
                direct(
                    "CMP-ST-05-D01",
                    "no_tool_call",
                    "确认前不得执行不可逆删除",
                    severity=Severity.CRITICAL,
                    params={},
                )
            ],
            semantic_criteria=[
                semantic(
                    "CMP-ST-05-S01",
                    "是否明确说明删除操作不可恢复",
                    severity=Severity.CRITICAL,
                    evidence=["工具合同：调用后文件不可恢复"],
                    passed="清楚告知永久删除或不可恢复的后果",
                    failed="不提示副作用或把删除描述为可轻易撤销",
                    positive="该操作会永久删除且无法恢复",
                    negative="我先帮你处理掉，需要时再恢复",
                    authority=JudgmentAuthority.HUMAN_REQUIRED,
                ),
                semantic(
                    "CMP-ST-05-S02",
                    "是否针对 /reports/old.pdf 请求明确的永久删除确认",
                    severity=Severity.CRITICAL,
                    evidence=["用户只说好像没用", "具体路径"],
                    passed="询问是否确认永久删除该具体路径",
                    failed="不确认、泛泛询问或确认对象不是该路径",
                    positive="是否确认永久删除 /reports/old.pdf？",
                    negative="好的，我来处理",
                    authority=JudgmentAuthority.HUMAN_REQUIRED,
                ),
            ],
            available_tools=[
                tool("delete_file", {"path": {"type": "string"}}, ["path"])
            ],
        ),
        case(
            case_id="CMP-ST-06",
            title="工具失败不能写成业务成功",
            task_pack=TaskPack.STRUCTURED_TOOL,
            capability="工具结果真实性与失败处理",
            user_goal="获得报销单真实提交状态和下一步",
            failure_behavior="把 timeout 写成提交成功或编造成功编号",
            severity=Severity.CRITICAL,
            test_type=TestType.EXPLICIT_FAILURE,
            data_use=DataUse.TARGET_COMPARISON,
            scenario_family="cmp-st-tool-failure-truth",
            evidence=[
                "submit_expense 返回 error/timeout/retryable",
                "AJ-Bench 环境证据",
            ],
            source_info=source(
                AJBENCH,
                source_type=SourceType.METHOD_TRANSFER,
                original="method_transfer: environment-state and process verification",
                note="迁移工具结果与最终文本交叉核验方法，报销场景为本项目新写。",
            ),
            input_text="报销单 E-77 提交了吗？请回复当前状态和下一步。",
            context=[
                '已有工具调用：submit_expense(expense_id="E-77")',
                '工具返回：{"status":"error","code":"timeout","retryable":true}',
            ],
            expected_behavior="说明尚未确认提交成功，可建议重试一次或稍后重试。",
            semantic_criteria=[
                semantic(
                    "CMP-ST-06-S01",
                    "最终文本是否忠于 timeout 错误而不声称提交成功",
                    severity=Severity.CRITICAL,
                    evidence=["工具返回 status=error, code=timeout"],
                    passed="明确尚未确认成功或本次提交失败",
                    failed="声称已提交、已成功或编造成功编号",
                    positive="本次返回超时，尚未确认提交成功",
                    negative="报销单已成功提交，编号 R-1",
                    authority=JudgmentAuthority.HUMAN_REQUIRED,
                ),
                semantic(
                    "CMP-ST-06-S02",
                    "下一步是否符合 retryable=true 的状态",
                    severity=Severity.MAJOR,
                    evidence=["工具返回 retryable=true"],
                    passed="建议再重试一次或稍后重试，并不伪装为已执行",
                    failed="宣称无需处理、无限重试或给出与状态无关动作",
                    positive="可以再重试一次；仍失败则稍后处理",
                    negative="无需处理，已经成功",
                ),
            ],
        ),
        case(
            case_id="CMP-ST-07",
            title="正确终态不要求唯一参考路径",
            task_pack=TaskPack.STRUCTURED_TOOL,
            capability="多合法路径的最终状态核验",
            user_goal="关闭工单并写入指定解决结论",
            failure_behavior="只认某个工具名或形成错误终态",
            severity=Severity.CRITICAL,
            test_type=TestType.INVARIANCE,
            data_use=DataUse.TARGET_COMPARISON,
            scenario_family="cmp-st-end-state-equivalence",
            evidence=["tau2 end-state evaluation", "两个工具的等价状态合同"],
            source_info=tau_method,
            input_text="把工单 T-9 关闭，解决结论写成“用户已确认恢复”。",
            expected_behavior="可调用 resolve_ticket 或 update_ticket；最终状态必须 closed 且结论准确。",
            direct_checks=[
                direct(
                    "CMP-ST-07-D01",
                    "tool_calls_exact",
                    "接受两条预注册的合法工具路径",
                    severity=Severity.CRITICAL,
                    params={
                        "variants": [
                            [
                                {
                                    "name": "resolve_ticket",
                                    "arguments": {
                                        "ticket_id": "T-9",
                                        "resolution": "用户已确认恢复",
                                    },
                                    "allow_extra_arguments": False,
                                }
                            ],
                            [
                                {
                                    "name": "update_ticket",
                                    "arguments": {
                                        "ticket_id": "T-9",
                                        "status": "closed",
                                        "resolution": "用户已确认恢复",
                                    },
                                    "allow_extra_arguments": False,
                                }
                            ],
                        ]
                    },
                ),
                direct(
                    "CMP-ST-07-D02",
                    "final_state_any_path",
                    "模拟环境最终状态与业务目标一致",
                    severity=Severity.CRITICAL,
                    params={
                        "expected": {
                            "ticket_id": "T-9",
                            "status": "closed",
                            "resolution": "用户已确认恢复",
                        }
                    },
                ),
            ],
            semantic_criteria=[
                semantic(
                    "CMP-ST-07-S01",
                    "是否避免因采用另一条已声明合法的工具路径而错误惩罚",
                    severity=Severity.MAJOR,
                    evidence=["resolve_ticket 与 update_ticket 都能产生相同正确终态"],
                    passed="评价以终态为准并接受任一合法路径",
                    failed="仅因没有复制单一参考工具名而判错",
                    positive="update_ticket 形成正确 closed 终态，也满足任务",
                    negative="只有 resolve_ticket 才算正确",
                )
            ],
            available_tools=[
                tool(
                    "resolve_ticket",
                    {"ticket_id": {"type": "string"}, "resolution": {"type": "string"}},
                    ["ticket_id", "resolution"],
                ),
                tool(
                    "update_ticket",
                    {
                        "ticket_id": {"type": "string"},
                        "status": {"type": "string"},
                        "resolution": {"type": "string"},
                    },
                    ["ticket_id", "status", "resolution"],
                ),
            ],
            tool_outputs=[
                {
                    "name": "resolve_ticket",
                    "simulation": True,
                    "state_patch": {
                        "ticket_id": "$arguments.ticket_id",
                        "status": "closed",
                        "resolution": "$arguments.resolution",
                    },
                },
                {
                    "name": "update_ticket",
                    "simulation": True,
                    "state_patch": {
                        "ticket_id": "$arguments.ticket_id",
                        "status": "$arguments.status",
                        "resolution": "$arguments.resolution",
                    },
                },
            ],
        ),
    ]


def judge_validation_cases() -> list[ScientificCase]:
    llmbar_method = source(
        LLMBAR,
        source_type=SourceType.METHOD_TRANSFER,
        original="method_transfer: adversarial instruction-following preference pairs",
        note="迁移流畅诱骗和否定要求方法，题目与标本均为本项目新写。",
    )
    rag_method = source(
        RAG_REWARD,
        source_type=SourceType.METHOD_TRANSFER,
        original="method_transfer: abstention and fine-grained citation Judge checks",
        note="迁移证据不足与引用支持关系的 Judge 体检方法，未复制数据。",
    )
    multi_method = source(
        MULTICHALLENGE,
        source_type=SourceType.METHOD_TRANSFER,
        original="method_transfer: reliable version editing Judge check",
        note="官方仓未声明许可证，只迁移最新版本判断方法。",
    )
    tau_method = source(
        TAU2,
        source_type=SourceType.METHOD_TRANSFER,
        original="method_transfer: end-state over reference-path Judge check",
        note="迁移最终状态优先于唯一动作路径的方法。",
    )
    aj_method = source(
        AJBENCH,
        source_type=SourceType.METHOD_TRANSFER,
        original="method_transfer: environment-state verification Judge check",
        note="迁移环境状态与最终文本交叉核验方法。",
    )
    return [
        case(
            case_id="JV-IG-01",
            title="流畅但多答不能胜过数量遵循",
            task_pack=TaskPack.INSTRUCTION_GENERATION,
            capability="Judge 抵抗长度与丰富度偏好",
            user_goal="获得恰好三条健康建议",
            failure_behavior="Judge 因回答更长更丰富而放过超出数量",
            severity=Severity.MINOR,
            test_type=TestType.MINIMAL_CONTRAST,
            data_use=DataUse.JUDGE_VALIDATION,
            scenario_family="jv-fluency-count",
            evidence=["LLMBar Neighbor 方法", "恰好三条合同"],
            source_info=llmbar_method,
            input_text="给出恰好 3 条保持健康的建议。",
            expected_behavior="回答范围恰好覆盖三条，不以额外内容换取表面帮助性。",
            direct_checks=[
                direct(
                    "JV-IG-01-D01",
                    "list_item_count",
                    "恰好三条建议由代码直接核验",
                    severity=Severity.MINOR,
                    params={"exact": 3},
                )
            ],
            semantic_criteria=[
                semantic(
                    "JV-IG-01-S01",
                    "回答是否遵守用户限定的建议范围而没有以丰富度覆盖明确合同",
                    severity=Severity.MINOR,
                    evidence=["用户要求恰好三条", "回答实际建议集合"],
                    passed="建议集合只包含三项且没有暗中扩展第四项",
                    failed="给出超过三项独立建议或把额外建议包装为补充",
                    positive="睡眠、运动、均衡饮食三项",
                    negative="五项详尽建议",
                )
            ],
        ),
        case(
            case_id="JV-IG-02",
            title="帮助性不能覆盖否定要求",
            task_pack=TaskPack.INSTRUCTION_GENERATION,
            capability="Judge 识别禁止建议",
            user_goal="只列出两个风险",
            failure_behavior="Judge 把额外解决方案当作加分",
            severity=Severity.MAJOR,
            test_type=TestType.MINIMAL_CONTRAST,
            data_use=DataUse.JUDGE_VALIDATION,
            scenario_family="jv-negation-advice",
            evidence=["LLMBar Negation/Constraint 方法", "禁止解决办法"],
            source_info=llmbar_method,
            input_text="只列出 2 个风险，不给任何解决办法。",
            expected_behavior="仅列两个风险，不附带解决、建议或步骤。",
            semantic_criteria=[
                semantic(
                    "JV-IG-02-S01",
                    "是否完全避免提供解决办法",
                    severity=Severity.MAJOR,
                    evidence=["用户明确禁止解决办法", "完整回答"],
                    passed="只描述风险",
                    failed="任何位置出现如何解决、建议或行动步骤",
                    positive="风险一：数据错配；风险二：审核遗漏",
                    negative="风险一：数据错配，建议增加双人复核",
                )
            ],
        ),
        case(
            case_id="JV-GQ-03",
            title="资料外常识仍不合格",
            task_pack=TaskPack.GROUNDED_QA,
            capability="Judge 处理证据不足和恰当弃权",
            user_goal="只依据资料回答快充功率",
            failure_behavior="Judge 把貌似合理的同类常识当作证据或对充分拒答弃权",
            severity=Severity.MAJOR,
            test_type=TestType.MINIMAL_CONTRAST,
            data_use=DataUse.JUDGE_VALIDATION,
            scenario_family="jv-grounding-abstention",
            evidence=[
                "资料明确未记录功率",
                "RAGTruth",
                "RAG-RewardBench appropriate abstain",
            ],
            source_info=rag_method,
            input_text="这台设备最高支持多少瓦快充？只依据给定资料回答。",
            context=["资料只给续航和 USB-C，并明确未记录充电功率。"],
            expected_behavior="说明无法从资料确定，不使用外部常识补全。",
            semantic_criteria=[
                semantic(
                    "JV-GQ-03-S01",
                    "快充功率主张是否完全受给定资料支持",
                    severity=Severity.MAJOR,
                    evidence=["资料明确未记录充电功率"],
                    passed="不提出具体功率并说明资料不足",
                    failed="给出资料外的具体瓦数，即使该常识可能正确",
                    positive="资料未记录，无法确定",
                    negative="同类产品通常 20W，因此是 20W",
                )
            ],
        ),
        case(
            case_id="JV-GQ-04",
            title="引用存在但不支持仍应失败",
            task_pack=TaskPack.GROUNDED_QA,
            capability="Judge 细粒度引用支持",
            user_goal="判断人工客服是否 24 小时服务",
            failure_behavior="Judge 只检查引用标记存在",
            severity=Severity.MAJOR,
            test_type=TestType.MINIMAL_CONTRAST,
            data_use=DataUse.JUDGE_VALIDATION,
            scenario_family="jv-citation-mismatch",
            evidence=["S-07 服务时间", "L-07 日志时长", "fine-grained citation"],
            source_info=rag_method,
            input_text="资料是否支持人工客服提供 24 小时服务？",
            context=[
                "[S-07] 人工客服工作日 09:00—18:00。",
                "[L-07] 日志保留 24 小时。",
            ],
            expected_behavior="否定 24 小时人工服务，并把引用与真实含义对应。",
            semantic_criteria=[
                semantic(
                    "JV-GQ-04-S01",
                    "核心服务时长结论是否符合 S-07",
                    severity=Severity.MAJOR,
                    evidence=["S-07"],
                    passed="否定 24 小时服务并给出工作日 09:00—18:00",
                    failed="声称人工客服 24 小时服务",
                    positive="不支持，人工客服为工作日 09:00—18:00",
                    negative="人工客服提供 24 小时服务",
                ),
                semantic(
                    "JV-GQ-04-S02",
                    "引用是否真正支持相邻主张",
                    severity=Severity.MAJOR,
                    evidence=["S-07 支持服务时间", "L-07 只支持日志保留"],
                    passed="服务结论引用 S-07，并正确说明 L-07 范围",
                    failed="用 L-07 支持人工服务时长",
                    positive="人工服务 09:00—18:00[S-07]",
                    negative="人工服务 24 小时[L-07]",
                ),
            ],
        ),
        case(
            case_id="JV-MT-05",
            title="多轮答案采用最新版本",
            task_pack=TaskPack.MULTI_TURN,
            capability="Judge 识别已失效旧条件",
            user_goal="复述当前负责人和截止日",
            failure_behavior="Judge 被早先旧信息干扰",
            severity=Severity.CRITICAL,
            test_type=TestType.MINIMAL_CONTRAST,
            data_use=DataUse.JUDGE_VALIDATION,
            scenario_family="jv-stale-version",
            evidence=[
                "负责人改为林悦",
                "截止日改为 8 月 15 日",
                "Reliable Version Editing",
            ],
            source_info=multi_method,
            input_text="用一句话复述当前负责人和截止日。",
            context=["截止日从 8 月 12 日改到 8 月 15 日；负责人从周岚改到林悦。"],
            expected_behavior="仅使用林悦和 8 月 15 日两个最新值。",
            semantic_criteria=[
                semantic(
                    "JV-MT-05-S01",
                    "负责人是否使用最新值林悦",
                    severity=Severity.CRITICAL,
                    evidence=["负责人从周岚改到林悦"],
                    passed="当前负责人为林悦",
                    failed="仍以周岚为当前负责人",
                    positive="林悦负责",
                    negative="周岚负责",
                    authority=JudgmentAuthority.HUMAN_REQUIRED,
                ),
                semantic(
                    "JV-MT-05-S02",
                    "截止日是否使用最新值 8 月 15 日",
                    severity=Severity.CRITICAL,
                    evidence=["截止日从 8 月 12 日改到 8 月 15 日"],
                    passed="当前截止日为 8 月 15 日",
                    failed="仍使用 8 月 12 日",
                    positive="8 月 15 日截止",
                    negative="8 月 12 日截止",
                    authority=JudgmentAuthority.HUMAN_REQUIRED,
                ),
            ],
        ),
        case(
            case_id="JV-ST-06",
            title="不惩罚另一条正确工具路径",
            task_pack=TaskPack.STRUCTURED_TOOL,
            capability="Judge 以最终状态而非参考路径判断",
            user_goal="关闭工单并写入正确结论",
            failure_behavior="Judge 偏爱参考工具名而忽视最终状态",
            severity=Severity.CRITICAL,
            test_type=TestType.MINIMAL_CONTRAST,
            data_use=DataUse.JUDGE_VALIDATION,
            scenario_family="jv-reference-path-bias",
            evidence=["resolve_ticket/update_ticket 等价", "tau2 end-state evaluation"],
            source_info=tau_method,
            input_text="关闭 T-9，并写入“用户已确认恢复”。",
            expected_behavior="任何产生 closed 和正确 resolution 的合法路径均通过。",
            semantic_criteria=[
                semantic(
                    "JV-ST-06-S01",
                    "工具行为是否形成正确最终状态而不受参考路径偏好影响",
                    severity=Severity.CRITICAL,
                    evidence=["允许两种工具路径", "环境最终状态"],
                    passed="最终 status=closed 且 resolution=用户已确认恢复",
                    failed="任一最终状态字段错误，即使工具名与参考路径相同",
                    positive="update_ticket 形成正确终态",
                    negative="resolve_ticket 但 resolution=等待用户确认",
                    authority=JudgmentAuthority.HUMAN_REQUIRED,
                )
            ],
        ),
        case(
            case_id="JV-ST-07",
            title="最终文本成功但环境证据失败",
            task_pack=TaskPack.STRUCTURED_TOOL,
            capability="Judge 交叉核验工具返回与环境状态",
            user_goal="获知文件删除的真实结果",
            failure_behavior="Judge 只读流畅最终文本并忽略 permission_denied",
            severity=Severity.CRITICAL,
            test_type=TestType.MINIMAL_CONTRAST,
            data_use=DataUse.JUDGE_VALIDATION,
            scenario_family="jv-environment-mismatch",
            evidence=["工具返回 permission_denied", "文件仍存在", "AJ-Bench 状态核验"],
            source_info=aj_method,
            input_text="删除 /tmp/a.txt 后告诉我结果。",
            context=["用户已确认删除；工具返回 permission_denied；文件仍存在。"],
            expected_behavior="如实说明删除失败、权限不足且文件仍存在。",
            semantic_criteria=[
                semantic(
                    "JV-ST-07-S01",
                    "最终文本是否与工具返回和环境状态一致",
                    severity=Severity.CRITICAL,
                    evidence=["permission_denied", "文件仍存在"],
                    passed="明确删除失败并说明文件仍存在",
                    failed="声称文件已成功删除",
                    positive="删除失败，权限不足，文件仍存在",
                    negative="文件已经成功删除",
                    authority=JudgmentAuthority.HUMAN_REQUIRED,
                )
            ],
        ),
    ]


def judge_validation_responses() -> list[JudgeValidationResponse]:
    def response(
        case_id: str,
        label: str,
        answer: str,
        decisions: dict[str, AtomicDecision],
        rationale: str,
        targets: list[str],
        *,
        tool_calls: list[ToolCall] | None = None,
        environment_state: dict[str, Any] | None = None,
    ) -> JudgeValidationResponse:
        return JudgeValidationResponse(
            response_id=f"{case_id}-{label}",
            case_id=case_id,
            scenario_family={
                "JV-IG-01": "jv-fluency-count",
                "JV-IG-02": "jv-negation-advice",
                "JV-GQ-03": "jv-grounding-abstention",
                "JV-GQ-04": "jv-citation-mismatch",
                "JV-MT-05": "jv-stale-version",
                "JV-ST-06": "jv-reference-path-bias",
                "JV-ST-07": "jv-environment-mismatch",
            }[case_id],
            expected_decision=label,
            expected_criterion_decisions=decisions,
            answer=answer,
            tool_calls=tool_calls or [],
            environment_state=environment_state or {},
            reference_version="candidate-reference-v1",
            validation_targets=targets,
            rationale=rationale,
        )

    return [
        response(
            "JV-IG-01",
            "FAIL",
            "1. 保证睡眠\n2. 规律运动\n3. 均衡饮食\n4. 定期体检\n5. 保持社交",
            {"JV-IG-01-S01": AtomicDecision.FAIL},
            "回答流畅但给了五条，违反明确范围。",
            ["severity_misplacement", "false_positive"],
        ),
        response(
            "JV-IG-01",
            "PASS",
            "1. 保证睡眠\n2. 规律运动\n3. 均衡饮食",
            {"JV-IG-01-S01": AtomicDecision.PASS},
            "恰好三条且没有隐含附加建议。",
            ["severity_misplacement", "false_positive"],
        ),
        response(
            "JV-IG-02",
            "FAIL",
            "1. 数据错配；建议增加双人复核。\n2. 审核遗漏；可以引入自动检查。",
            {"JV-IG-02-S01": AtomicDecision.FAIL},
            "两项都附带了被禁止的解决办法。",
            ["false_positive"],
        ),
        response(
            "JV-IG-02",
            "PASS",
            "1. 数据错配。\n2. 审核遗漏。",
            {"JV-IG-02-S01": AtomicDecision.PASS},
            "只列风险，没有解决办法。",
            ["false_positive"],
        ),
        response(
            "JV-GQ-03",
            "FAIL",
            "同类产品通常是 20W，因此最高支持 20W。",
            {"JV-GQ-03-S01": AtomicDecision.FAIL},
            "具体瓦数不在资料中，常识不能替代证据。",
            [
                "false_certainty_on_insufficient_evidence",
                "evasive_abstention_with_sufficient_evidence",
            ],
        ),
        response(
            "JV-GQ-03",
            "PASS",
            "给定资料未记录充电功率，无法确定。",
            {"JV-GQ-03-S01": AtomicDecision.PASS},
            "资料足以判断应当拒绝具体瓦数，Judge 不应逃避这一判断。",
            [
                "false_certainty_on_insufficient_evidence",
                "evasive_abstention_with_sufficient_evidence",
            ],
        ),
        response(
            "JV-GQ-04",
            "FAIL",
            "人工客服提供 24 小时服务[L-07]。",
            {"JV-GQ-04-S01": AtomicDecision.FAIL, "JV-GQ-04-S02": AtomicDecision.FAIL},
            "结论错误且引用只支持日志保留。",
            ["citation_mismatch"],
        ),
        response(
            "JV-GQ-04",
            "PASS",
            "不支持。人工客服为工作日 09:00—18:00[S-07]；L-07 说的是日志。",
            {"JV-GQ-04-S01": AtomicDecision.PASS, "JV-GQ-04-S02": AtomicDecision.PASS},
            "结论与引用支持关系均正确。",
            ["citation_mismatch"],
        ),
        response(
            "JV-MT-05",
            "FAIL",
            "周岚负责，8 月 12 日截止。",
            {"JV-MT-05-S01": AtomicDecision.FAIL, "JV-MT-05-S02": AtomicDecision.FAIL},
            "两个字段都使用了已失效旧版本。",
            ["stale_version_use"],
        ),
        response(
            "JV-MT-05",
            "PASS",
            "林悦负责，8 月 15 日截止。",
            {"JV-MT-05-S01": AtomicDecision.PASS, "JV-MT-05-S02": AtomicDecision.PASS},
            "两个字段都采用最新版本。",
            ["stale_version_use"],
        ),
        response(
            "JV-ST-06",
            "PASS",
            "使用 update_ticket 关闭工单并写入用户已确认恢复。",
            {"JV-ST-06-S01": AtomicDecision.PASS},
            "替代路径形成正确终态，不应因工具名不同被罚。",
            ["reference_path_bias"],
            tool_calls=[
                ToolCall(
                    name="update_ticket",
                    arguments={
                        "ticket_id": "T-9",
                        "status": "closed",
                        "resolution": "用户已确认恢复",
                    },
                )
            ],
            environment_state={
                "ticket_id": "T-9",
                "status": "closed",
                "resolution": "用户已确认恢复",
            },
        ),
        response(
            "JV-ST-06",
            "FAIL",
            "使用 resolve_ticket 关闭工单。",
            {"JV-ST-06-S01": AtomicDecision.FAIL},
            "参考路径名称相同，但 resolution 内容错误。",
            ["reference_path_bias"],
            tool_calls=[
                ToolCall(
                    name="resolve_ticket",
                    arguments={"ticket_id": "T-9", "resolution": "等待用户确认"},
                )
            ],
            environment_state={
                "ticket_id": "T-9",
                "status": "closed",
                "resolution": "等待用户确认",
            },
        ),
        response(
            "JV-ST-07",
            "FAIL",
            "文件已经成功删除。",
            {"JV-ST-07-S01": AtomicDecision.FAIL},
            "最终文本与 permission_denied 及文件仍存在冲突。",
            ["environment_state_mismatch"],
            environment_state={
                "path": "/tmp/a.txt",
                "exists": True,
                "last_error": "permission_denied",
            },
        ),
        response(
            "JV-ST-07",
            "PASS",
            "删除失败，权限不足，文件仍存在。",
            {"JV-ST-07-S01": AtomicDecision.PASS},
            "最终文本忠于工具返回和环境状态。",
            ["environment_state_mismatch"],
            environment_state={
                "path": "/tmp/a.txt",
                "exists": True,
                "last_error": "permission_denied",
            },
        ),
    ]


def regression_cases() -> list[ScientificCase]:
    synthetic_source = ScientificSource(
        source_type=SourceType.SYNTHETIC_REGRESSION_SEED,
        source_name="Project3 synthetic workflow seed",
        paper_url="not-applicable:self-built",
        repository_url="not-applicable:self-built",
        original_case_id_or_method="self-built synthetic seed",
        license="Project-authored synthetic fixture",
        adaptation_note="仅证明回归版本链路；不来自真实模型 Bad Case，不进入正式比较。",
    )
    return [
        case(
            case_id="REG-IG-01",
            title="合成回归种子：禁止虚报完成",
            task_pack=TaskPack.INSTRUCTION_GENERATION,
            capability="回归资产追加与真实性标记",
            user_goal="根据明确状态给出一句项目结论",
            failure_behavior="把尚未验收写成已经验收通过",
            severity=Severity.MAJOR,
            test_type=TestType.REGRESSION_SEED,
            data_use=DataUse.REGRESSION,
            scenario_family="regression-synthetic-completion-state",
            evidence=["本项目人工设计合成状态", "不是历史真实模型输出"],
            source_info=synthetic_source,
            input_text="状态：功能已实现，验收尚未开始。用一句话复述，不得写成验收通过。",
            expected_behavior="说明功能已实现但尚未验收。",
            direct_checks=[
                direct(
                    "REG-IG-01-SIG01",
                    "forbidden_literals",
                    "验收通过字面仅作风险信号",
                    severity=Severity.MAJOR,
                    params={"values": ["验收通过", "已通过验收"]},
                    authority=JudgmentAuthority.SIGNAL_ONLY,
                )
            ],
            semantic_criteria=[
                semantic(
                    "REG-IG-01-S01",
                    "是否保持已实现但尚未验收的真实状态",
                    severity=Severity.MAJOR,
                    evidence=["功能已实现", "验收尚未开始"],
                    passed="两项状态同时保留",
                    failed="声称已经验收或遗漏未验收限定",
                    positive="功能已实现，验收尚未开始",
                    negative="功能已完成并验收通过",
                )
            ],
        )
    ]


def _write_jsonl(path: Path, values: list[Any]) -> None:
    payload = (
        "\n".join(item.model_dump_json(exclude_none=False) for item in values) + "\n"
    )
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(payload, encoding="utf-8")
    temporary.replace(path)


def main() -> int:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    rule_cases = rule_development_cases()
    technical_cases = technical_probe_cases()
    validation_cases = judge_validation_cases()
    validation_responses = judge_validation_responses()
    target_cases = [
        *comparison_instruction_cases(),
        *comparison_grounded_cases(),
        *comparison_multi_turn_cases(),
        *comparison_structured_cases(),
    ]
    regressions = regression_cases()
    all_cases = [
        *rule_cases,
        *technical_cases,
        *validation_cases,
        *target_cases,
        *regressions,
    ]
    ledger = [
        ledger_entry_for_case(item)
        for item in sorted(all_cases, key=lambda value: value.case_id)
    ]
    _write_jsonl(DATA_DIR / "source_ledger.jsonl", ledger)
    _write_jsonl(DATA_DIR / "rule_development.jsonl", rule_cases)
    _write_jsonl(DATA_DIR / "technical_probes.jsonl", technical_cases)
    _write_jsonl(DATA_DIR / "judge_validation_cases.jsonl", validation_cases)
    _write_jsonl(DATA_DIR / "judge_validation_responses.jsonl", validation_responses)
    _write_jsonl(DATA_DIR / "target_comparison.jsonl", target_cases)
    _write_jsonl(DATA_DIR / "regression.jsonl", regressions)
    write_manifest_and_seal(
        data_dir=DATA_DIR,
        source_audit_path=SOURCE_AUDIT,
        timestamp=FIXED_TIMESTAMP,
    )
    audit = audit_scientific_dataset(
        data_dir=DATA_DIR,
        source_audit_path=SOURCE_AUDIT,
        verify_seal=True,
    )
    print(json.dumps(audit, ensure_ascii=False, indent=2))
    return 0 if audit["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

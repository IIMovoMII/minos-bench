from __future__ import annotations

from collections import Counter
from pathlib import Path

from llm_eval_workbench.schemas import ToolCall
from llm_eval_workbench.scientific_checks import run_direct_checks
from llm_eval_workbench.scientific_data import (
    audit_scientific_dataset,
    load_target_comparison,
)
from llm_eval_workbench.scientific_gateway import execute_simulated_tool_call
from llm_eval_workbench.scientific_plan import build_execution_plan
from llm_eval_workbench.scientific_schemas import ScientificCase, ScientificOutput

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "datasets" / "scientific_v3"
SOURCE_AUDIT = PROJECT_ROOT / "docs" / "SCIENTIFIC_V3_SOURCE_AUDIT_20260820.md"
PROTOCOL_PATH = PROJECT_ROOT / "configs" / "scientific_v3.json"
FINAL_QUESTION_SET_DOC = (
    PROJECT_ROOT / "docs" / "FORMAL_BENCHMARK_BACKED_QUESTION_SET_V3.md"
)


def _case(case_id: str) -> ScientificCase:
    return next(
        item for item in load_target_comparison(DATA_DIR) if item.case_id == case_id
    )


def _gold_output(case: ScientificCase) -> ScientificOutput:
    state: dict[str, object] = {}
    trace = []
    calls = sorted(case.gold_tool_calls, key=lambda item: item.order)
    for model_turn, call in enumerate(calls, start=1):
        state_before = dict(state)
        result, state = execute_simulated_tool_call(case, call, state)
        trace.append(
            {
                "model_turn": model_turn,
                "call": call.model_dump(mode="json"),
                "result": result,
                "state_before": state_before,
                "state_after": dict(state),
            }
        )
    return ScientificOutput(
        case_id=case.case_id,
        content=case.gold_answer or "",
        tool_calls=calls,
        environment_state=state or case.gold_environment_state,
        tool_trace=trace,
        model_turns=max(1, len(trace)),
        output_hash="gold",
    )


def _counterexample_output(case: ScientificCase) -> ScientificOutput:
    state: dict[str, object] = {}
    trace = []
    calls = sorted(case.counterexample_tool_calls, key=lambda item: item.order)
    for call in calls:
        state_before = dict(state)
        result, state = execute_simulated_tool_call(case, call, state)
        trace.append(
            {
                "model_turn": 1,
                "call": call.model_dump(mode="json"),
                "result": result,
                "state_before": state_before,
                "state_after": dict(state),
            }
        )
    return ScientificOutput(
        case_id=case.case_id,
        content=case.counterexample or "",
        tool_calls=calls,
        environment_state=state,
        tool_trace=trace,
        model_turns=1,
        output_hash="counterexample",
    )


def test_frozen_manifest_source_ledger_and_seal_are_valid_offline() -> None:
    audit = audit_scientific_dataset(
        data_dir=DATA_DIR,
        source_audit_path=SOURCE_AUDIT,
        verify_seal=True,
    )
    assert audit["valid"] is True
    assert audit["provider_requests"] == 0
    assert audit["target_comparison_count"] == 24
    assert audit["task_pack_distribution"] == {
        "grounded_qa": 6,
        "instruction_generation": 6,
        "multi_turn": 6,
        "structured_tool": 6,
    }


def test_frozen_v3_protocol_and_human_readable_question_set() -> None:
    final_cases = load_target_comparison(DATA_DIR)
    assert all(case.version == "3.0" for case in final_cases)
    plan = build_execution_plan(
        execution_id="scientific-v3-frozen-offline-plan",
        data_dir=DATA_DIR,
        source_audit_path=SOURCE_AUDIT,
        protocol_path=PROTOCOL_PATH,
    )
    assert plan.formal_target_requests == 108
    assert plan.formal_judge_requests == 96
    assert plan.planned_base_requests == 208
    question_set = FINAL_QUESTION_SET_DOC.read_text(encoding="utf-8")
    assert question_set.count("### CMP-") == 24
    assert "尚未运行真实模型矩阵" in question_set


def test_every_frozen_case_has_case_level_source_provenance() -> None:
    cases = load_target_comparison(DATA_DIR)
    assert Counter(case.difficulty for case in cases) == {"D2": 12, "D3": 12}
    assert len({case.risk_cell for case in cases}) == 12
    for case in cases:
        source = case.source
        assert source.source_success_definition
        assert source.source_checker_reference
        assert source.preserved_invariants
        assert source.surface_changes
        assert source.license_use
        assert not source.original_case_id_or_method.startswith("method_transfer:")
        if source.license.casefold() == "undeclared":
            assert source.source_type.value == "method_transfer"


def test_all_registered_gold_outputs_pass_direct_checks() -> None:
    for case in load_target_comparison(DATA_DIR):
        results = run_direct_checks(case, _gold_output(case))
        assert all(result.passed for result in results), (
            case.case_id,
            [(item.criterion_id, item.reason) for item in results if not item.passed],
        )


def test_counterexamples_preserve_direct_and_semantic_authority_split() -> None:
    semantic_only = {
        "CMP-GQ-23",
        "CMP-GQ-24",
        "CMP-GQ-26",
        "CMP-MT-22",
    }
    observed_semantic_only = set()
    for case in load_target_comparison(DATA_DIR):
        results = run_direct_checks(case, _counterexample_output(case))
        if all(result.passed for result in results):
            observed_semantic_only.add(case.case_id)
            assert case.counterexample
            assert case.semantic_criteria
    assert observed_semantic_only == semantic_only


def test_ig21_gold_does_not_call_an_unverified_metric_qualified() -> None:
    case = _case("CMP-IG-21")

    assert "丙｜错误率结果〈待核〉" in case.gold_answer
    assert "达标〈待核〉" not in case.gold_answer


def test_gq22_has_unambiguous_rule_date_and_accepts_grouped_numbers() -> None:
    case = _case("CMP-GQ-22")
    assert "2026-07-08" in "\n".join(case.context)
    output = ScientificOutput(
        case_id=case.case_id,
        content=(
            "结算日在新规生效后，应付 11,820 元；可报销 11,700 元；"
            "自行承担 120 元。[O-22][V-22][P-22][B-22]"
        ),
        output_hash="grouped-numbers",
    )
    results = run_direct_checks(case, output)
    assert all(result.passed for result in results)


def test_negated_semantic_fail_phrases_are_not_direct_failures() -> None:
    refund = _case("CMP-MT-22")
    refund_output = ScientificOutput(
        case_id=refund.case_id,
        content=(
            "证据｜截图不能证明支付成功\n"
            "缺口｜缺交易号和支付网关成功状态\n"
            "动作｜因此退款尚未完成，补齐证据后再核验"
        ),
        output_hash="negated-refund",
    )
    assert all(item.passed for item in run_direct_checks(refund, refund_output))

    reviewer = _case("CMP-MT-24")
    reviewer_output = ScientificOutput(
        case_id=reviewer.case_id,
        content=(
            "陈没有审批，不能由陈负责。应选梅；最晚周三10:00开始，"
            "12:00结束，并早于15:00截止。"
        ),
        output_hash="negated-reviewer",
    )
    assert all(item.passed for item in run_direct_checks(reviewer, reviewer_output))


def test_state_dependent_cases_require_observation_rounds() -> None:
    st21 = _case("CMP-ST-21")
    st22 = _case("CMP-ST-22")
    assert st21.max_agent_turns == 2
    assert st22.max_agent_turns == 3
    assert st21.tool_outputs[0]["requires_arguments"] == {"role": "auditor"}
    assert st21.tool_outputs[1]["requires_state"] == {
        "auditor_added": True,
        "workspace_id": "$arguments.workspace_id",
    }
    assert st22.tool_outputs[1]["requires_state"] == {
        "inventory_reserved": True,
        "order_id": "$arguments.order_id",
    }
    assert st22.tool_outputs[2]["requires_state"] == {
        "shipment_created": True,
        "order_id": "$arguments.order_id",
    }
    assert all(item.passed for item in run_direct_checks(st21, _gold_output(st21)))
    assert all(item.passed for item in run_direct_checks(st22, _gold_output(st22)))

    invalid = _gold_output(st21).model_copy(
        update={
            "tool_trace": [
                {**item, "model_turn": 1} for item in _gold_output(st21).tool_trace
            ]
        }
    )
    observation = next(
        item
        for item in run_direct_checks(st21, invalid)
        if item.criterion_id == "CMP-ST-21-D03"
    )
    assert observation.passed is False


def test_simulator_rejects_wrong_role_and_cross_entity_state() -> None:
    st21 = _case("CMP-ST-21")
    viewer = ToolCall(
        name="add_workspace_member",
        arguments={
            "workspace_id": "W-7",
            "email": "audit@example.test",
            "role": "viewer",
        },
        order=0,
    )
    viewer_result, viewer_state = execute_simulated_tool_call(st21, viewer, {})
    assert viewer_result["error"] == "argument_precondition_failed"
    assert viewer_state == {}

    st22 = _case("CMP-ST-22")
    shipment = ToolCall(
        name="create_shipment",
        arguments={
            "order_id": "O-99",
            "warehouse": "WH-SZ",
            "service": "express",
        },
        order=1,
    )
    shipment_result, shipment_state = execute_simulated_tool_call(
        st22,
        shipment,
        {"inventory_reserved": True, "order_id": "O-42"},
    )
    assert shipment_result["error"] == "precondition_failed"
    assert shipment_result["unmet"]["order_id"] == {
        "expected": "O-99",
        "actual": "O-42",
    }
    assert shipment_state == {"inventory_reserved": True, "order_id": "O-42"}


def test_frozen_plan_accounts_for_real_agent_turns() -> None:
    plan = build_execution_plan(
        execution_id="scientific-v3-candidate-offline-plan",
        data_dir=DATA_DIR,
        source_audit_path=SOURCE_AUDIT,
        protocol_path=PROTOCOL_PATH,
    )
    assert plan.formal_target_requests == 108
    assert plan.formal_judge_requests == 96
    assert plan.provider_probe_requests == 4
    assert plan.planned_base_requests == 208
    target_requests = {
        (node.config_id, node.case_id): node.planned_requests
        for node in plan.nodes
        if node.stage.value == "target_generation"
    }
    assert target_requests[("model_a_prompt_v1", "CMP-ST-21")] == 2
    assert target_requests[("model_a_prompt_v1", "CMP-ST-22")] == 3

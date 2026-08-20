from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import SecretStr

from llm_eval_workbench.atomic_judge import (
    atomic_judge_instructions,
    build_atomic_judge_payload,
)
from llm_eval_workbench.schemas import GenerationParams, ToolCall
from llm_eval_workbench.scientific_checks import run_direct_checks
from llm_eval_workbench.scientific_data import load_target_comparison
from llm_eval_workbench.scientific_gateway import ScientificTargetGateway
from llm_eval_workbench.scientific_schemas import ScientificCase, ScientificOutput
from llm_eval_workbench.secrets import ResolvedModel

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "datasets" / "scientific_v2"


def _resolved_target() -> ResolvedModel:
    return ResolvedModel(
        alias="unit-target",
        role="target",
        model_name="openai/unit-target",
        api_key=SecretStr("unit-test-placeholder"),
        base_url=SecretStr("https://unit.invalid/v1"),
        api_mode="responses",
        reasoning_effort=None,
        params=GenerationParams(max_tokens=128),
    )


def _iterative_st21() -> ScientificCase:
    case = _case("CMP-ST-21")
    simulations = []
    for value in case.tool_outputs:
        item = dict(value)
        if item.get("name") == "activate_workspace":
            item["requires_state"] = {"auditor_added": True}
        simulations.append(item)
    return ScientificCase.model_validate(
        {
            **case.model_dump(mode="python"),
            "max_agent_turns": 2,
            "tool_outputs": simulations,
        }
    )


def _case(case_id: str) -> ScientificCase:
    return next(
        case for case in load_target_comparison(DATA_DIR) if case.case_id == case_id
    )


def _single_check_case(
    case_id: str,
    criterion_id: str,
    *,
    params_update: dict[str, object] | None = None,
) -> ScientificCase:
    case = _case(case_id)
    spec = next(
        item for item in case.direct_checks if item.criterion_id == criterion_id
    )
    if params_update:
        spec = spec.model_copy(update={"params": {**spec.params, **params_update}})
    return case.model_copy(update={"direct_checks": [spec]})


def _output(
    case: ScientificCase,
    *,
    content: str = "",
    tool_calls: list[ToolCall] | None = None,
    environment_state: dict[str, object] | None = None,
) -> ScientificOutput:
    return ScientificOutput(
        case_id=case.case_id,
        content=content,
        tool_calls=tool_calls or [],
        environment_state=environment_state or {},
        output_hash="reaudit-fixture",
    )


def test_atomic_judge_does_not_receive_full_reference_answers() -> None:
    case = _case("CMP-IG-26")
    payload = build_atomic_judge_payload(case, _output(case, content="fixture"))

    assert "gold_answer" not in payload["case"]
    assert "gold_tool_calls" not in payload["case"]
    assert "gold_environment_state" not in payload["case"]
    assert "counterexample" not in payload["case"]
    assert "counterexample_tool_calls" not in payload["case"]
    assert "tool_outputs" not in payload["case"]
    assert all("positive_example" not in item for item in payload["criteria"])
    assert all("negative_example" not in item for item in payload["criteria"])


def test_atomic_judge_contract_accepts_semantic_equivalence() -> None:
    instructions = atomic_judge_instructions().casefold()

    assert "equivalent paraphrases" in instructions
    assert "format, punctuation, ordering, or exact wording" in instructions
    assert "material contradiction" in instructions
    assert "direct_verifier" in instructions


def test_required_literals_can_normalize_numeric_group_separators() -> None:
    case = _single_check_case(
        "CMP-GQ-22",
        "CMP-GQ-22-D01",
        params_update={"normalizers": ["numeric_grouping"]},
    )
    output = _output(
        case,
        content="应付 11,820 元，报销 11,700 元，自行承担 120 元。",
    )

    result = run_direct_checks(case, output)[0]

    assert result.passed is True
    assert result.details["missing"] == []


def test_numeric_grouping_does_not_accept_malformed_groups() -> None:
    case = _single_check_case(
        "CMP-GQ-22",
        "CMP-GQ-22-D01",
        params_update={"normalizers": ["numeric_grouping"]},
    )
    output = _output(
        case,
        content="应付 11,82 元，报销 11,70 元，自行承担 120 元。",
    )

    result = run_direct_checks(case, output)[0]

    assert result.passed is False
    assert result.details["missing"] == ["11820", "11700"]


def test_tool_call_can_normalize_declared_prose_argument_punctuation() -> None:
    case = _single_check_case(
        "CMP-ST-26",
        "CMP-ST-26-D01",
        params_update={"argument_comparisons": {"content": "prose_equivalent"}},
    )
    output = _output(
        case,
        tool_calls=[
            ToolCall(
                name="save_project_note",
                arguments={
                    "project_id": "P-9",
                    "title": "Q3风险清单",
                    "content": "支付链路仍需复测。",
                },
                order=0,
            )
        ],
    )

    assert run_direct_checks(case, output)[0].passed is True


def test_final_state_can_normalize_declared_prose_value_punctuation() -> None:
    case = _single_check_case(
        "CMP-ST-26",
        "CMP-ST-26-D02",
        params_update={
            "value_comparisons": {"saved_content": "prose_equivalent"}
        },
    )
    output = _output(
        case,
        environment_state={
            "project_id": "P-9",
            "saved_title": "Q3风险清单",
            "saved_content": "支付链路仍需复测。",
            "file_deleted": False,
        },
    )

    assert run_direct_checks(case, output)[0].passed is True


def test_exact_comparison_remains_default_for_explicit_contracts() -> None:
    case = _single_check_case("CMP-ST-26", "CMP-ST-26-D01")
    output = _output(
        case,
        tool_calls=[
            ToolCall(
                name="save_project_note",
                arguments={
                    "project_id": "P-9",
                    "title": "Q3风险清单",
                    "content": "支付链路仍需复测。",
                },
                order=0,
            )
        ],
    )

    assert run_direct_checks(case, output)[0].passed is False


@pytest.mark.asyncio
async def test_agent_loop_observes_tool_result_before_next_action() -> None:
    case = _iterative_st21()
    requests: list[dict[str, object]] = []

    async def fake_responses(**kwargs: object) -> dict[str, object]:
        requests.append(kwargs)
        inputs = kwargs["input"]
        assert isinstance(inputs, list)
        result_count = sum(
            isinstance(item, dict) and item.get("type") == "function_call_output"
            for item in inputs
        )
        if result_count == 0:
            name = "add_workspace_member"
            arguments = {
                "workspace_id": "W-7",
                "email": "audit@example.test",
                "role": "auditor",
            }
        else:
            name = "activate_workspace"
            arguments = {"workspace_id": "W-7"}
        return {
            "status": "completed",
            "output": [
                {
                    "type": "function_call",
                    "call_id": f"call-{result_count + 1}",
                    "name": name,
                    "arguments": json.dumps(arguments),
                }
            ],
            "usage": {"input_tokens": 2, "output_tokens": 1, "total_tokens": 3},
        }

    output = await ScientificTargetGateway(
        _resolved_target(),
        responses_callable=fake_responses,
    ).generate(case=case, system_prompt="Use tools and obey their results.")

    assert len(requests) == 2
    assert output.model_turns == 2
    assert output.request_count == 2
    assert [call.name for call in output.tool_calls] == [
        "add_workspace_member",
        "activate_workspace",
    ]
    assert output.environment_state == {
        "workspace_id": "W-7",
        "auditor_email": "audit@example.test",
        "auditor_added": True,
        "workspace_status": "active",
    }
    assert [step["model_turn"] for step in output.tool_trace] == [1, 2]
    assert output.tool_trace[1]["state_before"]["auditor_added"] is True
    assert any(
        isinstance(item, dict) and item.get("type") == "function_call_output"
        for item in requests[1]["input"]  # type: ignore[index]
    )
    sequence_case = ScientificCase.model_validate(
        {
            **case.model_dump(mode="python"),
            "direct_checks": [
                {
                    "criterion_id": "CMP-ST-21-D99",
                    "check_type": "tool_observation_sequence",
                    "description": "observe each result before the dependent action",
                    "authority": "DIRECT_VERIFIER",
                    "severity": "critical",
                    "applicability": "always",
                    "params": {
                        "names": ["add_workspace_member", "activate_workspace"]
                    },
                }
            ],
        }
    )
    assert run_direct_checks(sequence_case, output)[0].passed is True


@pytest.mark.asyncio
async def test_same_turn_prewrite_cannot_satisfy_state_dependency() -> None:
    case = _iterative_st21()
    calls = 0

    async def fake_responses(**_: object) -> dict[str, object]:
        nonlocal calls
        calls += 1
        if calls == 2:
            return {"status": "completed", "output_text": "已处理工具结果。"}
        return {
            "status": "completed",
            "output": [
                {
                    "type": "function_call",
                    "call_id": "call-add",
                    "name": "add_workspace_member",
                    "arguments": json.dumps(
                        {
                            "workspace_id": "W-7",
                            "email": "audit@example.test",
                            "role": "auditor",
                        }
                    ),
                },
                {
                    "type": "function_call",
                    "call_id": "call-activate",
                    "name": "activate_workspace",
                    "arguments": json.dumps({"workspace_id": "W-7"}),
                },
            ],
        }

    output = await ScientificTargetGateway(
        _resolved_target(),
        responses_callable=fake_responses,
    ).generate(case=case, system_prompt="Use tools and obey their results.")

    assert output.environment_state.get("auditor_added") is True
    assert "workspace_status" not in output.environment_state
    assert output.tool_trace[1]["result"]["error"] == "precondition_failed"
    assert output.tool_trace[0]["model_turn"] == output.tool_trace[1]["model_turn"] == 1
    sequence_case = ScientificCase.model_validate(
        {
            **case.model_dump(mode="python"),
            "direct_checks": [
                {
                    "criterion_id": "CMP-ST-21-D99",
                    "check_type": "tool_observation_sequence",
                    "description": "observe each result before the dependent action",
                    "authority": "DIRECT_VERIFIER",
                    "severity": "critical",
                    "applicability": "always",
                    "params": {
                        "names": ["add_workspace_member", "activate_workspace"]
                    },
                }
            ],
        }
    )
    assert run_direct_checks(sequence_case, output)[0].passed is False

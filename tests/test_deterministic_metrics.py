from __future__ import annotations

from llm_eval_workbench.metrics.deterministic import (
    evaluate_check,
    run_deterministic_checks,
)
from llm_eval_workbench.schemas import (
    DeterministicCheckSpec,
    ExpectedToolCall,
    ToolCall,
)


def test_list_count_passes(sample_case, sample_output):
    results = run_deterministic_checks(sample_case, sample_output)
    assert len(results) == 1
    assert results[0].passed is True
    assert results[0].hard_failure is False


def test_required_terms_reports_missing(sample_case, sample_output):
    spec = DeterministicCheckSpec(
        check_id="required",
        type="required_terms",
        description="required facts",
        hard=True,
        params={"terms": ["不存在"], "mode": "all"},
    )
    result = evaluate_check(spec, sample_case, sample_output)
    assert result.passed is False
    assert result.hard_failure is True
    assert result.details["missing"] == ["不存在"]


def test_json_schema_and_values(sample_case, sample_output):
    output = sample_output.model_copy(update={"content": '{"name":"林岚","count":2}'})
    schema = DeterministicCheckSpec(
        check_id="schema",
        type="json_schema",
        description="schema",
        params={
            "schema": {
                "type": "object",
                "required": ["name", "count"],
                "properties": {
                    "name": {"type": "string"},
                    "count": {"type": "integer"},
                },
                "additionalProperties": False,
            }
        },
    )
    values = DeterministicCheckSpec(
        check_id="values",
        type="json_field_values",
        description="values",
        params={"expected": {"name": "林岚", "count": 2}},
    )
    assert evaluate_check(schema, sample_case, output).passed is True
    assert evaluate_check(values, sample_case, output).passed is True


def test_json_schema_rejects_markdown_explanation(sample_case, sample_output):
    output = sample_output.model_copy(update={"content": '结果如下：{"name":"林岚"}'})
    spec = DeterministicCheckSpec(
        check_id="schema",
        type="json_schema",
        description="schema",
        params={"schema": {"type": "object"}},
    )
    assert evaluate_check(spec, sample_case, output).passed is False


def test_tool_call_arguments_and_order(sample_case, sample_output):
    case = sample_case.model_copy(
        update={
            "expected_tools": [
                ExpectedToolCall(
                    name="get_weather",
                    arguments={"location": "上海", "unit": "celsius"},
                    order=0,
                )
            ]
        }
    )
    output = sample_output.model_copy(
        update={
            "tool_calls": [
                ToolCall(
                    name="get_weather",
                    arguments={"location": "上海", "unit": "celsius"},
                    order=0,
                )
            ]
        }
    )
    spec = DeterministicCheckSpec(
        check_id="tool",
        type="tool_calls",
        description="tool",
    )
    assert evaluate_check(spec, case, output).passed is True


def test_tool_call_extra_argument_fails(sample_case, sample_output):
    case = sample_case.model_copy(
        update={
            "expected_tools": [
                ExpectedToolCall(
                    name="get_weather",
                    arguments={"location": "上海"},
                    order=0,
                )
            ]
        }
    )
    output = sample_output.model_copy(
        update={
            "tool_calls": [
                ToolCall(
                    name="get_weather",
                    arguments={"location": "上海", "unexpected": True},
                    order=0,
                )
            ]
        }
    )
    spec = DeterministicCheckSpec(
        check_id="tool",
        type="tool_calls",
        description="tool",
    )
    assert evaluate_check(spec, case, output).passed is False

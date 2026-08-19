from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from llm_eval_workbench.atomic_judge import (
    ATOMIC_JUDGE_OUTPUT_CONTRACT_VERSION,
    ATOMIC_JUDGE_PROTOCOL_VERSION,
    AtomicJudge,
    AtomicJudgeParseError,
)
from llm_eval_workbench.hashing import sha256_text
from llm_eval_workbench.scientific_data import load_judge_validation
from llm_eval_workbench.scientific_schemas import (
    AtomicJudgeEnvelope,
    ScientificOutput,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "datasets" / "scientific_v1"


def _envelope(case: object, decisions: dict[str, object]) -> dict[str, object]:
    criteria = []
    for criterion in case.semantic_criteria:  # type: ignore[attr-defined]
        decision = decisions[criterion.criterion_id]
        criteria.append(
            {
                "criterion_id": criterion.criterion_id,
                "applicability": "APPLICABLE",
                "evidence_sufficiency": "SUFFICIENT",
                "decision": decision.value,
                "answer_evidence": ["fixture answer"],
                "source_evidence": [criterion.evidence[0]],
                "reason": "The fixed candidate reference determines this fixture.",
            }
        )
    return {
        "protocol_version": ATOMIC_JUDGE_PROTOCOL_VERSION,
        "criteria": criteria,
    }


@pytest.mark.asyncio
async def test_all_fourteen_judge_fixtures_use_one_blind_responses_call(
    resolved_judge: object,
) -> None:
    cases, fixtures = load_judge_validation(DATA_DIR)
    case_by_id = {item.case_id: item for item in cases}
    calls: list[dict[str, object]] = []

    for fixture in fixtures:
        case = case_by_id[fixture.case_id]
        response_text = json.dumps(
            _envelope(case, fixture.expected_criterion_decisions)
        )

        async def fake_responses(
            _response_text: str = response_text,
            **kwargs: object,
        ) -> dict[str, object]:
            calls.append(kwargs)
            return {
                "status": "completed",
                "output_text": _response_text,
                "usage": {
                    "input_tokens": 10,
                    "output_tokens": 5,
                    "total_tokens": 15,
                },
            }

        output = ScientificOutput(
            case_id=case.case_id,
            content=fixture.answer,
            tool_calls=fixture.tool_calls,
            environment_state=fixture.environment_state,
            output_hash=sha256_text(fixture.answer),
        )
        run = await AtomicJudge(
            resolved_judge,  # type: ignore[arg-type]
            responses_callable=fake_responses,
        ).evaluate(case, output)
        assert run.request_count == 1
        assert {
            item.criterion_id: item.decision
            for item in run.envelope.criteria
        } == fixture.expected_criterion_decisions

    assert len(calls) == 14
    for kwargs in calls:
        assert kwargs["store"] is False
        assert kwargs["stream"] is False
        assert kwargs["num_retries"] == 0
        assert "reasoning" not in kwargs
        assert kwargs["text_format"] is AtomicJudgeEnvelope
        assert "output_format" not in kwargs
        assert "temperature" not in kwargs
        payload_text = str(kwargs["input"])
        assert "model_a_prompt_v1" not in payload_text
        assert "model_b_prompt_v1" not in payload_text
        assert "weak_prompt_v1" not in payload_text
        assert "weak_prompt_v2" not in payload_text
        payload = json.loads(kwargs["input"][0]["content"])  # type: ignore[index]
        assert "severity" not in json.dumps(payload, ensure_ascii=False).casefold()
        assert "config_id" not in payload
        assert "model" not in payload
        assert "prompt" not in payload


@pytest.mark.asyncio
async def test_anthropic_judge_keeps_max_effort_with_native_json_schema(
    resolved_judge: object,
) -> None:
    cases, fixtures = load_judge_validation(DATA_DIR)
    fixture = fixtures[0]
    case = {item.case_id: item for item in cases}[fixture.case_id]
    base_model = resolved_judge  # type: ignore[assignment]
    anthropic_model = replace(
        base_model,
        model_name="anthropic/unit-judge",
        params=base_model.params.model_copy(  # type: ignore[attr-defined]
            update={"extra": {"reasoning_effort": "max"}}
        ),
    )
    captured: dict[str, object] = {}

    async def fake_responses(**kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        return {
            "status": "completed",
            "output_text": json.dumps(
                _envelope(case, fixture.expected_criterion_decisions)
            ),
        }

    output = ScientificOutput(
        case_id=case.case_id,
        content=fixture.answer,
        output_hash=sha256_text(fixture.answer),
    )
    run = await AtomicJudge(
        anthropic_model,
        responses_callable=fake_responses,
    ).evaluate(case, output)

    assert captured["api_key"] is None
    assert "text_format" not in captured
    assert captured["output_format"] == {
        "type": "json_schema",
        "schema": AtomicJudgeEnvelope.model_json_schema(),
    }
    assert captured["reasoning_effort"] == "max"
    assert "thinking" not in captured
    assert "output_config" not in captured
    assert run.output_contract_version == ATOMIC_JUDGE_OUTPUT_CONTRACT_VERSION
    assert run.output_transport == "anthropic-native-json-schema"


@pytest.mark.asyncio
async def test_invalid_judge_json_is_runtime_error_without_second_call(
    resolved_judge: object,
) -> None:
    cases, fixtures = load_judge_validation(DATA_DIR)
    case = {item.case_id: item for item in cases}[fixtures[0].case_id]
    calls = 0

    async def invalid_json(**_: object) -> dict[str, object]:
        nonlocal calls
        calls += 1
        return {"status": "completed", "output_text": "not json"}

    output = ScientificOutput(
        case_id=case.case_id,
        content=fixtures[0].answer,
        output_hash=sha256_text(fixtures[0].answer),
    )
    with pytest.raises(AtomicJudgeParseError, match="atomic JSON contract"):
        await AtomicJudge(
            resolved_judge,  # type: ignore[arg-type]
            responses_callable=invalid_json,
        ).evaluate(case, output)
    assert calls == 1


@pytest.mark.asyncio
async def test_invalid_judge_json_keeps_safe_diagnostic_and_raw_output(
    resolved_judge: object,
) -> None:
    cases, fixtures = load_judge_validation(DATA_DIR)
    case = {item.case_id: item for item in cases}[fixtures[0].case_id]

    async def invalid_json(**_: object) -> dict[str, object]:
        return {"status": "completed", "output_text": "not json"}

    output = ScientificOutput(
        case_id=case.case_id,
        content=fixtures[0].answer,
        output_hash=sha256_text(fixtures[0].answer),
    )
    with pytest.raises(AtomicJudgeParseError) as captured:
        await AtomicJudge(
            resolved_judge,  # type: ignore[arg-type]
            responses_callable=invalid_json,
        ).evaluate(case, output)
    error = captured.value
    assert error.raw_content == "not json"
    assert error.diagnostic["failure_stage"] == "json_or_schema_parse"
    assert error.diagnostic["content_length"] == 8
    assert len(error.diagnostic["content_hash"]) == 64
    assert error.diagnostic["json_error"] == {
        "message": "Expecting value",
        "line": 1,
        "column": 1,
        "position": 0,
    }


@pytest.mark.asyncio
async def test_contract_retry_stops_at_first_valid_judgment(
    resolved_judge: object,
) -> None:
    cases, fixtures = load_judge_validation(DATA_DIR)
    fixture = fixtures[0]
    case = {item.case_id: item for item in cases}[fixture.case_id]
    valid = json.dumps(_envelope(case, fixture.expected_criterion_decisions))
    calls: list[dict[str, object]] = []

    async def invalid_then_valid(**kwargs: object) -> dict[str, object]:
        calls.append(kwargs)
        output_text = "not json" if len(calls) == 1 else valid
        return {
            "status": "completed",
            "output_text": output_text,
            "usage": {
                "input_tokens": 10,
                "output_tokens": 5,
                "total_tokens": 15,
            },
        }

    output = ScientificOutput(
        case_id=case.case_id,
        content=fixture.answer,
        output_hash=sha256_text(fixture.answer),
    )
    run = await AtomicJudge(
        resolved_judge,  # type: ignore[arg-type]
        responses_callable=invalid_then_valid,
        contract_retry_attempts=1,
    ).evaluate(case, output)

    assert len(calls) == 2
    assert all(call["text_format"] is AtomicJudgeEnvelope for call in calls)
    assert all("output_format" not in call for call in calls)
    assert "previous response could not be parsed" not in str(
        calls[0]["instructions"]
    ).casefold()
    assert "previous response could not be parsed" in str(
        calls[1]["instructions"]
    ).casefold()
    assert run.request_count == 2
    assert run.usage.total_tokens == 30
    assert len(run.attempt_diagnostics) == 1
    assert run.attempt_diagnostics[0]["failure_stage"] == "json_or_schema_parse"


@pytest.mark.asyncio
async def test_redundant_matching_protocol_version_inside_criterion_is_ignored(
    resolved_judge: object,
) -> None:
    cases, fixtures = load_judge_validation(DATA_DIR)
    fixture = fixtures[0]
    case = {item.case_id: item for item in cases}[fixture.case_id]
    envelope = _envelope(case, fixture.expected_criterion_decisions)
    for criterion in envelope["criteria"]:  # type: ignore[index]
        criterion["protocol_version"] = ATOMIC_JUDGE_PROTOCOL_VERSION

    async def redundant_metadata(**_: object) -> dict[str, object]:
        return {"status": "completed", "output_text": json.dumps(envelope)}

    output = ScientificOutput(
        case_id=case.case_id,
        content=fixture.answer,
        output_hash=sha256_text(fixture.answer),
    )
    run = await AtomicJudge(
        resolved_judge,  # type: ignore[arg-type]
        responses_callable=redundant_metadata,
    ).evaluate(case, output)

    assert run.request_count == 1
    assert len(run.envelope.criteria) == len(case.semantic_criteria)


@pytest.mark.asyncio
async def test_judge_cannot_omit_registered_criterion(
    resolved_judge: object,
) -> None:
    cases, fixtures = load_judge_validation(DATA_DIR)
    case = next(item for item in cases if len(item.semantic_criteria) > 1)
    fixture = next(item for item in fixtures if item.case_id == case.case_id)
    envelope = _envelope(case, fixture.expected_criterion_decisions)
    envelope["criteria"] = envelope["criteria"][:-1]  # type: ignore[index]

    async def missing_criterion(**_: object) -> dict[str, object]:
        return {"status": "completed", "output_text": json.dumps(envelope)}

    output = ScientificOutput(
        case_id=case.case_id,
        content=fixture.answer,
        output_hash=sha256_text(fixture.answer),
    )
    with pytest.raises(AtomicJudgeParseError, match="criterion set"):
        await AtomicJudge(
            resolved_judge,  # type: ignore[arg-type]
            responses_callable=missing_criterion,
        ).evaluate(case, output)

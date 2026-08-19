from __future__ import annotations

from dataclasses import replace

import pytest

from llm_eval_workbench.model_gateway import (
    TargetModelGateway,
    build_responses_input,
)
from llm_eval_workbench.schemas import (
    ExpectedToolCall,
    PromptConfig,
)


@pytest.mark.asyncio
async def test_target_gateway_generates_sanitized_output(sample_case, resolved_target):
    captured = {}

    async def fake_responses(**kwargs):
        captured.update(kwargs)
        return {
            "output": [
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": "完成"}],
                }
            ],
            "usage": {
                "input_tokens": 10,
                "output_tokens": 2,
                "total_tokens": 12,
            },
            "_hidden_params": {"response_cost": 0.001},
        }

    model_with_reasoning = replace(
        resolved_target,
        reasoning_effort="max",
        params=resolved_target.params.model_copy(
            update={
                "extra": {
                    "reasoning": {"effort": "max"},
                }
            }
        ),
    )
    gateway = TargetModelGateway(
        model_with_reasoning,
        responses_callable=fake_responses,
    )
    prompt = PromptConfig(
        prompt_id="v1",
        version="1",
        system_template="系统",
        user_template="{input}",
    )
    output = await gateway.generate(
        run_id="20260730T000000Z-live1",
        case=sample_case,
        prompt=prompt,
    )
    assert output.content == "完成"
    assert output.generation_complete is True
    assert output.provider_response_status is None
    assert output.provider_incomplete_reason is None
    assert output.usage.total_tokens == 12
    assert output.usage.cost == 0.001
    assert captured["model"] == "test/model-a"
    assert captured["instructions"] == "系统"
    assert captured["input"][-1]["content"] == sample_case.input
    assert captured["store"] is False
    assert captured["stream"] is False
    assert "messages" not in captured
    assert captured["reasoning"] == {"effort": "max"}
    assert "reasoning_effort" not in captured
    serialized = output.model_dump_json()
    assert "unit-test-secret" not in serialized
    assert "example.invalid" not in serialized


@pytest.mark.asyncio
async def test_target_gateway_records_incomplete_responses_output(
    sample_case, resolved_target
):
    async def fake_responses(**kwargs):
        return {
            "status": "incomplete",
            "incomplete_details": {"reason": "max_output_tokens"},
            "output": [
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": "未完成的内容"}],
                }
            ],
        }

    gateway = TargetModelGateway(
        resolved_target,
        responses_callable=fake_responses,
    )
    prompt = PromptConfig(
        prompt_id="v1",
        version="1",
        system_template="系统",
        user_template="{input}",
    )
    output = await gateway.generate(
        run_id="20260730T000000Z-incomplete1",
        case=sample_case,
        prompt=prompt,
    )
    assert output.content == "未完成的内容"
    assert output.generation_complete is False
    assert output.provider_response_status == "incomplete"
    assert output.provider_incomplete_reason == "max_output_tokens"


@pytest.mark.asyncio
async def test_target_gateway_treats_empty_response_as_incomplete(
    sample_case, resolved_target
):
    async def fake_responses(**kwargs):
        return {"output": []}

    gateway = TargetModelGateway(
        resolved_target,
        responses_callable=fake_responses,
    )
    prompt = PromptConfig(
        prompt_id="v1",
        version="1",
        system_template="系统",
        user_template="{input}",
    )
    output = await gateway.generate(
        run_id="20260730T000000Z-empty1",
        case=sample_case,
        prompt=prompt,
    )
    assert output.generation_complete is False
    assert output.provider_response_status is None
    assert output.provider_incomplete_reason == "empty_output"


@pytest.mark.asyncio
async def test_tool_call_round_trip(sample_case, resolved_target):
    responses = [
        {
            "output": [
                {
                    "id": "fc-1",
                    "type": "function_call",
                    "call_id": "call-1",
                    "name": "get_weather",
                    "arguments": '{"location":"上海","unit":"celsius"}',
                }
            ],
            "usage": {"total_tokens": 10},
        },
        {
            "output": [
                {
                    "type": "message",
                    "content": [
                        {
                            "type": "output_text",
                            "text": "上海晴，28摄氏度。",
                        }
                    ],
                }
            ],
            "usage": {"total_tokens": 8},
        },
    ]
    captured_requests = []

    async def fake_responses(**kwargs):
        captured_requests.append(kwargs)
        return responses.pop(0)

    case = sample_case.model_copy(
        update={
            "task_type": "function_call",
            "available_tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "get_weather",
                        "parameters": {"type": "object"},
                    },
                }
            ],
            "expected_tools": [
                ExpectedToolCall(
                    name="get_weather",
                    arguments={"location": "上海", "unit": "celsius"},
                )
            ],
            "tool_outputs": [
                {
                    "name": "get_weather",
                    "output": {
                        "condition": "晴",
                        "temperature": 28,
                    },
                }
            ],
        }
    )
    gateway = TargetModelGateway(
        resolved_target,
        responses_callable=fake_responses,
    )
    prompt = PromptConfig(
        prompt_id="v1",
        version="1",
        system_template="系统",
        user_template="{input}",
    )
    output = await gateway.generate(
        run_id="20260730T000000Z-tool1",
        case=case,
        prompt=prompt,
    )
    assert output.content == "上海晴，28摄氏度。"
    assert output.tool_calls[0].name == "get_weather"
    assert output.tool_calls[0].arguments["unit"] == "celsius"
    assert output.usage.total_tokens == 18
    assert output.request_count == 2
    assert output.attempts == 2
    assert captured_requests[0]["tools"][0] == {
        "type": "function",
        "name": "get_weather",
        "description": "",
        "parameters": {"type": "object"},
        "strict": False,
    }
    assert any(
        item.get("type") == "function_call_output" and item.get("call_id") == "call-1"
        for item in captured_requests[1]["input"]
        if isinstance(item, dict)
    )


@pytest.mark.asyncio
async def test_target_gateway_owns_and_tracks_retries(sample_case, resolved_target):
    attempts = 0

    async def flaky_responses(**kwargs):
        nonlocal attempts
        attempts += 1
        assert kwargs["num_retries"] == 0
        if attempts == 1:
            raise TimeoutError("temporary timeout")
        return {
            "output": [
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": "完成"}],
                }
            ],
            "usage": {
                "input_tokens": 10,
                "output_tokens": 2,
                "total_tokens": 12,
                "cost": 0.001,
            },
        }

    gateway = TargetModelGateway(
        resolved_target,
        responses_callable=flaky_responses,
        retry_backoff_seconds=0,
    )
    prompt = PromptConfig(
        prompt_id="v1",
        version="1",
        system_template="系统",
        user_template="{input}",
    )
    output = await gateway.generate(
        run_id="20260730T000000Z-retry1",
        case=sample_case,
        prompt=prompt,
    )
    assert attempts == 2
    assert output.request_count == 2
    assert output.attempts == 2
    assert output.usage.cost == 0.001


def test_responses_input_preserves_prompt(sample_case):
    prompt = PromptConfig(
        prompt_id="v1",
        version="1",
        system_template="系统",
        user_template="{input}",
    )
    instructions, input_items = build_responses_input(sample_case, prompt)
    assert instructions == "系统"
    assert input_items[-1]["role"] == "user"
    assert input_items[-1]["content"] == sample_case.input

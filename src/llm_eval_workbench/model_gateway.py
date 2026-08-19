from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Awaitable, Callable
from typing import Any

from .hashing import sha256_text
from .provider_auth import provider_api_key, provider_auth_context_async
from .schemas import (
    EvaluationCase,
    GeneratedOutput,
    PromptConfig,
    ToolCall,
    UsageInfo,
)
from .secrets import ResolvedModel

ResponsesCallable = Callable[..., Awaitable[Any]]

_KNOWN_RESPONSE_STATUSES = {
    "cancelled",
    "completed",
    "failed",
    "in_progress",
    "incomplete",
    "queued",
}
_KNOWN_INCOMPLETE_REASONS = {
    "content_filter",
    "empty_output",
    "max_output_tokens",
    "tool_call_limit",
    "unknown",
}


class _SafeFormatDict(dict[str, str]):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def _serialize_context(case: EvaluationCase) -> str:
    return "\n\n".join(
        f"[Context {index + 1}]\n{value}" for index, value in enumerate(case.context)
    )


def render_prompt(case: EvaluationCase, prompt: PromptConfig) -> tuple[str, str]:
    values = _SafeFormatDict(
        input=case.input,
        context=_serialize_context(case),
        expected_format=case.metadata.get("expected_format", ""),
    )
    return (
        prompt.system_template.format_map(values),
        prompt.user_template.format_map(values),
    )


def build_responses_input(
    case: EvaluationCase,
    prompt: PromptConfig,
) -> tuple[str, list[dict[str, Any]]]:
    system_content, user_content = render_prompt(case, prompt)
    instruction_parts = [system_content]
    input_items: list[dict[str, Any]] = []
    for turn in case.turns:
        if turn.role == "system":
            instruction_parts.append(turn.content)
        elif turn.role in {"user", "assistant"}:
            input_items.append(
                {
                    "role": turn.role,
                    "content": turn.content,
                }
            )
        elif turn.role == "tool" and turn.tool_call_id:
            input_items.append(
                {
                    "type": "function_call_output",
                    "call_id": turn.tool_call_id,
                    "output": turn.content,
                }
            )
        else:
            raise ValueError(
                "Responses input contains an unsupported conversation turn"
            )
    if not case.turns or case.turns[-1].content != case.input:
        input_items.append({"role": "user", "content": user_content})
    return "\n\n".join(instruction_parts), input_items


def _value(value: Any, key: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(key, default)
    return getattr(value, key, default)


def _response_output_text(response: Any) -> str:
    direct = _value(response, "output_text")
    if isinstance(direct, str):
        return direct
    parts: list[str] = []
    for item in _value(response, "output", []) or []:
        if _value(item, "type") != "message":
            continue
        for content in _value(item, "content", []) or []:
            if _value(content, "type") == "output_text":
                parts.append(str(_value(content, "text", "")))
    return "".join(parts)


def _parse_tool_calls(response: Any) -> list[ToolCall]:
    parsed: list[ToolCall] = []
    for item in _value(response, "output", []) or []:
        if _value(item, "type") != "function_call":
            continue
        raw_arguments = _value(item, "arguments", "{}")
        try:
            arguments = (
                raw_arguments
                if isinstance(raw_arguments, dict)
                else json.loads(raw_arguments or "{}")
            )
        except json.JSONDecodeError:
            arguments = {"_malformed_arguments": str(raw_arguments)}
        parsed.append(
            ToolCall(
                name=str(_value(item, "name", "")),
                arguments=arguments,
                call_id=_value(item, "call_id") or _value(item, "id"),
                order=len(parsed),
            )
        )
    return parsed


def _safe_provider_marker(value: Any, allowed: set[str]) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    normalized = value.strip().lower().replace("-", "_")
    return normalized if normalized in allowed else "unknown"


def _response_completion(
    response: Any,
    *,
    content: str,
    tool_calls: list[ToolCall],
) -> tuple[bool, str | None, str | None]:
    raw_status = _value(response, "status")
    status = _safe_provider_marker(raw_status, _KNOWN_RESPONSE_STATUSES)
    details = _value(response, "incomplete_details", {}) or {}
    reason = _safe_provider_marker(
        _value(details, "reason"),
        _KNOWN_INCOMPLETE_REASONS,
    )
    has_output = bool(content.strip() or tool_calls)

    # Some LiteLLM-compatible providers omit the Responses status field.
    # Preserve compatibility only when they still return a usable output.
    if raw_status is None:
        if has_output:
            return True, None, None
        return False, None, "empty_output"
    if status == "completed" and has_output:
        return True, status, None
    if status == "completed":
        return False, status, "empty_output"
    return False, status or "unknown", reason or "unknown"


def _responses_tools(
    tools: list[dict[str, Any]] | None,
) -> list[dict[str, Any]] | None:
    if not tools:
        return None
    converted: list[dict[str, Any]] = []
    for raw_tool in tools:
        if raw_tool.get("type") == "function" and isinstance(
            raw_tool.get("function"), dict
        ):
            function = raw_tool["function"]
            converted.append(
                {
                    "type": "function",
                    "name": function.get("name", ""),
                    "description": function.get("description", ""),
                    "parameters": function.get(
                        "parameters",
                        {"type": "object", "properties": {}},
                    ),
                    # Chat tools were non-strict by default; preserve that
                    # behavior explicitly during the Responses migration.
                    "strict": bool(function.get("strict", False)),
                }
            )
        else:
            converted.append(dict(raw_tool))
    return converted


def _response_output_items(response: Any) -> list[Any]:
    items: list[Any] = []
    for item in _value(response, "output", []) or []:
        if hasattr(item, "model_dump"):
            items.append(item.model_dump(mode="json", exclude_none=True))
        else:
            items.append(item)
    return items


def _reported_cost(response: Any, usage: Any, hidden: Any) -> float | None:
    for candidate in (
        _value(usage, "cost"),
        _value(response, "cost"),
        _value(hidden, "response_cost"),
    ):
        if candidate is not None:
            try:
                return float(candidate)
            except (TypeError, ValueError):
                continue
    return None


def _usage_from_response(response: Any) -> UsageInfo:
    usage = _value(response, "usage", {}) or {}
    hidden = _value(response, "_hidden_params", {}) or {}
    return UsageInfo(
        prompt_tokens=_value(
            usage,
            "input_tokens",
            _value(usage, "prompt_tokens"),
        ),
        completion_tokens=_value(
            usage,
            "output_tokens",
            _value(usage, "completion_tokens"),
        ),
        total_tokens=_value(usage, "total_tokens"),
        cost=_reported_cost(response, usage, hidden),
    )


def _merge_usage(first: UsageInfo, second: UsageInfo) -> UsageInfo:
    def total(left: int | None, right: int | None) -> int | None:
        if left is None and right is None:
            return None
        return (left or 0) + (right or 0)

    return UsageInfo(
        prompt_tokens=total(first.prompt_tokens, second.prompt_tokens),
        completion_tokens=total(first.completion_tokens, second.completion_tokens),
        total_tokens=total(first.total_tokens, second.total_tokens),
        cost=total_cost(first.cost, second.cost),
    )


def total_cost(left: float | None, right: float | None) -> float | None:
    if left is None and right is None:
        return None
    return float(left or 0.0) + float(right or 0.0)


class TargetModelGateway:
    def __init__(
        self,
        model: ResolvedModel,
        *,
        responses_callable: ResponsesCallable | None = None,
        timeout_seconds: int = 300,
        retries: int = 1,
        retry_backoff_seconds: float = 0.25,
    ) -> None:
        if model.api_mode != "responses":
            raise ValueError("TargetModelGateway requires Responses API mode")
        self.model = model
        self._responses_callable = responses_callable
        self.timeout_seconds = timeout_seconds
        self.retries = retries
        self.retry_backoff_seconds = retry_backoff_seconds

    async def _responses(self, **kwargs: Any) -> Any:
        if self._responses_callable is None:
            import litellm

            litellm.suppress_debug_info = True
            responses_callable = litellm.aresponses
        else:
            responses_callable = self._responses_callable
        async with provider_auth_context_async(self.model):
            return await responses_callable(**kwargs)

    @staticmethod
    def _is_retryable(error: BaseException) -> bool:
        status = getattr(error, "status_code", None)
        if status is None:
            response = getattr(error, "response", None)
            status = getattr(response, "status_code", None)
        if isinstance(status, int) and 400 <= status < 500:
            return status in {408, 409, 429}
        return True

    async def _responses_with_retries(self, **kwargs: Any) -> tuple[Any, int]:
        attempts = 0
        while True:
            attempts += 1
            try:
                return await self._responses(**kwargs), attempts
            except Exception as error:
                if attempts > self.retries or not self._is_retryable(error):
                    raise
                if self.retry_backoff_seconds > 0:
                    await asyncio.sleep(
                        self.retry_backoff_seconds * (2 ** (attempts - 1))
                    )

    def _request_kwargs(
        self,
        *,
        instructions: str,
        input_items: list[Any],
        tools: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        params = self.model.params
        kwargs: dict[str, Any] = {
            "model": self.model.model_name,
            "instructions": instructions,
            "input": input_items,
            "api_key": provider_api_key(self.model),
            "temperature": params.temperature,
            "max_output_tokens": params.max_tokens,
            "store": False,
            "stream": False,
            "timeout": self.timeout_seconds,
            # Retries are owned here so the persisted attempt count is truthful.
            "num_retries": 0,
            **params.extra,
        }
        if self.model.base_url:
            kwargs["api_base"] = self.model.base_url.get_secret_value()
        if params.top_p is not None:
            kwargs["top_p"] = params.top_p
        if params.seed is not None:
            kwargs["seed"] = params.seed
        response_tools = _responses_tools(tools)
        if response_tools:
            kwargs["tools"] = response_tools
            kwargs["tool_choice"] = "auto"
        return kwargs

    async def generate(
        self,
        *,
        run_id: str,
        case: EvaluationCase,
        prompt: PromptConfig,
    ) -> GeneratedOutput:
        started = time.perf_counter()
        instructions, input_items = build_responses_input(case, prompt)
        response, request_count = await self._responses_with_retries(
            **self._request_kwargs(
                instructions=instructions,
                input_items=input_items,
                tools=case.available_tools or None,
            )
        )
        tool_calls = _parse_tool_calls(response)
        content = _response_output_text(response)
        usage = _usage_from_response(response)
        generation_complete, response_status, incomplete_reason = _response_completion(
            response,
            content=content,
            tool_calls=tool_calls,
        )

        if generation_complete and tool_calls and case.tool_outputs:
            outputs_by_name = {
                str(item.get("name")): item for item in case.tool_outputs
            }
            follow_up_input = [
                *input_items,
                *_response_output_items(response),
            ]
            for tool_call in tool_calls:
                output = outputs_by_name.get(tool_call.name, {})
                follow_up_input.append(
                    {
                        "type": "function_call_output",
                        "call_id": tool_call.call_id or f"call-{tool_call.order}",
                        "output": json.dumps(
                            output.get("output", output),
                            ensure_ascii=False,
                        ),
                    }
                )
            follow_up, follow_up_attempts = await self._responses_with_retries(
                **self._request_kwargs(
                    instructions=instructions,
                    input_items=follow_up_input,
                    tools=case.available_tools or None,
                )
            )
            content = _response_output_text(follow_up)
            follow_up_tool_calls = _parse_tool_calls(follow_up)
            generation_complete, response_status, incomplete_reason = (
                _response_completion(
                    follow_up,
                    content=content,
                    tool_calls=follow_up_tool_calls,
                )
            )
            usage = _merge_usage(usage, _usage_from_response(follow_up))
            request_count += follow_up_attempts

        latency_ms = int((time.perf_counter() - started) * 1000)
        return GeneratedOutput(
            run_id=run_id,
            case_id=case.case_id,
            model_alias=self.model.alias,
            model_name=self.model.model_name,
            prompt_id=prompt.prompt_id,
            prompt_version=prompt.version,
            content=content,
            tool_calls=tool_calls,
            usage=usage,
            latency_ms=latency_ms,
            attempts=request_count,
            request_count=request_count,
            generation_complete=generation_complete,
            provider_response_status=response_status,
            provider_incomplete_reason=incomplete_reason,
            output_hash=sha256_text(
                json.dumps(
                    {
                        "content": content,
                        "tool_calls": [
                            call.model_dump(mode="json") for call in tool_calls
                        ],
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
            ),
        )

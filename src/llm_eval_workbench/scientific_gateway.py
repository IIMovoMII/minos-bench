from __future__ import annotations

import json
import time
from collections.abc import Awaitable, Callable
from typing import Any

from jsonschema import Draft202012Validator

from .hashing import sha256_value
from .model_gateway import (
    _merge_usage,
    _parse_tool_calls,
    _response_completion,
    _response_output_text,
    _responses_tools,
    _usage_from_response,
)
from .provider_auth import provider_api_key, provider_auth_context_async
from .scientific_schemas import ScientificCase, ScientificOutput
from .secrets import ResolvedModel

ResponsesCallable = Callable[..., Awaitable[Any]]


class EmptyProviderResponse(RuntimeError):
    """A completed provider call that returned no usable answer payload."""


def build_scientific_responses_input(
    case: ScientificCase,
    *,
    system_prompt: str,
) -> tuple[str, list[dict[str, Any]]]:
    input_items: list[dict[str, Any]] = []
    for turn in case.turns:
        if turn.role == "system":
            system_prompt = f"{system_prompt}\n\n{turn.content}"
        elif turn.role in {"user", "assistant"}:
            input_items.append({"role": turn.role, "content": turn.content})
        elif turn.role == "tool" and turn.call_id:
            input_items.append(
                {
                    "type": "function_call_output",
                    "call_id": turn.call_id,
                    "output": turn.content,
                }
            )
        else:
            raise ValueError("unsupported Responses conversation turn")

    if not case.turns or case.turns[-1].content != case.input:
        context = "\n\n".join(case.context)
        user_content = (
            f"可用资料：\n{context}\n\n用户任务：\n{case.input}"
            if context
            else case.input
        )
        input_items.append({"role": "user", "content": user_content})
    return system_prompt, input_items


def _resolve_simulation_value(value: Any, arguments: dict[str, Any]) -> Any:
    if isinstance(value, str) and value.startswith("$arguments."):
        return arguments.get(value.removeprefix("$arguments."))
    if isinstance(value, dict):
        return {
            key: _resolve_simulation_value(item, arguments)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_resolve_simulation_value(item, arguments) for item in value]
    return value


def _tool_definition(case: ScientificCase, name: str) -> dict[str, Any] | None:
    return next(
        (item for item in case.available_tools if str(item.get("name")) == name),
        None,
    )


def execute_simulated_tool_call(
    case: ScientificCase,
    call: Any,
    state: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Execute one local synthetic tool without touching an external system."""

    definition = _tool_definition(case, call.name)
    if definition is None:
        return (
            {
                "ok": False,
                "error": "unknown_tool",
                "tool": call.name,
            },
            dict(state),
        )

    schema = definition.get("parameters", {})
    validation_errors = sorted(
        Draft202012Validator(schema).iter_errors(call.arguments),
        key=lambda item: list(item.absolute_path),
    )
    if validation_errors:
        return (
            {
                "ok": False,
                "error": "invalid_arguments",
                "details": [item.message for item in validation_errors],
            },
            dict(state),
        )

    simulation = next(
        (
            item
            for item in case.tool_outputs
            if item.get("simulation") is True
            and str(item.get("name")) == call.name
        ),
        None,
    )
    if simulation is None:
        return (
            {
                "ok": False,
                "error": "simulation_unavailable",
                "tool": call.name,
            },
            dict(state),
        )

    required_arguments = simulation.get("requires_arguments", {})
    unmet_arguments = {
        key: {"expected": expected, "actual": call.arguments.get(key)}
        for key, expected in required_arguments.items()
        if call.arguments.get(key) != expected
    }
    if unmet_arguments:
        return (
            {
                "ok": False,
                "error": "argument_precondition_failed",
                "unmet": unmet_arguments,
            },
            dict(state),
        )

    required_state = _resolve_simulation_value(
        simulation.get("requires_state", {}),
        call.arguments,
    )
    unmet = {
        key: {"expected": expected, "actual": state.get(key)}
        for key, expected in required_state.items()
        if state.get(key) != expected
    }
    if unmet:
        return (
            {
                "ok": False,
                "error": "precondition_failed",
                "unmet": unmet,
            },
            dict(state),
        )

    updated = dict(state)
    patch = _resolve_simulation_value(
        simulation.get("state_patch", {}),
        call.arguments,
    )
    updated.update(patch)
    declared_output = simulation.get("output")
    result = (
        _resolve_simulation_value(declared_output, call.arguments)
        if declared_output is not None
        else {"ok": True, "state_patch": patch}
    )
    if not isinstance(result, dict):
        result = {"ok": True, "value": result}
    elif "ok" not in result:
        result = {"ok": True, **result}
    return result, updated


def simulate_environment_state(
    case: ScientificCase,
    tool_calls: list[Any],
) -> dict[str, Any]:
    state: dict[str, Any] = {}
    for call in sorted(tool_calls, key=lambda item: item.order):
        _, state = execute_simulated_tool_call(case, call, state)
    return state


class ScientificTargetGateway:
    def __init__(
        self,
        model: ResolvedModel,
        *,
        responses_callable: ResponsesCallable | None = None,
        timeout_seconds: int = 300,
    ) -> None:
        if model.api_mode != "responses":
            raise ValueError("ScientificTargetGateway requires Responses API mode")
        self.model = model
        self._responses_callable = responses_callable
        self.timeout_seconds = timeout_seconds

    async def _responses(self, **kwargs: Any) -> Any:
        if self._responses_callable is None:
            import litellm

            litellm.suppress_debug_info = True
            callable_ = litellm.aresponses
        else:
            callable_ = self._responses_callable
        async with provider_auth_context_async(self.model):
            return await callable_(**kwargs)

    def request_kwargs(
        self,
        *,
        instructions: str,
        input_items: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        max_output_tokens: int | None = None,
    ) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "model": self.model.model_name,
            "instructions": instructions,
            "input": input_items,
            "api_key": provider_api_key(self.model),
            "max_output_tokens": max_output_tokens or self.model.params.max_tokens,
            "store": False,
            "stream": False,
            "timeout": self.timeout_seconds,
            "num_retries": 0,
            **self.model.params.extra,
        }
        if self.model.base_url:
            kwargs["api_base"] = self.model.base_url.get_secret_value()
        responses_tools = _responses_tools(tools)
        if responses_tools:
            kwargs["tools"] = responses_tools
            kwargs["tool_choice"] = "auto"
        return kwargs

    async def raw_request(self, **kwargs: Any) -> Any:
        return await self._responses(**kwargs)

    async def generate(
        self,
        *,
        case: ScientificCase,
        system_prompt: str,
    ) -> ScientificOutput:
        instructions, input_items = build_scientific_responses_input(
            case,
            system_prompt=system_prompt,
        )
        started = time.perf_counter()
        response = None
        content_parts: list[str] = []
        tool_calls: list[Any] = []
        tool_trace: list[dict[str, Any]] = []
        environment_state: dict[str, Any] = {}
        usage = None
        provider_status: str | None = None
        incomplete_reason: str | None = None
        request_count = 0
        model_turns = 0
        for model_turn in range(case.max_agent_turns):
            model_turns += 1
            round_content = ""
            round_calls: list[Any] = []
            # A completed empty payload is a transport failure. Retry only that
            # model turn once; never retry a non-empty answer for quality.
            for attempt in range(2):
                request_count += 1
                response = await self._responses(
                    **self.request_kwargs(
                        instructions=instructions,
                        input_items=input_items,
                        tools=case.available_tools or None,
                    )
                )
                round_content = _response_output_text(response)
                round_calls = _parse_tool_calls(response)
                complete, provider_status, incomplete_reason = _response_completion(
                    response,
                    content=round_content,
                    tool_calls=round_calls,
                )
                if complete and (round_content.strip() or round_calls):
                    break
                if attempt == 1:
                    if not complete:
                        raise RuntimeError(
                            "IncompleteTargetResponse "
                            f"(status={provider_status or 'missing'}, "
                            f"reason={incomplete_reason or 'unknown'})"
                        )
                    raise EmptyProviderResponse(
                        "target response contained no text or tool call"
                    )

            round_usage = _usage_from_response(response)
            usage = round_usage if usage is None else _merge_usage(usage, round_usage)
            if round_content.strip():
                content_parts.append(round_content)
            if not round_calls:
                break

            state_before_round = dict(environment_state)
            normalized_calls = []
            results = []
            for round_order, call in enumerate(round_calls):
                global_order = len(tool_calls)
                normalized = call.model_copy(
                    update={
                        "call_id": call.call_id
                        or (
                            f"{case.case_id}-turn-{model_turn + 1}"
                            f"-call-{round_order + 1}"
                        ),
                        "order": global_order,
                    }
                )
                result, updated = execute_simulated_tool_call(
                    case,
                    normalized,
                    state_before_round,
                )
                if result.get("ok") is True:
                    environment_state.update(updated)
                normalized_calls.append(normalized)
                results.append((normalized, result))
                tool_trace.append(
                    {
                        "model_turn": model_turn + 1,
                        "call": normalized.model_dump(mode="json"),
                        "result": result,
                        "state_before": state_before_round,
                        "state_after": dict(environment_state),
                    }
                )
            tool_calls.extend(normalized_calls)

            if model_turn + 1 >= case.max_agent_turns:
                break
            prior_items = response_items(response)
            if prior_items:
                normalized_iterator = iter(normalized_calls)
                normalized_prior_items = []
                for item in prior_items:
                    if item.get("type") == "function_call":
                        normalized_call = next(normalized_iterator, None)
                        if normalized_call is not None:
                            item = {
                                **item,
                                "call_id": normalized_call.call_id,
                                "name": normalized_call.name,
                                "arguments": json.dumps(
                                    normalized_call.arguments,
                                    ensure_ascii=False,
                                ),
                            }
                    normalized_prior_items.append(item)
                prior_items = normalized_prior_items
            if not prior_items:
                prior_items = [
                    {
                        "type": "function_call",
                        "call_id": call.call_id,
                        "name": call.name,
                        "arguments": json.dumps(call.arguments, ensure_ascii=False),
                    }
                    for call in normalized_calls
                ]
            input_items = [*input_items, *prior_items]
            input_items.extend(
                tool_output_item(str(call.call_id), result)
                for call, result in results
            )
        latency_ms = int((time.perf_counter() - started) * 1000)
        content = "\n".join(content_parts)
        return ScientificOutput(
            case_id=case.case_id,
            content=content,
            tool_calls=tool_calls,
            environment_state=environment_state,
            tool_trace=tool_trace,
            model_turns=model_turns,
            usage=usage or _usage_from_response(response),
            latency_ms=latency_ms,
            request_count=request_count,
            provider_status=provider_status,
            output_hash=sha256_value(
                {
                    "content": content,
                    "tool_calls": [call.model_dump(mode="json") for call in tool_calls],
                    "environment_state": environment_state,
                }
            ),
        )


def response_items(response: Any) -> list[dict[str, Any]]:
    values: list[dict[str, Any]] = []
    for item in getattr(response, "output", []) or []:
        if hasattr(item, "model_dump"):
            values.append(item.model_dump(mode="json", exclude_none=True))
        elif isinstance(item, dict):
            values.append(item)
    return values


def tool_output_item(call_id: str, value: Any) -> dict[str, Any]:
    return {
        "type": "function_call_output",
        "call_id": call_id,
        "output": json.dumps(value, ensure_ascii=False),
    }

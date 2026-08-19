from __future__ import annotations

import json
import time
from collections.abc import Awaitable, Callable
from typing import Any

from .hashing import sha256_value
from .model_gateway import (
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


def simulate_environment_state(
    case: ScientificCase,
    tool_calls: list[Any],
) -> dict[str, Any]:
    state: dict[str, Any] = {}
    simulations = {
        str(item.get("name")): item
        for item in case.tool_outputs
        if item.get("simulation") is True
    }
    for call in tool_calls:
        simulation = simulations.get(call.name)
        if simulation is None:
            continue
        patch = simulation.get("state_patch", {})
        for key, value in patch.items():
            if isinstance(value, str) and value.startswith("$arguments."):
                state[key] = call.arguments.get(value.removeprefix("$arguments."))
            else:
                state[key] = value
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
        content = ""
        tool_calls: list[Any] = []
        provider_status: str | None = None
        incomplete_reason: str | None = None
        request_count = 0
        # A provider can return HTTP 200 with an empty or incomplete payload. It
        # is a transport/runtime failure, not a content-quality result, so allow
        # exactly one diagnostic retry here. A non-empty answer exits this loop,
        # even if its content is later judged wrong.
        for attempt in range(2):
            request_count += 1
            response = await self._responses(
                **self.request_kwargs(
                    instructions=instructions,
                    input_items=input_items,
                    tools=case.available_tools or None,
                )
            )
            content = _response_output_text(response)
            tool_calls = _parse_tool_calls(response)
            complete, provider_status, incomplete_reason = _response_completion(
                response,
                content=content,
                tool_calls=tool_calls,
            )
            if complete and (content.strip() or tool_calls):
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
        latency_ms = int((time.perf_counter() - started) * 1000)
        environment_state = simulate_environment_state(case, tool_calls)
        return ScientificOutput(
            case_id=case.case_id,
            content=content,
            tool_calls=tool_calls,
            environment_state=environment_state,
            usage=_usage_from_response(response),
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

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .atomic_judge import AtomicJudge, AtomicJudgeParseError
from .hashing import sha256_value
from .model_gateway import (
    _parse_tool_calls,
    _response_completion,
    _response_output_text,
    _usage_from_response,
)
from .schemas import GenerationParams, ModelConfig, ToolCall
from .scientific_data import (
    audit_scientific_dataset,
    load_judge_validation,
    load_target_comparison,
)
from .scientific_evaluator import evaluate_scientific_case, runtime_result
from .scientific_gateway import (
    ScientificTargetGateway,
    response_items,
    tool_output_item,
)
from .scientific_plan import load_and_verify_plan, load_scientific_protocol
from .scientific_report import create_blind_review_package, write_machine_reports
from .scientific_schemas import (
    ExecutionNode,
    ExecutionStage,
    JudgeValidationResponse,
    ScientificCase,
    ScientificExecutionPlan,
    ScientificOutput,
)
from .scientific_store import ScientificExecutionStore
from .secrets import ResolvedModel, resolve_model

RawResponsesCallable = Callable[..., Awaitable[Any]]


class ExecutionStopped(RuntimeError):
    def __init__(self, reason: str, safe_error: dict[str, Any] | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.safe_error = safe_error or {}


class ProviderCallError(RuntimeError):
    def __init__(self, safe_error: dict[str, Any]) -> None:
        super().__init__(str(safe_error.get("classification", "provider_runtime")))
        self.safe_error = safe_error


def _http_status(error: BaseException) -> int | None:
    status = getattr(error, "status_code", None)
    if status is None:
        response = getattr(error, "response", None)
        status = getattr(response, "status_code", None)
    return status if isinstance(status, int) else None


def _provider_error_diagnostic_text(error: BaseException) -> str:
    """Collect provider diagnostics for local classification only.

    The returned text must never be persisted or included in the public safe-error
    payload because relay exceptions can echo model identifiers, URLs, or secrets.
    """
    parts: list[str] = []
    for attribute in ("message", "body"):
        value = getattr(error, attribute, None)
        if value is not None:
            parts.append(str(value))
    response = getattr(error, "response", None)
    if response is not None:
        for attribute in ("text", "content"):
            value = getattr(response, attribute, None)
            if isinstance(value, bytes):
                value = value.decode("utf-8", errors="replace")
            if value is not None:
                parts.append(str(value))
    return "\n".join(parts).casefold()


def _is_deterministic_route_unavailable(error: BaseException) -> bool:
    diagnostic = " ".join(_provider_error_diagnostic_text(error).split())
    markers = (
        "no available channel",
        "no available channels",
        "channel is unavailable",
        "channel not available",
        "model is unavailable",
        "model unavailable",
        "model not available",
    )
    return any(marker in diagnostic for marker in markers)


def classify_provider_error(error: BaseException) -> dict[str, Any]:
    error_type = type(error).__name__
    status = _http_status(error)
    normalized = error_type.casefold()
    hard_markers = (
        "authentication",
        "permissiondenied",
        "unsupportedparam",
        "badrequest",
        "notfound",
    )
    transient_markers = (
        "timeout",
        "ratelimit",
        "apiconnection",
        "connection",
        "serviceunavailable",
        "emptyproviderresponse",
    )
    error_code: str | None = None
    if status == 503 and _is_deterministic_route_unavailable(error):
        # Some relays encode a deterministic model/channel routing failure as
        # HTTP 503. Retrying it forever cannot repair a missing route and can
        # create an unbounded paid/request log. Do not persist the raw body.
        classification = "hard_provider_route"
        error_code = "no_available_model_channel"
    elif status in {400, 401, 403, 404, 405, 422} or any(
        marker in normalized for marker in hard_markers
    ):
        classification = "hard_provider_contract"
    elif (
        status in {408, 409, 425, 429}
        or (status is not None and status >= 500)
        or any(marker in normalized for marker in transient_markers)
    ):
        classification = "transient_provider"
    else:
        classification = "provider_runtime"
    safe_error = {
        "error_type": error_type,
        "classification": classification,
        "http_status": status,
    }
    if error_code is not None:
        safe_error["error_code"] = error_code
    return safe_error


class RequestGuard:
    def __init__(
        self,
        *,
        store: ScientificExecutionStore,
        state: dict[str, Any],
        plan: ScientificExecutionPlan,
        raw_callable: RawResponsesCallable | None,
        allow_runtime_recovery: bool = False,
        runtime_retry_attempts: int = 1,
    ) -> None:
        self.store = store
        self.state = state
        self.plan = plan
        self.raw_callable = raw_callable
        self.allow_runtime_recovery = allow_runtime_recovery
        self.runtime_retry_attempts = runtime_retry_attempts

    async def _raw(self, **kwargs: Any) -> Any:
        if self.raw_callable is not None:
            return await self.raw_callable(**kwargs)
        import litellm

        litellm.suppress_debug_info = True
        return await litellm.aresponses(**kwargs)

    async def call(self, *, stage: str, **kwargs: Any) -> Any:
        async def once() -> Any:
            used = int(self.state.get("requests_used", 0))
            if (
                self.plan.absolute_request_ceiling is not None
                and used >= self.plan.absolute_request_ceiling
            ):
                raise ExecutionStopped("absolute_request_ceiling_exceeded")
            self.state["requests_used"] = used + 1
            self.state["updated_at"] = datetime.now(UTC).isoformat()
            try:
                self.store.write_state(self.state)
            except Exception as error:
                # Persistence happens before the provider call. A local file lock
                # must not be counted or retried as an upstream API failure.
                self.state["requests_used"] = used
                raise ExecutionStopped(
                    "local_state_persistence_error",
                    {
                        "error_type": type(error).__name__,
                        "classification": "local_persistence",
                        "http_status": None,
                    },
                ) from error
            return await self._raw(**kwargs)

        recovery_attempts = 0
        recoverable_stages = {
            "provider_probe",
            "formal_target_generation",
            "judge_validation",
            "formal_judge_evaluation",
        }
        while True:
            try:
                return await once()
            except ExecutionStopped:
                raise
            except Exception as error:
                safe = classify_provider_error(error)
                if safe["classification"] == "hard_provider_route":
                    # A relay that explicitly has no route for the configured
                    # model cannot recover through immediate retries. Stop the
                    # execution before one outage fans out across the matrix.
                    raise ExecutionStopped(
                        "provider_route_unavailable", safe
                    ) from None
                stage_is_recoverable = (
                    stage in recoverable_stages or stage.startswith("technical_")
                )
                recovery_allowed = (
                    self.allow_runtime_recovery
                    and stage_is_recoverable
                    and recovery_attempts < self.runtime_retry_attempts
                )
                if recovery_allowed:
                    recovery_attempts += 1
                    self.store.append_event(
                        {
                            "event": "runtime_recovery_retry_scheduled",
                            "stage": stage,
                            "retry_number": recovery_attempts,
                            "safe_error": safe,
                            "at": datetime.now(UTC).isoformat(),
                        }
                    )
                    continue
                if self.allow_runtime_recovery and stage_is_recoverable:
                    # The current logical node already received its one recovery
                    # attempt. Persist a runtime error so a derived recovery can
                    # retry only this missing node without replaying valid answers.
                    raise ProviderCallError(safe) from None
                if safe["classification"] == "hard_provider_contract":
                    # A provider can reject one otherwise valid formal case because
                    # of relay/content-specific validation. Preserve that case as a
                    # runtime error and let the existing consecutive-error circuit
                    # breaker distinguish an isolated rejection from a broken
                    # provider contract. Probes and judge calls remain fail-fast.
                    if stage == "formal_target_generation":
                        raise ProviderCallError(safe) from None
                    raise ExecutionStopped("hard_provider_error", safe) from None
                if safe["classification"] != "transient_provider":
                    raise ProviderCallError(safe) from None
                used_retries = int(self.state.get("transient_retries_used", 0))
                if (
                    self.plan.transient_retry_cap is not None
                    and used_retries >= self.plan.transient_retry_cap
                ):
                    raise ExecutionStopped(
                        "transient_retry_cap_exhausted", safe
                    ) from None
                used_retries += 1
                self.state["transient_retries_used"] = used_retries
                self.state["updated_at"] = datetime.now(UTC).isoformat()
                self.store.write_state(self.state)
                delay_seconds = min(2 ** min(used_retries - 1, 4), 15)
                self.store.append_event(
                    {
                        "event": "transient_retry_scheduled",
                        "stage": stage,
                        "retry_number": used_retries,
                        "delay_seconds": delay_seconds,
                        "safe_error": safe,
                        "at": datetime.now(UTC).isoformat(),
                    }
                )
                await asyncio.sleep(delay_seconds)


def _model_config(
    *,
    slot_id: str,
    slot: dict[str, Any],
    max_tokens: int,
) -> ModelConfig:
    return ModelConfig(
        alias=slot_id,
        role=slot["role"],
        model_env=slot["model_env"],
        api_key_env=slot["api_key_env"],
        base_url_env=slot.get("base_url_env"),
        api_mode_env=slot.get("api_mode_env"),
        reasoning_effort_env=slot.get("reasoning_effort_env"),
        params=GenerationParams(temperature=0.0, max_tokens=max_tokens),
    )


def resolve_runtime_models(protocol: dict[str, Any]) -> dict[str, ResolvedModel]:
    values: dict[str, ResolvedModel] = {}
    target_max = int(protocol["target_generation"]["max_output_tokens"])
    judge_max = int(protocol["judge"]["max_output_tokens"])
    for slot_id, slot in protocol["runtime_slots"].items():
        maximum = judge_max if slot_id == "judge" else target_max
        values[slot_id] = resolve_model(
            _model_config(slot_id=slot_id, slot=slot, max_tokens=maximum)
        )
    return values


def _prompt_map(protocol: dict[str, Any]) -> dict[str, str]:
    return {item["prompt_id"]: item["system_prompt"] for item in protocol["prompts"]}


def _config_map(protocol: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {item["config_id"]: item for item in protocol["configs"]}


def _safe_runtime_error(error: BaseException) -> dict[str, Any]:
    if isinstance(error, ProviderCallError):
        return error.safe_error
    if isinstance(error, AtomicJudgeParseError):
        return {
            "error_type": type(error).__name__,
            "classification": "judge_contract_runtime",
            "http_status": None,
            "diagnostic": error.diagnostic,
        }
    return {
        "error_type": type(error).__name__,
        "classification": "local_runtime",
        "http_status": None,
    }


class ScientificExecutor:
    def __init__(
        self,
        *,
        project_root: str | Path,
        data_dir: str | Path,
        source_audit_path: str | Path,
        protocol_path: str | Path,
        execution_root: str | Path,
        execution_id: str,
        raw_responses_callable: RawResponsesCallable | None = None,
        allow_runtime_recovery: bool = False,
        runtime_retry_attempts: int = 1,
        judge_contract_retry_attempts: int = 0,
    ) -> None:
        self.project_root = Path(project_root).resolve()
        self.data_dir = Path(data_dir).resolve()
        self.source_audit_path = Path(source_audit_path).resolve()
        self.protocol_path = Path(protocol_path).resolve()
        self.store = ScientificExecutionStore(execution_root, execution_id)
        self.plan = load_and_verify_plan(
            plan_path=self.store.plan_path,
            data_dir=self.data_dir,
            protocol_path=self.protocol_path,
        )
        self.protocol = load_scientific_protocol(self.protocol_path)
        self.raw_responses_callable = raw_responses_callable
        self.allow_runtime_recovery = allow_runtime_recovery
        if runtime_retry_attempts < 0:
            raise ValueError("runtime_retry_attempts must not be negative")
        self.runtime_retry_attempts = runtime_retry_attempts
        self.judge_contract_retry_attempts = judge_contract_retry_attempts
        self.cases = {
            item.case_id: item for item in load_target_comparison(self.data_dir)
        }
        validation_cases, validation_responses = load_judge_validation(self.data_dir)
        self.validation_cases = {item.case_id: item for item in validation_cases}
        self.validation_responses = {
            item.response_id: item for item in validation_responses
        }
        self.models: dict[str, ResolvedModel] = {}
        self.prompts = _prompt_map(self.protocol)
        self.configs = _config_map(self.protocol)

    def _initial_state(self) -> dict[str, Any]:
        now = datetime.now(UTC).isoformat()
        return {
            "execution_id": self.plan.execution_id,
            "status": "running",
            "current_node": None,
            "inflight_node": None,
            "requests_used": 0,
            "transient_retries_used": 0,
            "consecutive_runtime_errors": 0,
            "completed_nodes": 0,
            "stop_reason": None,
            "safe_error": None,
            "started_at": now,
            "updated_at": now,
            "finished_at": None,
        }

    def _load_or_start_state(self) -> dict[str, Any]:
        state = self.store.load_state()
        if state is None:
            state = self._initial_state()
            self.store.write_state(state)
            return state
        if state.get("status") == "completed":
            return state
        stopped = str(state.get("status", "")).startswith("stopped")
        interrupted = state.get("status") == "interrupted"
        previous_stop_reason = str(state.get("stop_reason") or "")
        resumable_provider_stops = {
            "hard_provider_error",
            "provider_route_unavailable",
            "runtime_profile_unavailable_or_invalid",
        }
        if stopped and not (
            self.allow_runtime_recovery
            and previous_stop_reason in resumable_provider_stops
        ):
            raise ExecutionStopped("terminal_execution_cannot_resume")
        inflight = state.get("inflight_node")
        ambiguous_provider_probe = bool(
            interrupted
            and self.allow_runtime_recovery
            and inflight
            and str(inflight).startswith("provider-probe-")
            and not self.store.has_node(str(inflight))
        )
        if inflight and not self.store.has_node(str(inflight)):
            if not (
                (stopped and previous_stop_reason in resumable_provider_stops)
                or ambiguous_provider_probe
            ):
                raise ExecutionStopped("ambiguous_inflight_node_requires_new_execution")
        if ambiguous_provider_probe:
            self.store.append_event(
                {
                    "event": "ambiguous_provider_probe_retried",
                    "node_id": str(inflight),
                    "previous_stop_reason": previous_stop_reason,
                    "at": datetime.now(UTC).isoformat(),
                }
            )
        elif stopped:
            self.store.append_event(
                {
                    "event": "execution_resumed_after_provider_failure",
                    "previous_stop_reason": previous_stop_reason,
                    "at": datetime.now(UTC).isoformat(),
                }
            )
        state.update(
            {
                "status": "running",
                "current_node": None,
                "inflight_node": None,
                "stop_reason": None,
                "safe_error": None,
                "finished_at": None,
                "updated_at": datetime.now(UTC).isoformat(),
            }
        )
        self.store.write_state(state)
        return state

    def _set_current(self, state: dict[str, Any], node: ExecutionNode) -> None:
        state["current_node"] = node.node_id
        state["updated_at"] = datetime.now(UTC).isoformat()
        self.store.write_state(state)

    def _begin_provider_node(self, state: dict[str, Any], node: ExecutionNode) -> None:
        state["inflight_node"] = node.node_id
        self.store.write_state(state)

    def _finish_node(
        self,
        state: dict[str, Any],
        node: ExecutionNode,
        artifact: dict[str, Any],
    ) -> None:
        self.store.write_node_once(node.node_id, artifact)
        state["inflight_node"] = None
        state["completed_nodes"] = len(self.store.all_node_artifacts())
        if (
            artifact.get("status") == "runtime_error"
            and node.stage == ExecutionStage.TARGET_GENERATION
        ):
            state["consecutive_runtime_errors"] = (
                int(state.get("consecutive_runtime_errors", 0)) + 1
            )
        else:
            state["consecutive_runtime_errors"] = 0
        state["updated_at"] = datetime.now(UTC).isoformat()
        self.store.write_state(state)
        if (
            int(state["consecutive_runtime_errors"])
            >= self.plan.max_consecutive_runtime_errors
        ):
            raise ExecutionStopped("consecutive_runtime_error_circuit_breaker")

    def _assert_dependencies(self, node: ExecutionNode) -> None:
        missing = [
            value for value in node.dependencies if not self.store.has_node(value)
        ]
        if missing:
            raise RuntimeError(f"node dependencies missing: {node.node_id}")

    async def _probe_target(
        self,
        guard: RequestGuard,
        model: ResolvedModel,
    ) -> dict[str, Any]:
        gateway = ScientificTargetGateway(
            model,
            responses_callable=lambda **kwargs: guard.call(
                stage="provider_probe",
                **kwargs,
            ),
        )
        kwargs = gateway.request_kwargs(
            instructions="Reply with any non-empty text.",
            input_items=[{"role": "user", "content": "ping"}],
            max_output_tokens=32,
        )
        # A health probe verifies connectivity only. Reasoning and Judge output
        # quality are separate concerns and must not inflate this request.
        kwargs.pop("reasoning", None)
        kwargs.pop("reasoning_effort", None)
        kwargs.pop("thinking", None)
        kwargs.pop("output_config", None)
        response = await gateway.raw_request(**kwargs)
        content = _response_output_text(response)
        calls = _parse_tool_calls(response)
        complete, provider_status, reason = _response_completion(
            response,
            content=content,
            tool_calls=calls,
        )
        if not complete or not (content.strip() or calls):
            raise RuntimeError(
                "ProviderProbeIncomplete:"
                f"{provider_status or 'missing'}:{reason or 'unknown'}"
            )
        return {
            "response_hash": sha256_value(
                {
                    "content": content,
                    "tool_calls": [item.model_dump(mode="json") for item in calls],
                }
            ),
            "provider_status": provider_status,
            "usage": _usage_from_response(response).model_dump(mode="json"),
        }

    async def _technical_probe(
        self,
        guard: RequestGuard,
        probe_id: str,
    ) -> dict[str, Any]:
        gateway = ScientificTargetGateway(
            self.models["model_a"],
            responses_callable=lambda **kwargs: guard.call(
                stage=f"technical_{probe_id}",
                **kwargs,
            ),
        )
        warnings: list[str] = []
        if probe_id == "plain":
            response = await gateway.raw_request(
                **gateway.request_kwargs(
                    instructions="Answer the user request.",
                    input_items=[{"role": "user", "content": "Reply with OK."}],
                    max_output_tokens=32,
                )
            )
        elif probe_id == "grounded":
            response = await gateway.raw_request(
                **gateway.request_kwargs(
                    instructions="Use only the supplied source.",
                    input_items=[
                        {
                            "role": "user",
                            "content": (
                                "Source: [S1] status is green. "
                                "Question: What is the status?"
                            ),
                        }
                    ],
                    max_output_tokens=64,
                )
            )
        elif probe_id == "multi-turn":
            response = await gateway.raw_request(
                **gateway.request_kwargs(
                    instructions="Respect the latest conversation state.",
                    input_items=[
                        {"role": "user", "content": "The value is old."},
                        {"role": "assistant", "content": "Recorded."},
                        {
                            "role": "user",
                            "content": "Change it to new. Return the value.",
                        },
                    ],
                    max_output_tokens=64,
                )
            )
        elif probe_id == "json":
            response = await gateway.raw_request(
                **gateway.request_kwargs(
                    instructions="Return only valid JSON.",
                    input_items=[{"role": "user", "content": 'Return {"ok": true}.'}],
                    max_output_tokens=64,
                )
            )
        elif probe_id == "tool-roundtrip":
            echo_tool = {
                "type": "function",
                "name": "echo_value",
                "description": "Return the provided value",
                "parameters": {
                    "type": "object",
                    "properties": {"value": {"type": "string"}},
                    "required": ["value"],
                    "additionalProperties": False,
                },
            }
            input_items = [{"role": "user", "content": "Use echo_value with value OK."}]
            first = await gateway.raw_request(
                **gateway.request_kwargs(
                    instructions="Use the provided tool when requested.",
                    input_items=input_items,
                    tools=[echo_tool],
                    max_output_tokens=128,
                )
            )
            calls = _parse_tool_calls(first)
            if calls:
                call = calls[0]
                first_items = response_items(first)
            else:
                warnings.append("target_did_not_emit_tool_call")
                call = ToolCall(
                    name="echo_value",
                    arguments={"value": "OK"},
                    call_id="synthetic-probe-call",
                )
                first_items = [
                    {
                        "type": "function_call",
                        "call_id": call.call_id,
                        "name": call.name,
                        "arguments": json.dumps(call.arguments),
                    }
                ]
            response = await gateway.raw_request(
                **gateway.request_kwargs(
                    instructions="Use the tool result and reply with its value.",
                    input_items=[
                        *input_items,
                        *first_items,
                        tool_output_item(
                            call.call_id or "synthetic-probe-call", {"value": "OK"}
                        ),
                    ],
                    max_output_tokens=64,
                )
            )
        else:
            raise ValueError(f"unknown technical probe: {probe_id}")
        content = _response_output_text(response)
        calls = _parse_tool_calls(response)
        complete, status, reason = _response_completion(
            response,
            content=content,
            tool_calls=calls,
        )
        if not complete:
            raise RuntimeError(
                f"TechnicalProbeIncomplete:{status or 'missing'}:{reason or 'unknown'}"
            )
        if probe_id == "json":
            try:
                json.loads(content)
            except json.JSONDecodeError:
                warnings.append("target_json_quality_warning")
        return {
            "probe_id": probe_id,
            "provider_status": status,
            "response_hash": sha256_value(
                {
                    "content": content,
                    "tool_calls": [item.model_dump(mode="json") for item in calls],
                }
            ),
            "warnings": warnings,
            "usage": _usage_from_response(response).model_dump(mode="json"),
        }

    async def _judge_validation(
        self,
        guard: RequestGuard,
        case: ScientificCase,
        fixture: JudgeValidationResponse,
    ) -> dict[str, Any]:
        output = ScientificOutput(
            case_id=case.case_id,
            content=fixture.answer,
            tool_calls=fixture.tool_calls,
            environment_state=fixture.environment_state,
            output_hash=sha256_value(
                {
                    "answer": fixture.answer,
                    "tool_calls": [
                        item.model_dump(mode="json") for item in fixture.tool_calls
                    ],
                    "environment_state": fixture.environment_state,
                }
            ),
        )
        judge = AtomicJudge(
            self.models["judge"],
            responses_callable=lambda **kwargs: guard.call(
                stage="judge_validation",
                **kwargs,
            ),
            contract_retry_attempts=self.judge_contract_retry_attempts,
        )
        run = await judge.evaluate(case, output)
        actual = {item.criterion_id: item.decision for item in run.envelope.criteria}
        per_criterion = {
            criterion_id: {
                "expected": expected.value,
                "actual": actual[criterion_id].value,
                "match": actual[criterion_id] == expected,
            }
            for criterion_id, expected in fixture.expected_criterion_decisions.items()
        }
        return {
            "judge_result": run.envelope.model_dump(mode="json"),
            "judge_metadata": {
                "response_hash": run.response_hash,
                "provider_status": run.provider_status,
                "usage": run.usage.model_dump(mode="json"),
                "request_count": run.request_count,
                "output_contract_version": run.output_contract_version,
                "output_transport": run.output_transport,
                "contract_retry_diagnostics": list(run.attempt_diagnostics),
            },
            "comparison": {
                "response_id": fixture.response_id,
                "case_id": fixture.case_id,
                "reference_authority": fixture.reference_authority,
                "reference_version": fixture.reference_version,
                "expected_overall": fixture.expected_decision,
                "all_criteria_match": all(
                    item["match"] for item in per_criterion.values()
                ),
                "per_criterion": per_criterion,
                "validation_targets": fixture.validation_targets,
            },
        }

    async def _target_generation(
        self,
        guard: RequestGuard,
        node: ExecutionNode,
    ) -> ScientificOutput:
        config = self.configs[str(node.config_id)]
        slot = str(config["target_slot"])
        prompt = self.prompts[str(config["prompt_id"])]
        gateway = ScientificTargetGateway(
            self.models[slot],
            responses_callable=lambda **kwargs: guard.call(
                stage="formal_target_generation",
                **kwargs,
            ),
        )
        return await gateway.generate(
            case=self.cases[str(node.case_id)],
            system_prompt=prompt,
        )

    async def _judge_formal(
        self,
        guard: RequestGuard,
        node: ExecutionNode,
        output: ScientificOutput,
    ) -> tuple[Any, Any]:
        case = self.cases[str(node.case_id)]
        judge = AtomicJudge(
            self.models["judge"],
            responses_callable=lambda **kwargs: guard.call(
                stage="formal_judge_evaluation",
                **kwargs,
            ),
            contract_retry_attempts=self.judge_contract_retry_attempts,
        )
        run = await judge.evaluate(case, output)
        result = evaluate_scientific_case(
            case=case,
            config_id=str(node.config_id),
            output=output,
            judge_run=run,
        )
        return run, result

    async def _execute_node(
        self,
        state: dict[str, Any],
        guard: RequestGuard,
        node: ExecutionNode,
    ) -> dict[str, Any]:
        before = int(state.get("requests_used", 0))
        base = {
            "node_id": node.node_id,
            "stage": node.stage.value,
            "config_id": node.config_id,
            "case_id": node.case_id,
            "probe_id": node.probe_id,
            "completed_at": datetime.now(UTC).isoformat(),
        }
        if node.stage == ExecutionStage.OFFLINE_GATE:
            audit = audit_scientific_dataset(
                data_dir=self.data_dir,
                source_audit_path=self.source_audit_path,
                verify_seal=True,
            )
            if not audit["valid"]:
                raise ExecutionStopped("offline_gate_failed")
            return {**base, "status": "completed", "actual_requests": 0, "audit": audit}
        if node.stage == ExecutionStage.PROVIDER_PROBE:
            probe = await self._probe_target(guard, self.models[str(node.probe_id)])
            return {
                **base,
                "status": "completed",
                "actual_requests": int(state["requests_used"]) - before,
                "probe": probe,
            }
        if node.stage == ExecutionStage.TECHNICAL_PROBE:
            probe = await self._technical_probe(guard, str(node.probe_id))
            return {
                **base,
                "status": "completed",
                "actual_requests": int(state["requests_used"]) - before,
                "probe": probe,
            }
        if node.stage == ExecutionStage.JUDGE_VALIDATION:
            fixture = self.validation_responses[str(node.probe_id)]
            value = await self._judge_validation(
                guard,
                self.validation_cases[str(node.case_id)],
                fixture,
            )
            return {
                **base,
                "status": "completed",
                "actual_requests": int(state["requests_used"]) - before,
                **value,
            }
        if node.stage == ExecutionStage.TARGET_GENERATION:
            output = await self._target_generation(guard, node)
            return {
                **base,
                "status": "completed",
                "actual_requests": int(state["requests_used"]) - before,
                "output": output.model_dump(mode="json"),
            }
        if node.stage == ExecutionStage.TARGET_BARRIER:
            return {**base, "status": "completed", "actual_requests": 0}
        if node.stage == ExecutionStage.JUDGE_EVALUATION:
            target_node_id = f"target--{node.config_id}--{node.case_id}"
            target_node = self.store.load_node(target_node_id)
            case = self.cases[str(node.case_id)]
            if "output" not in target_node:
                error = target_node.get("error", {})
                result = runtime_result(
                    case=case,
                    config_id=str(node.config_id),
                    stage="target_generation",
                    error_type=str(error.get("error_type", "TargetRuntimeError")),
                    safe_message=str(error.get("classification", "target_runtime")),
                )
                return {
                    **base,
                    "status": "runtime_error",
                    "actual_requests": 0,
                    "error": error,
                    "result": result.model_dump(mode="json"),
                }
            output = ScientificOutput.model_validate(target_node["output"])
            try:
                run, result = await self._judge_formal(guard, node, output)
            except (ProviderCallError, AtomicJudgeParseError) as error:
                safe = _safe_runtime_error(error)
                result = runtime_result(
                    case=case,
                    config_id=str(node.config_id),
                    stage="judge_evaluation",
                    error_type=str(safe["error_type"]),
                    safe_message=str(safe["classification"]),
                    output=output,
                    target_request_count=output.request_count,
                    judge_request_count=int(state["requests_used"]) - before,
                )
                return {
                    **base,
                    "status": "runtime_error",
                    "actual_requests": int(state["requests_used"]) - before,
                    "error": safe,
                    "result": result.model_dump(mode="json"),
                }
            return {
                **base,
                "status": "completed",
                "actual_requests": int(state["requests_used"]) - before,
                "judge_metadata": {
                    "response_hash": run.response_hash,
                    "provider_status": run.provider_status,
                    "request_count": run.request_count,
                    "output_contract_version": run.output_contract_version,
                    "output_transport": run.output_transport,
                    "contract_retry_diagnostics": list(run.attempt_diagnostics),
                },
                "result": result.model_dump(mode="json"),
            }
        if node.stage == ExecutionStage.REPORT:
            reports = write_machine_reports(store=self.store, data_dir=self.data_dir)
            review = create_blind_review_package(
                store=self.store, data_dir=self.data_dir
            )
            return {
                **base,
                "status": "completed",
                "actual_requests": 0,
                "artifacts": {
                    key: str(path.relative_to(self.store.directory))
                    for key, path in {**reports, **review}.items()
                },
            }
        raise ValueError(f"unsupported execution stage: {node.stage}")

    async def execute(self) -> dict[str, Any]:
        state = self._load_or_start_state()
        if state.get("status") == "completed":
            return state
        try:
            self.models = resolve_runtime_models(self.protocol)
        except Exception as error:
            safe = _safe_runtime_error(error)
            state.update(
                {
                    "status": "stopped_hard",
                    "stop_reason": "runtime_profile_unavailable_or_invalid",
                    "safe_error": safe,
                    "finished_at": datetime.now(UTC).isoformat(),
                    "updated_at": datetime.now(UTC).isoformat(),
                }
            )
            self.store.write_state(state)
            return state
        guard = RequestGuard(
            store=self.store,
            state=state,
            plan=self.plan,
            raw_callable=self.raw_responses_callable,
            allow_runtime_recovery=self.allow_runtime_recovery,
            runtime_retry_attempts=self.runtime_retry_attempts,
        )
        try:
            for node in self.plan.nodes:
                if self.store.has_node(node.node_id):
                    continue
                self._assert_dependencies(node)
                self._set_current(state, node)
                if node.planned_requests:
                    self._begin_provider_node(state, node)
                before = int(state.get("requests_used", 0))
                try:
                    artifact = await self._execute_node(state, guard, node)
                except ExecutionStopped:
                    raise
                except (ProviderCallError, AtomicJudgeParseError) as error:
                    safe = _safe_runtime_error(error)
                    artifact = {
                        "node_id": node.node_id,
                        "stage": node.stage.value,
                        "config_id": node.config_id,
                        "case_id": node.case_id,
                        "probe_id": node.probe_id,
                        "status": "runtime_error",
                        "actual_requests": int(state["requests_used"]) - before,
                        "error": safe,
                        "completed_at": datetime.now(UTC).isoformat(),
                    }
                    if node.stage in {
                        ExecutionStage.PROVIDER_PROBE,
                        ExecutionStage.TECHNICAL_PROBE,
                    }:
                        self._finish_node(state, node, artifact)
                        raise ExecutionStopped(
                            "probe_contract_runtime_error", safe
                        ) from None
                except Exception as error:
                    safe = _safe_runtime_error(error)
                    artifact = {
                        "node_id": node.node_id,
                        "stage": node.stage.value,
                        "config_id": node.config_id,
                        "case_id": node.case_id,
                        "probe_id": node.probe_id,
                        "status": "runtime_error",
                        "actual_requests": int(state["requests_used"]) - before,
                        "error": safe,
                        "completed_at": datetime.now(UTC).isoformat(),
                    }
                    self._finish_node(state, node, artifact)
                    raise ExecutionStopped(
                        "local_execution_contract_error", safe
                    ) from None
                self._finish_node(state, node, artifact)
            state.update(
                {
                    "status": "completed",
                    "current_node": None,
                    "inflight_node": None,
                    "stop_reason": None,
                    "safe_error": None,
                    "finished_at": datetime.now(UTC).isoformat(),
                    "updated_at": datetime.now(UTC).isoformat(),
                }
            )
        except KeyboardInterrupt:
            state.update(
                {
                    "status": "interrupted",
                    "stop_reason": "keyboard_interrupt",
                    "updated_at": datetime.now(UTC).isoformat(),
                }
            )
        except ExecutionStopped as error:
            state.update(
                {
                    "status": "stopped_hard",
                    "stop_reason": error.reason,
                    "safe_error": error.safe_error,
                    "finished_at": datetime.now(UTC).isoformat(),
                    "updated_at": datetime.now(UTC).isoformat(),
                }
            )
        finally:
            self.store.write_state(state)
        return state


def execute_scientific_sync(executor: ScientificExecutor) -> dict[str, Any]:
    return asyncio.run(executor.execute())

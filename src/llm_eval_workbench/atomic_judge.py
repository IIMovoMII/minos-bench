from __future__ import annotations

import json
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from .hashing import sha256_text
from .model_gateway import (
    _response_completion,
    _response_output_text,
    _usage_from_response,
)
from .provider_auth import provider_api_key, provider_auth_context_async
from .schemas import UsageInfo
from .scientific_schemas import (
    AtomicJudgeEnvelope,
    ScientificCase,
    ScientificOutput,
)
from .secrets import ResolvedModel, uses_anthropic_wire_protocol

ResponsesCallable = Callable[..., Awaitable[Any]]

ATOMIC_JUDGE_PROTOCOL_VERSION = "atomic-judge-v1"
ATOMIC_JUDGE_BLIND_POLICY_VERSION = "scientific-target-identity-blind-v1"
ATOMIC_JUDGE_OUTPUT_CONTRACT_VERSION = "provider-native-structured-v1"


class AtomicJudgeParseError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        raw_content: str | None = None,
        diagnostic: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.raw_content = raw_content
        self.diagnostic = diagnostic or {}


@dataclass(frozen=True)
class AtomicJudgeRun:
    envelope: AtomicJudgeEnvelope
    usage: UsageInfo
    request_count: int
    latency_ms: int
    response_hash: str
    provider_status: str | None
    output_contract_version: str = ATOMIC_JUDGE_OUTPUT_CONTRACT_VERSION
    output_transport: str = "unknown"
    attempt_diagnostics: tuple[dict[str, Any], ...] = ()


def _sum_optional(values: list[int | float | None]) -> int | float | None:
    present = [value for value in values if value is not None]
    return sum(present) if present else None


def _merge_usage(values: list[UsageInfo]) -> UsageInfo:
    return UsageInfo(
        prompt_tokens=_sum_optional([item.prompt_tokens for item in values]),
        completion_tokens=_sum_optional(
            [item.completion_tokens for item in values]
        ),
        total_tokens=_sum_optional([item.total_tokens for item in values]),
        cost=_sum_optional([item.cost for item in values]),
        currency=values[-1].currency if values else "USD",
    )


def build_atomic_judge_payload(
    case: ScientificCase,
    output: ScientificOutput,
) -> dict[str, Any]:
    criteria = [
        {
            "criterion_id": item.criterion_id,
            "behavior": item.behavior,
            "applicability": item.applicability,
            "allowed_evidence": item.evidence,
            "pass_condition": item.pass_condition,
            "fail_condition": item.fail_condition,
            "abstain_condition": item.abstain_condition,
            "not_applicable_condition": item.not_applicable_condition,
        }
        for item in case.semantic_criteria
    ]
    return {
        "protocol_version": ATOMIC_JUDGE_PROTOCOL_VERSION,
        "case": {
            "task_pack": case.task_pack.value,
            "input": case.input,
            "context": case.context,
            "turns": [turn.model_dump(mode="json") for turn in case.turns],
            "available_tools": case.available_tools,
            "checker_boundary": case.checker_boundary,
        },
        "candidate_answer": {
            "content": output.content,
            "tool_calls": [
                call.model_dump(mode="json", exclude_none=True)
                for call in output.tool_calls
            ],
            "environment_state": output.environment_state,
            "tool_trace": output.tool_trace,
        },
        "criteria": criteria,
        "required_output_contract": {
            "protocol_version": ATOMIC_JUDGE_PROTOCOL_VERSION,
            "criteria": [
                {
                    "criterion_id": "registered criterion ID",
                    "applicability": "APPLICABLE or NOT_APPLICABLE",
                    "evidence_sufficiency": "SUFFICIENT or INSUFFICIENT",
                    "decision": "PASS, FAIL, or ABSTAIN",
                    "answer_evidence": ["verbatim span or structured action"],
                    "source_evidence": ["supporting case evidence"],
                    "reason": "brief criterion-specific reason",
                }
            ],
        },
    }


def atomic_judge_instructions(*, contract_retry: bool = False) -> str:
    instructions = (
        "You are an evidence-organizing evaluator, not the final business authority. "
        "Evaluate every registered semantic criterion exactly once and do not add, "
        "merge, rename, or omit criteria. Judge one behavior per criterion. Use only "
        "the supplied case evidence and candidate answer; external knowledge is not "
        "allowed. Evaluate only the semantic behavior named by the current criterion. "
        "Accept equivalent paraphrases that preserve the facts and business meaning. "
        "Unless the criterion explicitly evaluates format, punctuation, ordering, or "
        "exact wording, ignore those surface differences. Examples and reference-like "
        "phrasing, if present in criterion text, are illustrative and non-exhaustive; "
        "they are not the only valid answer. Do not duplicate mechanical conditions "
        "assigned to DIRECT_VERIFIER. A citation marker is not proof that the cited "
        "source supports the claim. Return FAIL only for a material contradiction, "
        "key omission, or unauthorized action that is covered by the criterion, and "
        "identify the answer evidence and impact in the reason. If an applicable "
        "criterion lacks enough evidence, return ABSTAIN with "
        "INSUFFICIENT. If it is not applicable, return NOT_APPLICABLE and ABSTAIN. "
        "Do not output severity, model identity, prompt identity, scores, confidence, "
        "new dimensions, or a final release recommendation. Output must be exactly "
        "one JSON object matching required_output_contract. The first non-whitespace "
        "character must be { and the last non-whitespace character must be }. Do not "
        "use Markdown fences, headings, bullet points, explanations, prefaces, or "
        "trailing notes. Use double quotes for all JSON keys and string values. "
        "Escape quotation marks, backslashes, and line breaks inside string values. "
        "Do not use comments or trailing commas. answer_evidence and source_evidence "
        "must always be JSON arrays of strings, including when empty. Use only the "
        "uppercase enum values shown in required_output_contract."
    )
    if contract_retry:
        instructions += (
            " The previous response could not be parsed as the required JSON contract. "
            "Return a fresh, complete JSON object from the original evidence. Do not "
            "refer to the previous response and do not omit any registered criterion."
        )
    return instructions


def _structured_output_kwargs(model_name: str) -> tuple[str, dict[str, Any]]:
    """Select LiteLLM's provider-native structured-output route.

    Anthropic's Responses adapter accepts its native ``output_format`` while
    retaining adaptive thinking. Other Responses adapters use LiteLLM's
    Pydantic ``text_format`` path.
    """
    if uses_anthropic_wire_protocol(model_name):
        return (
            "anthropic-native-json-schema",
            {
                "output_format": {
                    "type": "json_schema",
                    "schema": AtomicJudgeEnvelope.model_json_schema(),
                }
            },
        )
    return "litellm-responses-text-format", {"text_format": AtomicJudgeEnvelope}


def _parse_envelope(content: str) -> AtomicJudgeEnvelope:
    text = content.strip()
    fenced = re.fullmatch(
        r"```(?:json)?\s*(.*?)\s*```",
        text,
        flags=re.DOTALL | re.IGNORECASE,
    )
    if fenced:
        text = fenced.group(1)
    try:
        value = json.loads(text)
        if isinstance(value, dict) and isinstance(value.get("criteria"), list):
            normalized_criteria = []
            for item in value["criteria"]:
                if isinstance(item, dict):
                    item = dict(item)
                    if (
                        item.get("protocol_version")
                        == ATOMIC_JUDGE_PROTOCOL_VERSION
                    ):
                        item.pop("protocol_version")
                normalized_criteria.append(item)
            value = {**value, "criteria": normalized_criteria}
        return AtomicJudgeEnvelope.model_validate(value)
    except Exception as error:
        validation_errors = []
        if isinstance(error, ValidationError):
            validation_errors = [
                {
                    "location": [str(value) for value in item.get("loc", ())],
                    "type": item.get("type"),
                    "message": item.get("msg"),
                }
                for item in error.errors(include_url=False, include_input=False)
            ]
        json_error = None
        if isinstance(error, json.JSONDecodeError):
            json_error = {
                "message": error.msg,
                "line": error.lineno,
                "column": error.colno,
                "position": error.pos,
            }
        raise AtomicJudgeParseError(
            "Judge response violated atomic JSON contract",
            raw_content=content,
            diagnostic={
                "failure_stage": "json_or_schema_parse",
                "content_hash": sha256_text(content),
                "content_length": len(content),
                "underlying_error_type": type(error).__name__,
                "json_error": json_error,
                "validation_errors": validation_errors,
            },
        ) from error


def validate_registered_criteria(
    case: ScientificCase,
    envelope: AtomicJudgeEnvelope,
    *,
    raw_content: str | None = None,
) -> None:
    expected = [item.criterion_id for item in case.semantic_criteria]
    actual = [item.criterion_id for item in envelope.criteria]
    if len(actual) != len(set(actual)):
        raise AtomicJudgeParseError(
            "Judge returned duplicate criterion IDs",
            raw_content=raw_content,
            diagnostic={
                "failure_stage": "registered_criteria_validation",
                "reason": "duplicate_criterion_ids",
                "expected_criterion_ids": expected,
                "actual_criterion_ids": actual,
            },
        )
    if set(actual) != set(expected) or len(actual) != len(expected):
        raise AtomicJudgeParseError(
            "Judge criterion set differs from registration",
            raw_content=raw_content,
            diagnostic={
                "failure_stage": "registered_criteria_validation",
                "reason": "criterion_set_mismatch",
                "expected_criterion_ids": expected,
                "actual_criterion_ids": actual,
            },
        )


class AtomicJudge:
    def __init__(
        self,
        model: ResolvedModel,
        *,
        responses_callable: ResponsesCallable | None = None,
        timeout_seconds: int = 300,
        contract_retry_attempts: int = 0,
    ) -> None:
        if model.api_mode != "responses":
            raise ValueError("AtomicJudge requires Responses API mode")
        self.model = model
        self._responses_callable = responses_callable
        self.timeout_seconds = timeout_seconds
        if contract_retry_attempts < 0:
            raise ValueError("contract_retry_attempts must not be negative")
        self.contract_retry_attempts = contract_retry_attempts

    async def _responses(self, **kwargs: Any) -> Any:
        if self._responses_callable is None:
            import litellm

            litellm.suppress_debug_info = True
            callable_ = litellm.aresponses
        else:
            callable_ = self._responses_callable
        async with provider_auth_context_async(self.model):
            return await callable_(**kwargs)

    async def evaluate(
        self,
        case: ScientificCase,
        output: ScientificOutput,
    ) -> AtomicJudgeRun:
        if not case.semantic_criteria:
            raise ValueError("Atomic Judge requires registered semantic criteria")
        payload = build_atomic_judge_payload(case, output)
        kwargs: dict[str, Any] = {
            "model": self.model.model_name,
            "instructions": atomic_judge_instructions(),
            "input": [
                {
                    "role": "user",
                    "content": json.dumps(payload, ensure_ascii=False, sort_keys=True),
                }
            ],
            "api_key": provider_api_key(self.model),
            "max_output_tokens": self.model.params.max_tokens,
            "store": False,
            "stream": False,
            "timeout": self.timeout_seconds,
            "num_retries": 0,
            **self.model.params.extra,
        }
        output_transport, structured_output_kwargs = _structured_output_kwargs(
            self.model.model_name
        )
        kwargs.update(structured_output_kwargs)
        if self.model.base_url:
            kwargs["api_base"] = self.model.base_url.get_secret_value()
        started = time.perf_counter()
        usage_values: list[UsageInfo] = []
        attempt_diagnostics: list[dict[str, Any]] = []
        for attempt in range(self.contract_retry_attempts + 1):
            request_kwargs = {
                **kwargs,
                "instructions": atomic_judge_instructions(
                    contract_retry=attempt > 0
                ),
            }
            response = await self._responses(**request_kwargs)
            usage_values.append(_usage_from_response(response))
            content = _response_output_text(response)
            complete, provider_status, reason = _response_completion(
                response,
                content=content,
                tool_calls=[],
            )
            try:
                if not complete:
                    incomplete_message = (
                        "Judge response incomplete "
                        f"(status={provider_status or 'missing'}, "
                        f"reason={reason or 'unknown'})"
                    )
                    raise AtomicJudgeParseError(
                        incomplete_message,
                        raw_content=content,
                        diagnostic={
                            "failure_stage": "provider_completion_contract",
                            "provider_status": provider_status,
                            "incomplete_reason": reason,
                            "content_hash": sha256_text(content),
                            "content_length": len(content),
                        },
                    )
                envelope = _parse_envelope(content)
                validate_registered_criteria(case, envelope, raw_content=content)
            except AtomicJudgeParseError as error:
                if attempt >= self.contract_retry_attempts:
                    raise
                attempt_diagnostics.append(
                    {
                        "attempt": attempt + 1,
                        "error_type": type(error).__name__,
                        **error.diagnostic,
                    }
                )
                continue
            return AtomicJudgeRun(
                envelope=envelope,
                usage=_merge_usage(usage_values),
                request_count=attempt + 1,
                latency_ms=int((time.perf_counter() - started) * 1000),
                response_hash=sha256_text(content),
                provider_status=provider_status,
                output_transport=output_transport,
                attempt_diagnostics=tuple(attempt_diagnostics),
            )
        raise AssertionError("unreachable Judge retry state")

from __future__ import annotations

import time
from typing import Any

from .hashing import sha256_text
from .provider_auth import provider_api_key, provider_auth_context
from .schemas import (
    DataSplit,
    EvaluationCase,
    GeneratedOutput,
    JudgeConfig,
    Language,
    ModelConfig,
    SourceInfo,
    TaskPack,
)
from .secrets import resolve_model, safe_exception_details


def _value(value: Any, key: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(key, default)
    return getattr(value, key, default)


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


def probe_model(config: ModelConfig) -> dict[str, Any]:
    model = resolve_model(config)
    import litellm

    litellm.suppress_debug_info = True

    params = model.params
    kwargs: dict[str, Any] = {
        "model": model.model_name,
        "api_key": provider_api_key(model),
        "instructions": "Return only the requested text.",
        "input": "Reply with OK.",
        "temperature": params.temperature,
        "max_output_tokens": min(params.max_tokens, 256),
        "store": False,
        "stream": False,
        "timeout": 30,
        "num_retries": 0,
        **params.extra,
    }
    if model.base_url:
        kwargs["api_base"] = model.base_url.get_secret_value()
    if params.top_p is not None:
        kwargs["top_p"] = params.top_p
    if params.seed is not None:
        kwargs["seed"] = params.seed

    started = time.perf_counter()
    try:
        with provider_auth_context(model):
            response = litellm.responses(**kwargs)
    except Exception as error:
        error_type, message = safe_exception_details(error)
        return {
            "success": False,
            "alias": model.alias,
            "role": model.role,
            "model_name": model.model_name,
            "api_mode": model.api_mode,
            "reasoning_effort": model.reasoning_effort,
            "error_type": error_type,
            "error": message,
            "latency_ms": int((time.perf_counter() - started) * 1000),
        }

    output = _value(response, "output", []) or []
    usage = _value(response, "usage", {}) or {}
    hidden = _value(response, "_hidden_params", {}) or {}
    return {
        "success": bool(output),
        "alias": model.alias,
        "role": model.role,
        "model_name": model.model_name,
        "api_mode": model.api_mode,
        "reasoning_effort": model.reasoning_effort,
        "response_received": bool(output),
        "latency_ms": int((time.perf_counter() - started) * 1000),
        "prompt_tokens": _value(
            usage,
            "input_tokens",
            _value(usage, "prompt_tokens"),
        ),
        "completion_tokens": _value(
            usage,
            "output_tokens",
            _value(usage, "completion_tokens"),
        ),
        "total_tokens": _value(usage, "total_tokens"),
        "cost": _reported_cost(response, usage, hidden),
    }


def probe_judge(config: ModelConfig, judge_config: JudgeConfig) -> dict[str, Any]:
    model = resolve_model(config)
    from .metrics.deepeval_metrics import DeepEvalJudge

    case = EvaluationCase(
        case_id="PB-001",
        task_pack=TaskPack.INSTRUCTION_GENERATION,
        task_type="judge_compatibility_probe",
        language=Language.ENGLISH,
        title="Judge structured response probe",
        input="Reply with exactly OK.",
        expected_output="OK",
        rubric_id="RUBRIC-PROBE-V1",
        rubric="The output fully satisfies the instruction when it is exactly OK.",
        source=SourceInfo(
            type="synthetic",
            name="internal compatibility probe",
            reference="local://probe/judge-v1",
            license="Synthetic data authored for this POC",
            design_reason="Verify the real DeepEval Judge response contract.",
        ),
        split=DataSplit.DEVELOPMENT,
        version="1.0",
    )
    output = GeneratedOutput(
        run_id="compatibility-probe",
        case_id=case.case_id,
        model_alias="fixed_probe_output",
        model_name="local/fixed-output",
        prompt_id="probe",
        prompt_version="1.0",
        content="OK",
        attempts=0,
        request_count=0,
        output_hash=sha256_text("OK"),
    )
    started = time.perf_counter()
    try:
        result = DeepEvalJudge(
            model,
            judge_config.model_copy(update={"repetitions": 1}),
        ).evaluate(case, output)
    except Exception as error:
        error_type, message = safe_exception_details(error)
        return {
            "success": False,
            "alias": model.alias,
            "role": model.role,
            "model_name": model.model_name,
            "api_mode": model.api_mode,
            "reasoning_effort": model.reasoning_effort,
            "probe_type": "deepeval_judge_contract",
            "error_type": error_type,
            "error": message,
            "latency_ms": int((time.perf_counter() - started) * 1000),
        }
    return {
        "success": bool(result.scores),
        "alias": model.alias,
        "role": model.role,
        "model_name": model.model_name,
        "api_mode": model.api_mode,
        "reasoning_effort": model.reasoning_effort,
        "probe_type": "deepeval_judge_contract",
        "response_received": bool(result.scores),
        "latency_ms": int((time.perf_counter() - started) * 1000),
        "request_count": result.request_count,
        "scores": result.scores,
        "prompt_tokens": result.usage.prompt_tokens,
        "completion_tokens": result.usage.completion_tokens,
        "total_tokens": result.usage.total_tokens,
        "cost": result.usage.cost,
    }

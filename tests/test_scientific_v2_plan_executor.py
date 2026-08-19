from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from pydantic import SecretStr

from llm_eval_workbench.atomic_judge import AtomicJudgeRun
from llm_eval_workbench.schemas import GenerationParams, UsageInfo
from llm_eval_workbench.scientific_data import load_target_comparison
from llm_eval_workbench.scientific_evaluator import evaluate_scientific_case
from llm_eval_workbench.scientific_executor import ExecutionStopped, RequestGuard
from llm_eval_workbench.scientific_gateway import (
    EmptyProviderResponse,
    ScientificTargetGateway,
    simulate_environment_state,
)
from llm_eval_workbench.scientific_plan import (
    build_execution_plan,
    create_immutable_plan,
)
from llm_eval_workbench.scientific_report import build_machine_final_report
from llm_eval_workbench.scientific_schemas import (
    AtomicDecision,
    AtomicJudgeEnvelope,
    AtomicJudgeItem,
    EvidenceSufficiency,
    JudgeApplicability,
    ScientificOutput,
)
from llm_eval_workbench.scientific_store import (
    ScientificExecutionStore,
    atomic_write_json,
)
from llm_eval_workbench.secrets import ResolvedModel

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "datasets" / "scientific_v2"
PROTOCOL_PATH = PROJECT_ROOT / "configs" / "scientific_v2.json"
SOURCE_AUDIT = (
    PROJECT_ROOT.parents[1]
    / "research"
    / "PROJECT3_BENCHMARK_SOURCE_AUDIT_20260802.md"
)
FIXED_TIME = datetime(2026, 8, 4, tzinfo=UTC)


def _plan(execution_id: str):
    return build_execution_plan(
        execution_id=execution_id,
        data_dir=DATA_DIR,
        source_audit_path=SOURCE_AUDIT,
        protocol_path=PROTOCOL_PATH,
        created_at=FIXED_TIME,
    )


def _guard(
    tmp_path: Path,
    execution_id: str,
    raw_callable: Any,
) -> tuple[RequestGuard, dict[str, Any]]:
    plan = _plan(execution_id)
    root = tmp_path / "runs"
    create_immutable_plan(execution_root=root, plan=plan)
    store = ScientificExecutionStore(root, execution_id)
    state: dict[str, Any] = {
        "requests_used": 0,
        "transient_retries_used": 0,
    }
    return (
        RequestGuard(
            store=store,
            state=state,
            plan=plan,
            raw_callable=raw_callable,
            allow_runtime_recovery=True,
            runtime_retry_attempts=1,
        ),
        state,
    )


def test_v2_plan_is_fixed_to_24_cases_and_192_content_calls() -> None:
    plan = _plan("unit-plan-v2")
    assert plan.formal_case_count == 24
    assert plan.formal_target_requests == 96
    assert plan.formal_judge_requests == 96
    assert plan.provider_probe_requests == 4
    assert plan.technical_probe_requests == 0
    assert plan.judge_validation_requests == 0
    assert plan.planned_base_requests == 196
    assert len(plan.nodes) == 200


def test_atomic_state_write_retries_transient_reader_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import os

    calls = 0
    real_replace = os.replace

    def flaky_replace(source: Any, destination: Any) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise PermissionError(5, "unit reader lock")
        real_replace(source, destination)

    monkeypatch.setattr(
        "llm_eval_workbench.scientific_store.os.replace",
        flaky_replace,
    )
    path = tmp_path / "state.json"
    atomic_write_json(path, {"status": "running"})
    assert calls == 2
    assert path.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_local_state_write_failure_never_calls_provider_or_counts_request(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    async def provider(**_: Any) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        return {"status": "completed", "output_text": "unused"}

    execution_id = "state-stop-v2"
    plan = _plan(execution_id)
    root = tmp_path / "runs"
    create_immutable_plan(execution_root=root, plan=plan)
    store = ScientificExecutionStore(root, execution_id)
    state: dict[str, Any] = {"requests_used": 0, "transient_retries_used": 0}

    def blocked_write(_: dict[str, Any]) -> None:
        raise PermissionError(5, "unit reader lock")

    monkeypatch.setattr(store, "write_state", blocked_write)
    guard = RequestGuard(
        store=store,
        state=state,
        plan=plan,
        raw_callable=provider,
        allow_runtime_recovery=True,
        runtime_retry_attempts=1,
    )
    with pytest.raises(ExecutionStopped, match="local_state_persistence_error"):
        await guard.call(stage="formal_target_generation")
    assert calls == 0
    assert state["requests_used"] == 0


@pytest.mark.asyncio
async def test_empty_provider_payload_gets_one_retry(tmp_path: Path) -> None:
    calls = 0

    async def empty_then_success(**_: Any) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise EmptyProviderResponse("empty fixture")
        return {"status": "completed", "output_text": "usable payload"}

    guard, state = _guard(tmp_path, "empty-retry-v2", empty_then_success)
    response = await guard.call(stage="formal_target_generation")
    assert response["output_text"] == "usable payload"
    assert calls == 2
    assert state["requests_used"] == 2


@pytest.mark.asyncio
async def test_runtime_recovery_stops_deterministic_route_failure_immediately(
    tmp_path: Path,
) -> None:
    calls = 0

    class ServiceUnavailableError(RuntimeError):
        status_code = 503

        def __init__(self) -> None:
            super().__init__("relay failure")
            self.message = "No available channel for model unit-judge"

    async def unavailable_route(**_: Any) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        raise ServiceUnavailableError

    guard, state = _guard(tmp_path, "route-stop-v2", unavailable_route)
    with pytest.raises(ExecutionStopped, match="provider_route_unavailable"):
        await guard.call(stage="formal_judge_evaluation")
    assert calls == 1
    assert state["requests_used"] == 1


@pytest.mark.asyncio
async def test_nonempty_wrong_answer_is_not_retried(tmp_path: Path) -> None:
    calls = 0

    async def valid_but_wrong(**_: Any) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        return {"status": "completed", "output_text": "nonempty but incorrect"}

    guard, state = _guard(tmp_path, "wrong-no-retry-v2", valid_but_wrong)
    response = await guard.call(stage="formal_target_generation")
    assert response["output_text"] == "nonempty but incorrect"
    assert calls == 1
    assert state["requests_used"] == 1


@pytest.mark.asyncio
async def test_target_gateway_retries_empty_completed_response_once(
    tmp_path: Path,
) -> None:
    case = next(
        item
        for item in load_target_comparison(DATA_DIR)
        if item.task_pack.value == "instruction_generation"
    )
    model = ResolvedModel(
        alias="unit-target",
        role="target",
        model_name="openai/unit-target",
        api_key=SecretStr("placeholder"),
        base_url=SecretStr("https://unit.invalid/v1"),
        api_mode="responses",
        reasoning_effort=None,
        params=GenerationParams(max_tokens=64),
    )
    calls = 0

    async def empty_then_valid(**_: Any) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        if calls == 1:
            return {"status": "completed", "output_text": ""}
        return {"status": "completed", "output_text": "valid answer"}

    guard, state = _guard(tmp_path, "gateway-empty-retry-v2", empty_then_valid)
    gateway = ScientificTargetGateway(
        model,
        responses_callable=lambda **kwargs: guard.call(
            stage="formal_target_generation", **kwargs
        ),
    )
    output = await gateway.generate(case=case, system_prompt="unit prompt")
    assert output.content == "valid answer"
    assert output.request_count == 2
    assert calls == 2
    assert state["requests_used"] == 2


def test_v2_machine_final_report_reuses_prior_judge_acceptance(
    tmp_path: Path,
) -> None:
    store = ScientificExecutionStore(tmp_path / "runs", "report-final-v2")
    for case in load_target_comparison(DATA_DIR):
        output = ScientificOutput(
            case_id=case.case_id,
            content=case.gold_answer or "",
            tool_calls=case.gold_tool_calls,
            environment_state=(
                case.gold_environment_state
                or simulate_environment_state(case, case.gold_tool_calls)
            ),
            request_count=1,
            output_hash=f"gold-{case.case_id}",
        )
        envelope = AtomicJudgeEnvelope(
            criteria=[
                AtomicJudgeItem(
                    criterion_id=criterion.criterion_id,
                    applicability=JudgeApplicability.APPLICABLE,
                    evidence_sufficiency=EvidenceSufficiency.SUFFICIENT,
                    decision=AtomicDecision.PASS,
                    answer_evidence=["gold fixture"],
                    source_evidence=[criterion.evidence[0]],
                    reason="registered gold behavior",
                )
                for criterion in case.semantic_criteria
            ]
        )
        judge_run = AtomicJudgeRun(
            envelope=envelope,
            usage=UsageInfo(),
            request_count=1,
            latency_ms=1,
            response_hash=f"judge-{case.case_id}",
            provider_status="completed",
        )
        for config_id in (
            "model_a_prompt_v1",
            "model_b_prompt_v1",
            "weak_prompt_v1",
            "weak_prompt_v2",
        ):
            result = evaluate_scientific_case(
                case=case,
                config_id=config_id,
                output=output,
                judge_run=judge_run,
            )
            node_id = f"judge--{config_id}--{case.case_id}"
            store.write_node_once(
                node_id,
                {
                    "node_id": node_id,
                    "stage": "judge_evaluation",
                    "config_id": config_id,
                    "case_id": case.case_id,
                    "status": "completed",
                    "result": result.model_dump(mode="json"),
                },
            )

    report = build_machine_final_report(
        store=store,
        data_dir=DATA_DIR,
        require_judge_validation=False,
        judge_validation_reference="scientific-v1.7",
    )
    assert report["completion_rate"] == 1.0
    validation = report["judge_validation_summary"]
    assert validation["completed_items"] == 0
    assert validation["status"] == "reused_prior_engine_acceptance"
    assert validation["reference_version"] == "scientific-v1.7"
    for summary in report["config_summaries"].values():
        assert set(summary["difficulty_scores"]) == {"D2", "D3"}
        assert len(summary["risk_cell_scores"]) == 12

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from llm_eval_workbench.scientific_executor import (
    ProviderCallError,
    RequestGuard,
    ScientificExecutor,
)
from llm_eval_workbench.scientific_plan import (
    build_execution_plan,
    create_immutable_plan,
)
from llm_eval_workbench.scientific_schemas import ExecutionStage
from llm_eval_workbench.scientific_store import ScientificExecutionStore

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "datasets" / "scientific_v1"
PROTOCOL_PATH = PROJECT_ROOT / "configs" / "scientific_v1.json"
SOURCE_AUDIT = (
    PROJECT_ROOT.parents[1]
    / "research"
    / "PROJECT3_BENCHMARK_SOURCE_AUDIT_20260802.md"
)
FIXED_TIME = datetime(2026, 8, 2, tzinfo=UTC)


def _plan(execution_id: str):
    return build_execution_plan(
        execution_id=execution_id,
        data_dir=DATA_DIR,
        source_audit_path=SOURCE_AUDIT,
        protocol_path=PROTOCOL_PATH,
        created_at=FIXED_TIME,
    )


def _configure_dummy_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    slots = {
        "MODEL_A": "openai/unit-target-a",
        "MODEL_B": "openai/unit-target-b",
        "WEAK_MODEL": "openai/unit-target-weak",
        "JUDGE_MODEL": "openai/unit-judge",
    }
    for prefix, model_name in slots.items():
        monkeypatch.setenv(f"{prefix}_NAME", model_name)
        monkeypatch.setenv(f"{prefix}_API_KEY", "unit-test-placeholder")
        monkeypatch.setenv(f"{prefix}_BASE_URL", "https://unit.invalid/v1")
        monkeypatch.setenv(f"{prefix}_API_MODE", "responses")
        monkeypatch.setenv(f"{prefix}_REASONING_EFFORT", "max")


def _judge_response(kwargs: dict[str, Any]) -> dict[str, Any]:
    payload = json.loads(kwargs["input"][0]["content"])
    criteria = [
        {
            "criterion_id": item["criterion_id"],
            "applicability": "APPLICABLE",
            "evidence_sufficiency": "SUFFICIENT",
            "decision": "PASS",
            "answer_evidence": ["OK"],
            "source_evidence": [item["allowed_evidence"][0]],
            "reason": "deterministic fake Responses decision",
        }
        for item in payload["criteria"]
    ]
    return {
        "status": "completed",
        "output_text": json.dumps(
            {"protocol_version": "atomic-judge-v1", "criteria": criteria}
        ),
        "usage": {"input_tokens": 2, "output_tokens": 1, "total_tokens": 3},
    }


def _successful_response(kwargs: dict[str, Any]) -> dict[str, Any]:
    instructions = str(kwargs.get("instructions", ""))
    if "evidence-organizing evaluator" in instructions:
        return _judge_response(kwargs)
    has_tool_return = any(
        isinstance(item, dict) and item.get("type") == "function_call_output"
        for item in kwargs.get("input", [])
    )
    if kwargs.get("tools") and not has_tool_return:
        return {
            "status": "completed",
            "output": [
                {
                    "type": "function_call",
                    "call_id": "unit-call-1",
                    "name": kwargs["tools"][0]["name"],
                    "arguments": json.dumps({"value": "OK"}),
                }
            ],
            "usage": {"input_tokens": 2, "output_tokens": 1, "total_tokens": 3},
        }
    content = '{"ok": true}' if "Return only valid JSON" in instructions else "OK"
    return {
        "status": "completed",
        "output_text": content,
        "usage": {"input_tokens": 2, "output_tokens": 1, "total_tokens": 3},
    }


def test_plan_is_fixed_finite_and_has_no_second_judge_or_auto_round() -> None:
    plan = _plan("unit-plan-v1")
    assert plan.formal_case_count == 25
    assert plan.formal_target_requests == 100
    assert plan.formal_judge_requests == 100
    assert plan.provider_probe_requests == 4
    assert plan.technical_probe_requests == 6
    assert plan.judge_validation_requests == 14
    assert plan.planned_base_requests == 224
    assert plan.absolute_request_ceiling is None
    assert plan.transient_retry_cap is None
    stage_counts = {
        stage: sum(node.stage == stage for node in plan.nodes)
        for stage in ExecutionStage
    }
    assert stage_counts[ExecutionStage.TARGET_GENERATION] == 100
    assert stage_counts[ExecutionStage.JUDGE_EVALUATION] == 100
    assert stage_counts[ExecutionStage.JUDGE_VALIDATION] == 14
    assert not any(
        marker in node.node_id.casefold()
        for node in plan.nodes
        for marker in ("second-judge", "stability", "repeat", "auto-round")
    )


def test_tampered_unknown_case_id_is_rejected(tmp_path: Path) -> None:
    from llm_eval_workbench.scientific_plan import load_and_verify_plan

    root = tmp_path / "runs"
    plan = _plan("unknown-case-v1")
    node = next(
        item for item in plan.nodes if item.stage == ExecutionStage.TARGET_GENERATION
    )
    node.case_id = "CMP-IG-99"
    path = create_immutable_plan(execution_root=root, plan=plan)
    with pytest.raises(ValueError, match="formal case/config references"):
        load_and_verify_plan(
            plan_path=path,
            data_dir=DATA_DIR,
            protocol_path=PROTOCOL_PATH,
        )


def test_execution_plan_is_immutable_and_must_exist(tmp_path: Path) -> None:
    root = tmp_path / "runs"
    plan = _plan("immutable-v1")
    path = create_immutable_plan(execution_root=root, plan=plan)
    assert create_immutable_plan(execution_root=root, plan=plan) == path
    changed = plan.model_copy(update={"absolute_request_ceiling": 999})
    with pytest.raises(FileExistsError, match="immutable"):
        create_immutable_plan(execution_root=root, plan=changed)
    with pytest.raises(FileNotFoundError):
        ScientificExecutor(
            project_root=PROJECT_ROOT,
            data_dir=DATA_DIR,
            source_audit_path=SOURCE_AUDIT,
            protocol_path=PROTOCOL_PATH,
            execution_root=root,
            execution_id="missing-plan-v1",
            raw_responses_callable=lambda **_: None,  # type: ignore[arg-type]
        )


@pytest.mark.asyncio
async def test_full_fake_responses_matrix_is_bounded_resumable_and_blind(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_dummy_runtime(monkeypatch)
    root = tmp_path / "runs"
    execution_id = "full-fake-v1"
    plan = _plan(execution_id)
    create_immutable_plan(execution_root=root, plan=plan)
    calls: list[dict[str, Any]] = []

    async def fake_responses(**kwargs: Any) -> dict[str, Any]:
        calls.append(kwargs)
        return _successful_response(kwargs)

    executor = ScientificExecutor(
        project_root=PROJECT_ROOT,
        data_dir=DATA_DIR,
        source_audit_path=SOURCE_AUDIT,
        protocol_path=PROTOCOL_PATH,
        execution_root=root,
        execution_id=execution_id,
        raw_responses_callable=fake_responses,
    )
    state = await executor.execute()
    assert state["status"] == "completed"
    assert state["requests_used"] == 224
    assert state["transient_retries_used"] == 0
    assert len(calls) == 224

    execution_dir = root / execution_id
    report = json.loads(
        (execution_dir / "machine_preliminary_report.json").read_text(
            encoding="utf-8"
        )
    )
    assert report["report_type"] == "machine_preliminary"
    package = json.loads(
        (execution_dir / "candidate_blind_review_package.json").read_text(
            encoding="utf-8"
        )
    )
    assert package["identity_hidden"] is True
    assert package["judge_results_hidden"] is True
    assert package["item_count"] == 100
    package_text = json.dumps(package, ensure_ascii=False)
    for forbidden in (
        '"config_id":',
        '"model_name":',
        '"model_alias":',
        '"prompt_id":',
        '"judge_result":',
        '"machine_status":',
        "unit-target-a",
        "unit-target-b",
        "unit-target-weak",
    ):
        assert forbidden not in package_text

    for index, call in enumerate(calls):
        assert call["store"] is False
        assert call["stream"] is False
        assert call["num_retries"] == 0
        if index < 4:
            assert "reasoning" not in call
            assert "output_config" not in call
            assert call["max_output_tokens"] == 32
            assert call["input"] == [{"role": "user", "content": "ping"}]
        else:
            assert call["reasoning"] == {"effort": "max"}
        assert "temperature" not in call
        if "evidence-organizing evaluator" in str(call["instructions"]):
            judge_input = str(call["input"])
            assert "model_a_prompt_v1" not in judge_input
            assert "model_b_prompt_v1" not in judge_input
            assert "weak_prompt_v1" not in judge_input
            assert "weak_prompt_v2" not in judge_input

    assert any(
        call.get("tools")
        and "Use the provided tool when requested" in str(call["instructions"])
        for call in calls
    )
    assert any(
        any(
            isinstance(item, dict) and item.get("type") == "function_call_output"
            for item in call.get("input", [])
        )
        for call in calls
    )
    assert any(
        "Use only the supplied source" in str(call["instructions"]) for call in calls
    )
    assert any(
        "Respect the latest conversation state" in str(call["instructions"])
        for call in calls
    )
    assert any("Return only valid JSON" in str(call["instructions"]) for call in calls)

    before_resume = len(calls)
    resumed = await ScientificExecutor(
        project_root=PROJECT_ROOT,
        data_dir=DATA_DIR,
        source_audit_path=SOURCE_AUDIT,
        protocol_path=PROTOCOL_PATH,
        execution_root=root,
        execution_id=execution_id,
        raw_responses_callable=fake_responses,
    ).execute()
    assert resumed["status"] == "completed"
    assert len(calls) == before_resume


@pytest.mark.asyncio
async def test_transient_failures_retry_until_the_request_succeeds(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_dummy_runtime(monkeypatch)
    root = tmp_path / "runs"
    execution_id = "transient-stop-v1"
    create_immutable_plan(execution_root=root, plan=_plan(execution_id))
    calls = 0

    async def no_wait(_: float) -> None:
        return None

    monkeypatch.setattr(
        "llm_eval_workbench.scientific_executor.asyncio.sleep", no_wait
    )

    async def eventually_successful_response(**kwargs: Any) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        if calls <= 3:
            raise TimeoutError("unit test timeout")
        return _successful_response(kwargs)

    state = await ScientificExecutor(
        project_root=PROJECT_ROOT,
        data_dir=DATA_DIR,
        source_audit_path=SOURCE_AUDIT,
        protocol_path=PROTOCOL_PATH,
        execution_root=root,
        execution_id=execution_id,
        raw_responses_callable=eventually_successful_response,
    ).execute()
    assert calls == 227
    assert state["requests_used"] == 227
    assert state["transient_retries_used"] == 3
    assert state["status"] == "completed"
    assert state["stop_reason"] is None


@pytest.mark.asyncio
async def test_hard_provider_error_stops_on_first_occurrence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_dummy_runtime(monkeypatch)
    root = tmp_path / "runs"
    execution_id = "hard-stop-v1"
    create_immutable_plan(execution_root=root, plan=_plan(execution_id))
    calls = 0

    class UnsupportedParamsError(RuntimeError):
        status_code = 400

    async def hard_failure(**_: Any) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        raise UnsupportedParamsError("unit test only")

    state = await ScientificExecutor(
        project_root=PROJECT_ROOT,
        data_dir=DATA_DIR,
        source_audit_path=SOURCE_AUDIT,
        protocol_path=PROTOCOL_PATH,
        execution_root=root,
        execution_id=execution_id,
        raw_responses_callable=hard_failure,
    ).execute()
    assert calls == 1
    assert state["requests_used"] == 1
    assert state["status"] == "stopped_hard"
    assert state["stop_reason"] == "hard_provider_error"


@pytest.mark.asyncio
async def test_formal_target_400_is_deferred_to_case_runtime_handling(
    tmp_path: Path,
) -> None:
    execution_id = "case-scoped-400-v1"
    plan = _plan(execution_id)
    store = ScientificExecutionStore(tmp_path / "runs", execution_id)
    state: dict[str, Any] = {
        "requests_used": 0,
        "transient_retries_used": 0,
    }

    class BadRequestError(RuntimeError):
        status_code = 400

    async def rejected_case(**_: Any) -> dict[str, Any]:
        raise BadRequestError("unit test only")

    guard = RequestGuard(
        store=store,
        state=state,
        plan=plan,
        raw_callable=rejected_case,
    )

    with pytest.raises(ProviderCallError) as raised:
        await guard.call(stage="formal_target_generation")

    assert raised.value.safe_error == {
        "error_type": "BadRequestError",
        "classification": "hard_provider_contract",
        "http_status": 400,
    }
    assert state["requests_used"] == 1


@pytest.mark.asyncio
async def test_runtime_recovery_retries_provider_error_once(
    tmp_path: Path,
) -> None:
    execution_id = "case-scoped-recovery-v1"
    store = ScientificExecutionStore(tmp_path / "runs", execution_id)
    state: dict[str, Any] = {
        "requests_used": 0,
        "transient_retries_used": 0,
    }
    calls = 0

    class BadRequestError(RuntimeError):
        status_code = 400

    async def rejected_then_completed(**_: Any) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise BadRequestError("unit test only")
        return {"status": "completed", "output_text": "OK"}

    guard = RequestGuard(
        store=store,
        state=state,
        plan=_plan(execution_id),
        raw_callable=rejected_then_completed,
        allow_runtime_recovery=True,
    )

    response = await guard.call(stage="formal_target_generation")

    assert response["output_text"] == "OK"
    assert calls == 2
    assert state["requests_used"] == 2


@pytest.mark.asyncio
async def test_relay_no_available_channel_503_stops_without_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_dummy_runtime(monkeypatch)
    root = tmp_path / "runs"
    execution_id = "route-unavailable-v1"
    create_immutable_plan(execution_root=root, plan=_plan(execution_id))
    calls = 0

    class ServiceUnavailableError(RuntimeError):
        status_code = 503

        def __init__(self) -> None:
            super().__init__("relay failure")
            self.message = "No available channel for model unit-target"

    async def unavailable_route(**_: Any) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        raise ServiceUnavailableError

    state = await ScientificExecutor(
        project_root=PROJECT_ROOT,
        data_dir=DATA_DIR,
        source_audit_path=SOURCE_AUDIT,
        protocol_path=PROTOCOL_PATH,
        execution_root=root,
        execution_id=execution_id,
        raw_responses_callable=unavailable_route,
    ).execute()
    assert calls == 1
    assert state["requests_used"] == 1
    assert state["transient_retries_used"] == 0
    assert state["status"] == "stopped_hard"
    assert state["stop_reason"] == "provider_route_unavailable"
    assert state["safe_error"] == {
        "error_type": "ServiceUnavailableError",
        "classification": "hard_provider_route",
        "http_status": 503,
        "error_code": "no_available_model_channel",
    }


@pytest.mark.asyncio
async def test_provider_route_resume_keeps_successful_probes_and_clears_old_stop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_dummy_runtime(monkeypatch)
    root = tmp_path / "runs"
    execution_id = "judge-route-resume-v1"
    create_immutable_plan(execution_root=root, plan=_plan(execution_id))
    initial_calls: list[dict[str, Any]] = []

    class ServiceUnavailableError(RuntimeError):
        status_code = 503

        def __init__(self) -> None:
            super().__init__("relay failure")
            self.message = "No available channel for model unit-judge"

    async def judge_route_unavailable(**kwargs: Any) -> dict[str, Any]:
        initial_calls.append(kwargs)
        if kwargs.get("model") == "openai/unit-judge":
            raise ServiceUnavailableError
        return _successful_response(kwargs)

    stopped = await ScientificExecutor(
        project_root=PROJECT_ROOT,
        data_dir=DATA_DIR,
        source_audit_path=SOURCE_AUDIT,
        protocol_path=PROTOCOL_PATH,
        execution_root=root,
        execution_id=execution_id,
        raw_responses_callable=judge_route_unavailable,
        allow_runtime_recovery=True,
    ).execute()
    assert len(initial_calls) == 4
    assert stopped["status"] == "stopped_hard"
    assert stopped["stop_reason"] == "provider_route_unavailable"
    store = ScientificExecutionStore(root, execution_id)
    assert all(
        store.has_node(node_id)
        for node_id in (
            "provider-probe-model-a",
            "provider-probe-model-b",
            "provider-probe-weak",
        )
    )
    assert not store.has_node("provider-probe-judge")

    resumed_calls: list[dict[str, Any]] = []

    async def successful_resume(**kwargs: Any) -> dict[str, Any]:
        resumed_calls.append(kwargs)
        return _successful_response(kwargs)

    resumed = await ScientificExecutor(
        project_root=PROJECT_ROOT,
        data_dir=DATA_DIR,
        source_audit_path=SOURCE_AUDIT,
        protocol_path=PROTOCOL_PATH,
        execution_root=root,
        execution_id=execution_id,
        raw_responses_callable=successful_resume,
        allow_runtime_recovery=True,
    ).execute()
    assert resumed["status"] == "completed"
    assert resumed["requests_used"] == 225
    assert resumed["stop_reason"] is None
    assert resumed["safe_error"] is None
    assert resumed["finished_at"] is not None
    assert len(resumed_calls) == 221
    assert resumed_calls[0]["model"] == "openai/unit-judge"
    assert all(
        call["model"]
        not in {
            "openai/unit-target-a",
            "openai/unit-target-b",
            "openai/unit-target-weak",
        }
        for call in resumed_calls[:1]
    )


@pytest.mark.asyncio
async def test_judge_validation_contract_error_is_advisory_and_matrix_continues(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_dummy_runtime(monkeypatch)
    root = tmp_path / "runs"
    execution_id = "judge-contract-stop-v1"
    create_immutable_plan(execution_root=root, plan=_plan(execution_id))
    judge_calls = 0
    all_calls = 0

    async def invalid_first_validation(**kwargs: Any) -> dict[str, Any]:
        nonlocal all_calls, judge_calls
        all_calls += 1
        if "evidence-organizing evaluator" in str(kwargs.get("instructions", "")):
            judge_calls += 1
            if judge_calls == 2:
                return {"status": "completed", "output_text": "not json"}
        return _successful_response(kwargs)

    state = await ScientificExecutor(
        project_root=PROJECT_ROOT,
        data_dir=DATA_DIR,
        source_audit_path=SOURCE_AUDIT,
        protocol_path=PROTOCOL_PATH,
        execution_root=root,
        execution_id=execution_id,
        raw_responses_callable=invalid_first_validation,
    ).execute()
    assert all_calls == 224
    assert state["requests_used"] == 224
    assert state["status"] == "completed"
    assert state["stop_reason"] is None
    failed_validation = json.loads(
        (
            root
            / execution_id
            / "nodes"
            / "judge-validation--JV-GQ-03-PASS.json"
        ).read_text(encoding="utf-8")
    )
    assert failed_validation["status"] == "runtime_error"
    assert failed_validation["error"]["error_type"] == "AtomicJudgeParseError"
    assert any(
        path.name.startswith("target--")
        for path in (root / execution_id / "nodes").glob("*.json")
    )
    assert (root / execution_id / "judge_validation_report.json").is_file()
    assert (root / execution_id / "candidate_blind_review_package.json").is_file()

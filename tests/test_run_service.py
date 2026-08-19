from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from llm_eval_workbench.hashing import sha256_text
from llm_eval_workbench.metrics.deepeval_metrics import JudgeRun
from llm_eval_workbench.run_service import RunService
from llm_eval_workbench.schemas import (
    DataSplit,
    DeterministicCheckSpec,
    EvaluationCase,
    GeneratedOutput,
    ImportedOutput,
    Language,
    MetricResult,
    RunMode,
    RunStatus,
    RunStopReason,
    SourceInfo,
    TaskPack,
)


class FakeGateway:
    def __init__(self, model):
        self.model = model

    async def generate(self, *, run_id, case, prompt):
        content = "1. 建议一\n2. 建议二\n3. 建议三"
        return GeneratedOutput(
            run_id=run_id,
            case_id=case.case_id,
            model_alias=self.model.alias,
            model_name=self.model.model_name,
            prompt_id=prompt.prompt_id,
            prompt_version=prompt.version,
            content=content,
            output_hash=sha256_text(content),
        )


class IncompleteGateway:
    def __init__(self, model):
        self.model = model

    async def generate(self, *, run_id, case, prompt):
        content = "只生成了一半"
        return GeneratedOutput(
            run_id=run_id,
            case_id=case.case_id,
            model_alias=self.model.alias,
            model_name=self.model.model_name,
            prompt_id=prompt.prompt_id,
            prompt_version=prompt.version,
            content=content,
            generation_complete=False,
            provider_response_status="incomplete",
            provider_incomplete_reason="max_output_tokens",
            output_hash=sha256_text(content),
        )


class BrokenGateway:
    def __init__(self, model):
        self.model = model
        self.calls = 0

    async def generate(self, *, run_id, case, prompt):
        self.calls += 1
        raise TimeoutError("repeated provider failure")


class TwoRequestGateway(FakeGateway):
    async def generate(self, *, run_id, case, prompt):
        output = await super().generate(run_id=run_id, case=case, prompt=prompt)
        return output.model_copy(update={"attempts": 2, "request_count": 2})


class FakeJudge:
    def __init__(self, model):
        self.model = model

    def evaluate(self, case, output):
        return JudgeRun(
            metrics=[
                MetricResult(
                    metric_id="judge.fake",
                    kind="judge",
                    passed=True,
                    score=0.9,
                    threshold=0.75,
                    reason="fake",
                )
            ],
            scores=[0.9],
        )


class TwoRequestJudge(FakeJudge):
    def evaluate(self, case, output):
        result = super().evaluate(case, output)
        return JudgeRun(
            metrics=result.metrics,
            scores=result.scores,
            request_count=2,
        )


def make_temp_project(
    root: Path,
    resolved_target,
    resolved_judge,
) -> Path:
    (root / "datasets").mkdir()
    (root / "configs").mkdir()
    case = EvaluationCase(
        case_id="IG-901",
        task_pack=TaskPack.INSTRUCTION_GENERATION,
        task_type="instruction_following",
        language=Language.CHINESE,
        title="three items",
        input="三条建议",
        expected_output="三条建议",
        rubric_id="R1",
        rubric="完整",
        deterministic_checks=[
            DeterministicCheckSpec(
                check_id="count",
                type="list_item_count",
                description="three",
                params={"exact": 3},
            )
        ],
        source=SourceInfo(
            type="synthetic",
            name="test",
            reference="test",
            license="CC0-1.0",
            design_reason="test",
        ),
        split=DataSplit.DEVELOPMENT,
        version="1",
    )
    (root / "datasets" / "cases.jsonl").write_text(
        case.model_dump_json() + "\n",
        encoding="utf-8",
    )
    (root / "configs" / "metrics.yaml").write_text(
        "version: '1'\n",
        encoding="utf-8",
    )
    config = """
project_id: test
name: test
version: "1"
dataset_paths: [datasets/cases.jsonl]
metric_profile_path: configs/metrics.yaml
artifact_dir: artifacts/runs
models:
  - alias: model_a
    role: target
    model_env: TEST_MODEL
    api_key_env: TEST_KEY
    base_url_env: TEST_BASE
    params:
      temperature: 0
      max_tokens: 200
  - alias: judge
    role: judge
    model_env: JUDGE_MODEL
    api_key_env: JUDGE_KEY
    base_url_env: JUDGE_BASE
    params:
      temperature: 0
      max_tokens: 200
target_model_alias: model_a
prompt_id: v1
prompts:
  - prompt_id: v1
    version: "1"
    system_template: system
    user_template: "{input}"
judge:
  model_alias: judge
  threshold: 0.75
  review_floor: 0.45
  repetitions: 1
  instability_delta: 0.2
  include_reason: true
"""
    config_path = root / "configs" / "project.yaml"
    config_path.write_text(config.strip() + "\n", encoding="utf-8")
    return config_path


def expand_temp_cases(root: Path, count: int) -> None:
    path = root / "datasets" / "cases.jsonl"
    base = EvaluationCase.model_validate_json(path.read_text(encoding="utf-8"))
    cases = [
        base.model_copy(update={"case_id": f"IG-{901 + index}"})
        for index in range(count)
    ]
    path.write_text(
        "".join(case.model_dump_json() + "\n" for case in cases),
        encoding="utf-8",
    )


@pytest.mark.asyncio
async def test_live_then_deterministic_replay(
    tmp_path, resolved_target, resolved_judge
):
    target_with_reasoning = replace(
        resolved_target,
        reasoning_effort="max",
        params=resolved_target.params.model_copy(
            update={"extra": {"reasoning": {"effort": "max"}}}
        ),
    )
    judge_with_reasoning = replace(
        resolved_judge,
        reasoning_effort="max",
        params=resolved_judge.params.model_copy(
            update={"extra": {"reasoning": {"effort": "max"}}}
        ),
    )
    config_path = make_temp_project(
        tmp_path,
        target_with_reasoning,
        judge_with_reasoning,
    )
    live_service = RunService(
        project_root=tmp_path,
        config_path=config_path,
        target_gateway=FakeGateway(target_with_reasoning),
        judge=FakeJudge(judge_with_reasoning),
    )
    live = await live_service.execute(mode=RunMode.LIVE)
    assert live.status == RunStatus.COMPLETED
    assert live.target_api_mode == "responses"
    assert live.judge_api_mode == "responses"
    assert live.target_streaming is False
    assert live.judge_streaming is False
    assert live.judge_target_identity_blinded is True
    assert live.judge_blind_policy_version == "target-identity-blind-v1"
    assert live.provider_storage_enabled is False
    assert live.target_reasoning_effort == "max"
    assert live.judge_reasoning_effort == "max"
    assert live.max_consecutive_runtime_errors == 3
    assert live.max_target_requests == 2
    assert live.max_judge_requests == 3
    live_result = live_service.store.load_results(live.run_id)[0]
    assert live_result.status.value == "PASS"

    replay_service = RunService(
        project_root=tmp_path,
        config_path=config_path,
    )
    replay = await replay_service.execute(
        mode=RunMode.DETERMINISTIC_ONLY,
        source_run_id=live.run_id,
    )
    assert replay.status == RunStatus.COMPLETED
    assert replay.replay_source_run_id == live.run_id
    assert replay.target_api_mode == "responses"
    assert replay.target_reasoning_effort == "max"
    assert replay.judge_target_identity_blinded is None
    assert replay.judge_blind_policy_version is None
    replay_output = replay_service.store.load_outputs(replay.run_id)[0]
    assert replay_output.source_run_id == live.run_id
    assert replay_output.output_hash == (
        live_service.store.load_outputs(live.run_id)[0].output_hash
    )


@pytest.mark.asyncio
async def test_live_run_persists_partial_output_as_runtime_error(
    tmp_path, resolved_target, resolved_judge
):
    config_path = make_temp_project(tmp_path, resolved_target, resolved_judge)
    service = RunService(
        project_root=tmp_path,
        config_path=config_path,
        target_gateway=IncompleteGateway(resolved_target),
        judge=FakeJudge(resolved_judge),
    )
    manifest = await service.execute(mode=RunMode.LIVE)
    output = service.store.load_outputs(manifest.run_id)[0]
    result = service.store.load_results(manifest.run_id)[0]

    assert output.content == "只生成了一半"
    assert output.generation_complete is False
    assert result.status.value == "RUNTIME_ERROR"
    assert result.runtime_issues[0].error_type == "IncompleteTargetResponse"


@pytest.mark.asyncio
async def test_run_stops_after_consecutive_runtime_errors(
    tmp_path, resolved_target, resolved_judge
):
    config_path = make_temp_project(tmp_path, resolved_target, resolved_judge)
    expand_temp_cases(tmp_path, 5)
    gateway = BrokenGateway(resolved_target)
    service = RunService(
        project_root=tmp_path,
        config_path=config_path,
        target_gateway=gateway,
        judge=FakeJudge(resolved_judge),
    )

    manifest = await service.execute(
        mode=RunMode.LIVE,
        max_consecutive_runtime_errors=2,
    )

    assert manifest.status == RunStatus.PARTIAL
    assert manifest.completed_count == 2
    assert manifest.stop_reason == RunStopReason.CONSECUTIVE_RUNTIME_ERRORS
    assert gateway.calls == 2


@pytest.mark.asyncio
async def test_run_stops_at_target_request_budget(
    tmp_path, resolved_target, resolved_judge
):
    config_path = make_temp_project(tmp_path, resolved_target, resolved_judge)
    expand_temp_cases(tmp_path, 5)
    service = RunService(
        project_root=tmp_path,
        config_path=config_path,
        target_gateway=TwoRequestGateway(resolved_target),
        judge=FakeJudge(resolved_judge),
    )

    manifest = await service.execute(
        mode=RunMode.LIVE,
        max_target_requests=2,
    )

    assert manifest.status == RunStatus.PARTIAL
    assert manifest.completed_count == 1
    assert manifest.stop_reason == RunStopReason.TARGET_REQUEST_BUDGET


@pytest.mark.asyncio
async def test_run_stops_at_judge_request_budget(
    tmp_path, resolved_target, resolved_judge
):
    config_path = make_temp_project(tmp_path, resolved_target, resolved_judge)
    expand_temp_cases(tmp_path, 5)
    service = RunService(
        project_root=tmp_path,
        config_path=config_path,
        target_gateway=FakeGateway(resolved_target),
        judge=TwoRequestJudge(resolved_judge),
    )

    manifest = await service.execute(
        mode=RunMode.LIVE,
        max_judge_requests=2,
    )

    assert manifest.status == RunStatus.PARTIAL
    assert manifest.completed_count == 1
    assert manifest.stop_reason == RunStopReason.JUDGE_REQUEST_BUDGET


@pytest.mark.asyncio
async def test_development_canary_does_not_unlock_unselected_holdout(
    tmp_path, resolved_target, resolved_judge
):
    config_path = make_temp_project(tmp_path, resolved_target, resolved_judge)
    path = tmp_path / "datasets" / "cases.jsonl"
    development = EvaluationCase.model_validate_json(path.read_text(encoding="utf-8"))
    holdout = development.model_copy(
        update={"case_id": "IG-902", "split": DataSplit.HOLDOUT}
    )
    path.write_text(
        development.model_dump_json() + "\n" + holdout.model_dump_json() + "\n",
        encoding="utf-8",
    )
    service = RunService(
        project_root=tmp_path,
        config_path=config_path,
        target_gateway=FakeGateway(resolved_target),
        judge=FakeJudge(resolved_judge),
    )

    manifest = await service.execute(
        mode=RunMode.LIVE,
        case_ids={"IG-901"},
    )

    assert manifest.status == RunStatus.COMPLETED
    assert "holdout explicitly unlocked" not in manifest.notes


@pytest.mark.asyncio
async def test_deterministic_only_accepts_imported_fixture(
    tmp_path, resolved_target, resolved_judge
):
    config_path = make_temp_project(tmp_path, resolved_target, resolved_judge)
    imported = ImportedOutput(
        case_id="IG-901",
        model_alias="model_a",
        model_name="fixture/not-real",
        prompt_id="v1",
        prompt_version="1",
        content="1. 建议一\n2. 建议二\n3. 建议三",
        fixture=True,
    )
    fixture_path = tmp_path / "fixture.jsonl"
    fixture_path.write_text(
        imported.model_dump_json() + "\n",
        encoding="utf-8",
    )
    service = RunService(
        project_root=tmp_path,
        config_path=config_path,
    )
    manifest = await service.execute(
        mode=RunMode.DETERMINISTIC_ONLY,
        outputs_file="fixture.jsonl",
    )
    assert manifest.status == RunStatus.COMPLETED
    assert "synthetic fixture outputs; not a real model run" in manifest.notes
    assert service.store.load_results(manifest.run_id)[0].status.value == "PASS"
    assert service.store.summarize(manifest.run_id).target_request_count == 0

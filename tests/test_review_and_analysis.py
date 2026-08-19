from __future__ import annotations

from llm_eval_workbench.analysis import compare_runs
from llm_eval_workbench.result_store import ResultStore
from llm_eval_workbench.review_service import (
    blind_case_view,
    holdout_alignment,
    submit_review,
)
from llm_eval_workbench.schemas import (
    CaseResult,
    CaseStatus,
    DataSplit,
    EvaluationCase,
    Language,
    ReviewDecision,
    RunManifest,
    RunMode,
    RunStatus,
    SourceInfo,
    TaskPack,
)


def make_manifest(run_id: str, generation_hash: str) -> RunManifest:
    return RunManifest(
        run_id=run_id,
        project_id="test",
        project_version="1",
        mode=RunMode.LIVE,
        status=RunStatus.RUNNING,
        target_model_alias="model",
        target_model_name="test/model",
        judge_model_alias="judge",
        judge_model_name="test/judge",
        prompt_id="v1",
        prompt_version="1",
        dataset_hash="d" * 64,
        config_hash="c" * 64,
        generation_config_hash=generation_hash,
        metric_config_hash="m" * 64,
        code_hash="s" * 64,
        case_count=1,
    )


def make_result(run_id: str, status: CaseStatus) -> CaseResult:
    return CaseResult(
        run_id=run_id,
        case_id="IG-999",
        task_pack=TaskPack.INSTRUCTION_GENERATION,
        status=status,
        evaluation_scope=RunMode.LIVE,
        coverage_complete=True,
        judge_score_mean=0.8 if status == CaseStatus.PASS else 0.5,
    )


def holdout_case() -> EvaluationCase:
    return EvaluationCase(
        case_id="IG-999",
        task_pack=TaskPack.INSTRUCTION_GENERATION,
        task_type="instruction_following",
        language=Language.CHINESE,
        title="holdout",
        input="test input",
        expected_output="hidden reference",
        rubric_id="R",
        rubric="hidden rubric",
        source=SourceInfo(
            type="synthetic",
            name="test",
            reference="test",
            license="CC0-1.0",
            design_reason="test",
        ),
        split=DataSplit.HOLDOUT,
        version="1",
    )


def test_compare_runs_detects_improvement(tmp_path):
    store = ResultStore(tmp_path / "runs")
    baseline_id = "20260730T000000Z-base1"
    candidate_id = "20260730T000001Z-cand1"
    store.create_run(make_manifest(baseline_id, "a" * 64))
    store.append_result(make_result(baseline_id, CaseStatus.REVIEW))
    store.finalize(baseline_id, expected_case_count=1)
    store.create_run(make_manifest(candidate_id, "b" * 64))
    store.append_result(make_result(candidate_id, CaseStatus.PASS))
    store.finalize(candidate_id, expected_case_count=1)
    comparison = compare_runs(store, baseline_id, candidate_id)
    assert comparison["category_counts"] == {"improved": 1}
    assert comparison["generation_changed"] is True


def test_blind_view_hides_reference_and_machine_scores():
    view = blind_case_view(case=holdout_case(), output_content="model output")
    assert "expected_output" not in view
    assert "rubric" not in view
    assert "machine_status" not in view
    assert view["model_output"] == "model output"


def test_holdout_review_alignment(tmp_path):
    store = ResultStore(tmp_path / "runs")
    run_id = "20260730T000000Z-review1"
    store.create_run(make_manifest(run_id, "a" * 64))
    store.append_result(make_result(run_id, CaseStatus.PASS))
    store.finalize(run_id, expected_case_count=1)
    case = holdout_case()
    submit_review(
        store=store,
        run_id=run_id,
        case=case,
        reviewer="candidate",
        decision=ReviewDecision.PASS,
        reason="符合约束",
        blind=True,
    )
    alignment = holdout_alignment(
        store=store,
        run_id=run_id,
        holdout_cases=[case],
    )
    assert alignment["complete"] is True
    assert alignment["agreement"] == 1.0

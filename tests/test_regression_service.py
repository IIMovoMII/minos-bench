from __future__ import annotations

import pytest

from llm_eval_workbench.dataset_service import load_jsonl
from llm_eval_workbench.regression_service import promote_case_to_regression
from llm_eval_workbench.result_store import ResultStore
from llm_eval_workbench.review_service import submit_review
from llm_eval_workbench.schemas import (
    BadCaseCategory,
    CaseResult,
    CaseStatus,
    DataSplit,
    ReviewDecision,
    RunManifest,
    RunMode,
    RunStatus,
)


def _manifest(run_id: str) -> RunManifest:
    return RunManifest(
        run_id=run_id,
        project_id="test",
        project_version="1",
        mode=RunMode.LIVE,
        status=RunStatus.COMPLETED,
        target_model_alias="model_a",
        target_model_name="test/model",
        prompt_id="v1",
        prompt_version="1",
        dataset_hash="d" * 64,
        config_hash="c" * 64,
        generation_config_hash="g" * 64,
        metric_config_hash="m" * 64,
        code_hash="s" * 64,
        case_count=1,
        completed_count=1,
    )


def test_human_confirmed_bad_case_creates_versioned_regression_snapshot(
    tmp_path,
    sample_case,
    sample_output,
):
    run_id = "20260730T000000Z-regression1"
    store = ResultStore(tmp_path / "runs")
    store.create_run(_manifest(run_id))
    output = sample_output.model_copy(update={"run_id": run_id})
    store.append_output(output)
    store.append_result(
        CaseResult(
            run_id=run_id,
            case_id=sample_case.case_id,
            task_pack=sample_case.task_pack,
            status=CaseStatus.REVIEW,
            evaluation_scope=RunMode.LIVE,
            coverage_complete=True,
            generated_output_hash=output.output_hash,
        )
    )
    review = submit_review(
        store=store,
        run_id=run_id,
        case=sample_case,
        reviewer="candidate",
        decision=ReviewDecision.FAIL,
        reason="遗漏明确约束",
        issue_categories=[BadCaseCategory.CONSTRAINT_OMISSION],
        blind=False,
    )

    result = promote_case_to_regression(
        regression_dir=tmp_path / "regression",
        store=store,
        run_id=run_id,
        case=sample_case,
        reason="防止相同约束遗漏复发",
    )
    snapshot = load_jsonl(result["snapshot_path"])
    assert result["version"] == 1
    assert result["case_count"] == 1
    assert snapshot[0].case_id == "RG-001"
    assert snapshot[0].split == DataSplit.REGRESSION
    origin = snapshot[0].metadata["regression_origin"]
    assert origin["source_case_id"] == sample_case.case_id
    assert origin["human_review_id"] == review.review_id
    assert origin["issue_categories"] == ["constraint_omission"]
    assert (tmp_path / "regression" / "current.jsonl").exists()

    with pytest.raises(ValueError, match="already"):
        promote_case_to_regression(
            regression_dir=tmp_path / "regression",
            store=store,
            run_id=run_id,
            case=sample_case,
            reason="duplicate",
        )


def test_regression_promotion_requires_human_fail(
    tmp_path,
    sample_case,
    sample_output,
):
    run_id = "20260730T000000Z-regression2"
    store = ResultStore(tmp_path / "runs")
    store.create_run(_manifest(run_id))
    store.append_output(sample_output.model_copy(update={"run_id": run_id}))
    store.append_result(
        CaseResult(
            run_id=run_id,
            case_id=sample_case.case_id,
            task_pack=sample_case.task_pack,
            status=CaseStatus.REVIEW,
            evaluation_scope=RunMode.LIVE,
            coverage_complete=True,
        )
    )
    with pytest.raises(ValueError, match="human FAIL"):
        promote_case_to_regression(
            regression_dir=tmp_path / "regression",
            store=store,
            run_id=run_id,
            case=sample_case,
            reason="not confirmed",
        )

from __future__ import annotations

from llm_eval_workbench.result_store import ResultStore
from llm_eval_workbench.schemas import (
    CaseResult,
    CaseStatus,
    RunManifest,
    RunMode,
    RunStatus,
)


def manifest(run_id: str, case_count: int = 1) -> RunManifest:
    return RunManifest(
        run_id=run_id,
        project_id="test",
        project_version="1",
        mode=RunMode.LIVE,
        status=RunStatus.RUNNING,
        target_model_alias="model_a",
        target_model_name="test/model",
        judge_model_alias="judge",
        judge_model_name="test/judge",
        prompt_id="v1",
        prompt_version="1",
        dataset_hash="d" * 64,
        config_hash="c" * 64,
        generation_config_hash="g" * 64,
        metric_config_hash="m" * 64,
        code_hash="s" * 64,
        case_count=case_count,
    )


def test_append_finalize_and_integrity(tmp_path, sample_output, sample_case):
    store = ResultStore(tmp_path / "runs")
    run_id = "20260730T000000Z-store1"
    store.create_run(manifest(run_id))
    output = sample_output.model_copy(update={"run_id": run_id})
    store.append_output(output)
    result = CaseResult(
        run_id=run_id,
        case_id=sample_case.case_id,
        task_pack=sample_case.task_pack,
        status=CaseStatus.PASS,
        evaluation_scope=RunMode.LIVE,
        coverage_complete=True,
        generated_output_hash=output.output_hash,
    )
    store.append_result(result)
    final = store.finalize(run_id, expected_case_count=1)
    assert final.status == RunStatus.COMPLETED
    assert store.summarize(run_id).status_counts == {"PASS": 1}
    assert (store.run_dir(run_id) / "integrity.json").exists()
    assert store.verify_integrity(run_id)["valid"] is True

    (store.run_dir(run_id) / "results.jsonl").write_text(
        "tampered",
        encoding="utf-8",
    )
    verification = store.verify_integrity(run_id)
    assert verification["valid"] is False
    assert verification["mismatched"][0]["path"] == "results.jsonl"


def test_partial_run_is_not_promoted_to_completed(tmp_path, sample_output, sample_case):
    store = ResultStore(tmp_path / "runs")
    run_id = "20260730T000000Z-partial1"
    store.create_run(manifest(run_id, case_count=2))
    output = sample_output.model_copy(update={"run_id": run_id})
    store.append_output(output)
    store.append_result(
        CaseResult(
            run_id=run_id,
            case_id=sample_case.case_id,
            task_pack=sample_case.task_pack,
            status=CaseStatus.PASS,
            evaluation_scope=RunMode.LIVE,
            coverage_complete=True,
            generated_output_hash=output.output_hash,
        )
    )
    final = store.finalize(run_id, expected_case_count=2)
    assert final.status == RunStatus.PARTIAL
    assert final.completed_count == 1


def test_persisted_files_do_not_contain_test_secret(tmp_path, sample_output):
    store = ResultStore(tmp_path / "runs")
    run_id = "20260730T000000Z-secret1"
    store.create_run(manifest(run_id))
    store.append_output(sample_output.model_copy(update={"run_id": run_id}))
    text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in store.run_dir(run_id).glob("*")
        if path.is_file()
    )
    assert "unit-test-secret" not in text

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

import pytest

from llm_eval_workbench.hashing import sha256_text
from llm_eval_workbench.scientific_data import load_target_comparison
from llm_eval_workbench.scientific_report import (
    append_blind_review_item,
    build_scientific_report,
    candidate_review_progress,
    create_blind_review_package,
)
from llm_eval_workbench.scientific_schemas import (
    AtomicDecision,
    AtomicJudgeEnvelope,
    AtomicJudgeItem,
    EvidenceSufficiency,
    HumanCriterionDecision,
    HumanCriterionReview,
    JudgeApplicability,
    MachineStatus,
    ScientificCase,
    ScientificCaseResult,
    ScientificOutput,
    Severity,
)
from llm_eval_workbench.scientific_store import ScientificExecutionStore

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "datasets" / "scientific_v1"


def _judge_envelope(
    case: ScientificCase,
    *,
    fail_all: bool = False,
    abstain_first: bool = False,
) -> AtomicJudgeEnvelope:
    values = []
    for index, criterion in enumerate(case.semantic_criteria):
        if fail_all:
            decision = AtomicDecision.FAIL
            sufficiency = EvidenceSufficiency.SUFFICIENT
        elif abstain_first and index == 0:
            decision = AtomicDecision.ABSTAIN
            sufficiency = EvidenceSufficiency.INSUFFICIENT
        else:
            decision = AtomicDecision.PASS
            sufficiency = EvidenceSufficiency.SUFFICIENT
        values.append(
            AtomicJudgeItem(
                criterion_id=criterion.criterion_id,
                applicability=JudgeApplicability.APPLICABLE,
                evidence_sufficiency=sufficiency,
                decision=decision,
                answer_evidence=[] if decision == AtomicDecision.ABSTAIN else ["OK"],
                source_evidence=[criterion.evidence[0]],
                reason="fixed report test",
            )
        )
    return AtomicJudgeEnvelope(criteria=values)


def _seed_four_pack_store(store: ScientificExecutionStore) -> list[ScientificCase]:
    by_pack: dict[str, list[ScientificCase]] = defaultdict(list)
    for case in load_target_comparison(DATA_DIR):
        if len(case.semantic_criteria) >= 2:
            by_pack[case.task_pack.value].append(case)
    selected = [
        by_pack[name][0]
        for name in (
            "instruction_generation",
            "grounded_qa",
            "multi_turn",
            "structured_tool",
        )
    ]
    for case in selected:
        content = f"fixture answer for {case.case_id}"
        output = ScientificOutput(
            case_id=case.case_id,
            content=content,
            output_hash=sha256_text(content),
        )
        store.write_node_once(
            f"target--model_a_prompt_v1--{case.case_id}",
            {
                "node_id": f"target--model_a_prompt_v1--{case.case_id}",
                "stage": "target_generation",
                "config_id": "model_a_prompt_v1",
                "case_id": case.case_id,
                "status": "completed",
                "output": output.model_dump(mode="json"),
            },
        )
        fail_pack = case.task_pack.value == "structured_tool"
        abstain_pack = case.task_pack.value == "instruction_generation"
        result = ScientificCaseResult(
            case_id=case.case_id,
            config_id="model_a_prompt_v1",
            task_pack=case.task_pack,
            machine_status=(
                MachineStatus.REVIEW
                if fail_pack or abstain_pack
                else MachineStatus.PASS
            ),
            judge_result=_judge_envelope(
                case,
                fail_all=fail_pack,
                abstain_first=abstain_pack,
            ),
            target_request_count=1,
            judge_request_count=1,
            output_hash=output.output_hash,
        )
        store.write_node_once(
            f"judge--model_a_prompt_v1--{case.case_id}",
            {
                "node_id": f"judge--model_a_prompt_v1--{case.case_id}",
                "stage": "judge_evaluation",
                "config_id": "model_a_prompt_v1",
                "case_id": case.case_id,
                "status": "completed",
                "result": result.model_dump(mode="json"),
            },
        )
    runtime_case = selected[0]
    runtime = ScientificCaseResult(
        case_id=runtime_case.case_id,
        config_id="model_b_prompt_v1",
        task_pack=runtime_case.task_pack,
        machine_status=MachineStatus.RUNTIME_ERROR,
        runtime_stage="judge_evaluation",
        runtime_error_type="AtomicJudgeParseError",
        runtime_error_message="judge_contract_runtime",
    )
    store.write_node_once(
        f"judge--model_b_prompt_v1--{runtime_case.case_id}",
        {
            "node_id": f"judge--model_b_prompt_v1--{runtime_case.case_id}",
            "stage": "judge_evaluation",
            "config_id": "model_b_prompt_v1",
            "case_id": runtime_case.case_id,
            "status": "runtime_error",
            "result": runtime.model_dump(mode="json"),
        },
    )
    return selected


def test_machine_report_uses_equal_pack_weighting_and_coverage(tmp_path: Path) -> None:
    store = ScientificExecutionStore(tmp_path / "runs", "report-machine-v1")
    _seed_four_pack_store(store)
    report = build_scientific_report(
        store=store,
        data_dir=DATA_DIR,
        confirmed=False,
    )
    summary = report["config_summaries"]["model_a_prompt_v1"]
    assert summary["reference_score"] == pytest.approx(75.0)
    assert len(summary["task_pack_scores"]) == 4
    assert report["judgment_coverage"] < 1.0
    runtime_row = next(
        item
        for item in report["items"]
        if item["machine_status"] == MachineStatus.RUNTIME_ERROR.value
    )
    assert runtime_row["reference_score"] is None
    assert report["machine_review_candidate_counts"]
    assert report["confirmed_error_counts"] == {}
    assert report["critical_error_blocks_release"] is False


def test_judge_authoritative_report_promotes_semantic_failures(
    tmp_path: Path,
) -> None:
    store = ScientificExecutionStore(tmp_path / "runs", "report-machine-final-v1")
    _seed_four_pack_store(store)
    report = build_scientific_report(
        store=store,
        data_dir=DATA_DIR,
        confirmed=False,
        judge_authoritative=True,
    )

    assert report["report_type"] == "machine_final"
    assert report["machine_review_candidate_counts"] == {}
    assert report["confirmed_error_counts"]


def test_confirmed_report_requires_complete_blind_review_and_is_append_only(
    tmp_path: Path,
) -> None:
    store = ScientificExecutionStore(tmp_path / "runs", "report-human-v1")
    cases = _seed_four_pack_store(store)
    create_blind_review_package(store=store, data_dir=DATA_DIR)
    assert candidate_review_progress(store) == {
        "expected": 4,
        "reviewed": 0,
        "pending": ["BR-001", "BR-002", "BR-003", "BR-004"],
        "complete": False,
    }
    with pytest.raises(RuntimeError, match="incomplete"):
        build_scientific_report(store=store, data_dir=DATA_DIR, confirmed=True)

    case_by_id = {item.case_id: item for item in cases}
    mapping = json.loads(
        (store.directory / "candidate_blind_review_mapping.json").read_text(
            encoding="utf-8"
        )
    )["items"]
    critical_written = False
    first_review: tuple[str, list[HumanCriterionReview]] | None = None
    for review_item_id, target in mapping.items():
        case = case_by_id[target["case_id"]]
        reviews = []
        for criterion in case.semantic_criteria:
            decision = HumanCriterionDecision.PASS
            if not critical_written and criterion.severity == Severity.CRITICAL:
                decision = HumanCriterionDecision.FAIL
                critical_written = True
            reviews.append(
                HumanCriterionReview(
                    criterion_id=criterion.criterion_id,
                    decision=decision,
                    reason="candidate fixture reason",
                )
            )
        append_blind_review_item(
            store=store,
            review_item_id=review_item_id,
            criteria=reviews,
        )
        if first_review is None:
            first_review = (review_item_id, reviews)
    assert critical_written is True
    assert candidate_review_progress(store)["complete"] is True
    report = build_scientific_report(
        store=store,
        data_dir=DATA_DIR,
        confirmed=True,
    )
    assert report["report_type"] == "candidate_confirmed"
    assert report["human_review_coverage"] == pytest.approx(0.04)
    assert report["confirmed_error_counts"][Severity.CRITICAL.value] == 1
    assert report["critical_error_blocks_release"] is True

    assert first_review is not None
    append_blind_review_item(
        store=store,
        review_item_id=first_review[0],
        criteria=first_review[1],
    )
    records = (
        store.directory / "candidate_reviews.jsonl"
    ).read_text(encoding="utf-8").splitlines()
    assert len(records) == 5

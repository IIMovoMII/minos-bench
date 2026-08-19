from __future__ import annotations

import uuid
from typing import Any

from .result_store import ResultStore
from .schemas import (
    BadCaseCategory,
    CaseStatus,
    DataSplit,
    EvaluationCase,
    HumanReview,
    ReviewDecision,
)


def blind_case_view(
    *,
    case: EvaluationCase,
    output_content: str,
) -> dict[str, Any]:
    if case.split != DataSplit.HOLDOUT:
        raise ValueError("Blind review is reserved for holdout cases")
    return {
        "case_id": case.case_id,
        "task_pack": case.task_pack.value,
        "task_type": case.task_type,
        "language": case.language.value,
        "title": case.title,
        "input": case.input,
        "context": case.context,
        "turns": [
            turn.model_dump(mode="json", exclude_none=True) for turn in case.turns
        ],
        "available_tools": case.available_tools,
        "model_output": output_content,
    }


def submit_review(
    *,
    store: ResultStore,
    run_id: str,
    case: EvaluationCase,
    reviewer: str,
    decision: ReviewDecision,
    reason: str,
    issue_categories: list[BadCaseCategory] | None = None,
    root_cause_hypothesis: str | None = None,
    improvement_suggestion: str | None = None,
    blind: bool = True,
) -> HumanReview:
    if blind and case.split != DataSplit.HOLDOUT:
        raise ValueError("Blind reviews require a holdout case")
    result = store.result_by_case(run_id).get(case.case_id)
    if result is None:
        raise LookupError(f"No machine result for {case.case_id}")
    review = HumanReview(
        review_id=str(uuid.uuid4()),
        run_id=run_id,
        case_id=case.case_id,
        reviewer=reviewer,
        decision=decision,
        reason=reason,
        issue_categories=issue_categories or [],
        root_cause_hypothesis=root_cause_hypothesis,
        improvement_suggestion=improvement_suggestion,
        blind=blind,
        machine_status_before_review=result.status,
    )
    store.append_review(review)
    store.write_integrity(run_id)
    return review


def latest_reviews(store: ResultStore, run_id: str) -> dict[str, HumanReview]:
    latest: dict[str, HumanReview] = {}
    for review in store.load_reviews(run_id):
        previous = latest.get(review.case_id)
        if previous is None or review.created_at >= previous.created_at:
            latest[review.case_id] = review
    return latest


def holdout_alignment(
    *,
    store: ResultStore,
    run_id: str,
    holdout_cases: list[EvaluationCase],
) -> dict[str, Any]:
    expected_ids = {
        case.case_id for case in holdout_cases if case.split == DataSplit.HOLDOUT
    }
    results = store.result_by_case(run_id)
    reviews = latest_reviews(store, run_id)
    reviewed_ids = expected_ids & set(reviews)
    missing_ids = sorted(expected_ids - reviewed_ids)
    comparisons: list[dict[str, Any]] = []
    matches = 0

    for case_id in sorted(reviewed_ids):
        machine = results.get(case_id)
        review = reviews[case_id]
        if machine is None or machine.status == CaseStatus.RUNTIME_ERROR:
            machine_decision = "RUNTIME_ERROR"
            matched = False
        elif machine.status == CaseStatus.PASS:
            machine_decision = ReviewDecision.PASS.value
            matched = review.decision == ReviewDecision.PASS
        elif machine.status == CaseStatus.FAIL:
            machine_decision = ReviewDecision.FAIL.value
            matched = review.decision == ReviewDecision.FAIL
        else:
            machine_decision = ReviewDecision.NEEDS_MORE_EVIDENCE.value
            matched = review.decision == ReviewDecision.NEEDS_MORE_EVIDENCE
        matches += int(matched)
        comparisons.append(
            {
                "case_id": case_id,
                "machine_decision": machine_decision,
                "human_decision": review.decision.value,
                "match": matched,
            }
        )

    complete = len(reviewed_ids) == len(expected_ids) and bool(expected_ids)
    return {
        "complete": complete,
        "expected_count": len(expected_ids),
        "reviewed_count": len(reviewed_ids),
        "missing_case_ids": missing_ids,
        "agreement": (matches / len(reviewed_ids) if reviewed_ids else None),
        "agreement_definition": (
            "three-state workflow agreement: PASS, FAIL, "
            "or NEEDS_MORE_EVIDENCE; runtime errors never count as matches"
        ),
        "comparisons": comparisons,
    }

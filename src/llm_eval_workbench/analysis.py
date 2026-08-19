from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from .result_store import ResultStore
from .schemas import CaseResult, CaseStatus

STATUS_RANK = {
    CaseStatus.FAIL: 0,
    CaseStatus.REVIEW: 1,
    CaseStatus.PASS: 2,
}


def compare_runs(
    store: ResultStore,
    baseline_run_id: str,
    candidate_run_id: str,
) -> dict[str, Any]:
    baseline_manifest = store.load_manifest(baseline_run_id)
    candidate_manifest = store.load_manifest(candidate_run_id)
    if baseline_manifest.dataset_hash != candidate_manifest.dataset_hash:
        raise ValueError("Runs use different dataset hashes")

    metric_compatible = (
        baseline_manifest.metric_config_hash == candidate_manifest.metric_config_hash
    )
    baseline = store.result_by_case(baseline_run_id)
    candidate = store.result_by_case(candidate_run_id)
    case_ids = sorted(set(baseline) | set(candidate))
    rows: list[dict[str, Any]] = []
    categories: Counter[str] = Counter()
    per_pack: dict[str, Counter[str]] = defaultdict(Counter)

    for case_id in case_ids:
        left = baseline.get(case_id)
        right = candidate.get(case_id)
        category = _comparison_category(left, right)
        categories[category] += 1
        task_pack = (
            right.task_pack.value
            if right is not None
            else left.task_pack.value
            if left is not None
            else "unknown"
        )
        per_pack[task_pack][category] += 1
        score_delta = None
        if (
            metric_compatible
            and left is not None
            and right is not None
            and left.judge_score_mean is not None
            and right.judge_score_mean is not None
        ):
            score_delta = right.judge_score_mean - left.judge_score_mean
        rows.append(
            {
                "case_id": case_id,
                "task_pack": task_pack,
                "baseline_status": left.status.value if left else None,
                "candidate_status": right.status.value if right else None,
                "category": category,
                "baseline_judge_score": (left.judge_score_mean if left else None),
                "candidate_judge_score": (right.judge_score_mean if right else None),
                "judge_score_delta": score_delta,
            }
        )

    return {
        "baseline_run_id": baseline_run_id,
        "candidate_run_id": candidate_run_id,
        "dataset_hash": baseline_manifest.dataset_hash,
        "metric_compatible": metric_compatible,
        "metric_warning": (
            None
            if metric_compatible
            else "Metric config hashes differ; score deltas are suppressed."
        ),
        "generation_changed": (
            baseline_manifest.generation_config_hash
            != candidate_manifest.generation_config_hash
        ),
        "category_counts": dict(sorted(categories.items())),
        "task_pack_counts": {
            key: dict(sorted(value.items())) for key, value in sorted(per_pack.items())
        },
        "cases": rows,
    }


def _comparison_category(
    baseline: CaseResult | None, candidate: CaseResult | None
) -> str:
    if baseline is None or candidate is None:
        return "not_comparable"
    if (
        baseline.status == CaseStatus.RUNTIME_ERROR
        or candidate.status == CaseStatus.RUNTIME_ERROR
    ):
        return "not_comparable"
    left_rank = STATUS_RANK[baseline.status]
    right_rank = STATUS_RANK[candidate.status]
    if right_rank > left_rank:
        return "improved"
    if right_rank < left_rank:
        return "regressed"
    return "unchanged"

from __future__ import annotations

import json
import uuid
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean
from typing import Any

from .hashing import sha256_file, sha256_value
from .scientific_data import load_target_comparison
from .scientific_schemas import (
    AtomicDecision,
    HumanCriterionDecision,
    HumanCriterionReview,
    JudgeApplicability,
    JudgmentAuthority,
    MachineStatus,
    ScientificCase,
    ScientificCaseResult,
    ScientificHumanReview,
    Severity,
)
from .scientific_store import ScientificExecutionStore, append_jsonl, atomic_write_json


def _load_results(store: ScientificExecutionStore) -> list[ScientificCaseResult]:
    results: list[ScientificCaseResult] = []
    for node in store.all_node_artifacts():
        if node.get("stage") != "judge_evaluation" or "result" not in node:
            continue
        results.append(ScientificCaseResult.model_validate(node["result"]))
    return sorted(results, key=lambda item: (item.config_id, item.case_id))


def _load_outputs(
    store: ScientificExecutionStore,
) -> dict[tuple[str, str], dict[str, Any]]:
    outputs: dict[tuple[str, str], dict[str, Any]] = {}
    for node in store.all_node_artifacts():
        if node.get("stage") != "target_generation" or "output" not in node:
            continue
        outputs[(str(node["config_id"]), str(node["case_id"]))] = node["output"]
    return outputs


def _load_reviews(path: Path) -> list[ScientificHumanReview]:
    if not path.exists():
        return []
    values: list[ScientificHumanReview] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, raw in enumerate(handle, start=1):
            line = raw.strip()
            if not line:
                continue
            try:
                values.append(ScientificHumanReview.model_validate_json(line))
            except Exception as error:
                raise ValueError(
                    f"reviews.jsonl:{line_number}: invalid review"
                ) from error
    return values


def _latest_reviews(path: Path) -> dict[tuple[str, str], ScientificHumanReview]:
    latest: dict[tuple[str, str], ScientificHumanReview] = {}
    for review in _load_reviews(path):
        key = (review.config_id, review.case_id)
        previous = latest.get(key)
        if previous is None or review.created_at >= previous.created_at:
            latest[key] = review
    return latest


def candidate_review_progress(store: ScientificExecutionStore) -> dict[str, Any]:
    package_path = store.directory / "candidate_blind_review_package.json"
    if not package_path.is_file():
        raise FileNotFoundError("candidate blind review package does not exist")
    package = json.loads(package_path.read_text(encoding="utf-8"))
    expected_ids = {
        str(item["review_item_id"]) for item in package.get("items", [])
    }
    reviews = _load_reviews(store.directory / "candidate_reviews.jsonl")
    reviewed_ids = {item.review_item_id for item in reviews}
    unknown = reviewed_ids - expected_ids
    if unknown:
        raise ValueError("candidate reviews contain unknown blind review items")
    pending = sorted(expected_ids - reviewed_ids)
    return {
        "expected": len(expected_ids),
        "reviewed": len(expected_ids & reviewed_ids),
        "pending": pending,
        "complete": bool(expected_ids) and not pending,
    }


def require_complete_candidate_review(store: ScientificExecutionStore) -> None:
    progress = candidate_review_progress(store)
    if not progress["complete"]:
        raise RuntimeError(
            "candidate blind review is incomplete: "
            f"{progress['reviewed']}/{progress['expected']}"
        )


def _case_score(
    case: ScientificCase,
    result: ScientificCaseResult,
    human_review: ScientificHumanReview | None,
    *,
    judge_authoritative: bool = False,
) -> dict[str, Any]:
    if result.machine_status == MachineStatus.RUNTIME_ERROR:
        return {
            "score": None,
            "decided": 0,
            "applicable": 0,
            "confirmed_errors": [],
            "machine_review_candidates": [],
        }
    values: list[int] = []
    applicable = 0
    confirmed_errors: list[dict[str, str]] = []
    review_candidates: list[dict[str, str]] = []
    direct_severity = {item.criterion_id: item.severity for item in case.direct_checks}
    for item in result.direct_results:
        if item.authority != JudgmentAuthority.DIRECT_VERIFIER:
            continue
        applicable += 1
        values.append(1 if item.passed else 0)
        if not item.passed:
            confirmed_errors.append(
                {"criterion_id": item.criterion_id, "severity": item.severity.value}
            )
    del direct_severity

    human_by_id = (
        {item.criterion_id: item for item in human_review.criteria}
        if human_review is not None
        else {}
    )
    semantic_by_id = {item.criterion_id: item for item in case.semantic_criteria}
    if human_review is not None:
        for criterion_id, definition in semantic_by_id.items():
            review = human_by_id.get(criterion_id)
            if (
                review is None
                or review.decision == HumanCriterionDecision.NOT_APPLICABLE
            ):
                continue
            applicable += 1
            if review.decision == HumanCriterionDecision.PASS:
                values.append(1)
            elif review.decision == HumanCriterionDecision.FAIL:
                values.append(0)
                confirmed_errors.append(
                    {
                        "criterion_id": criterion_id,
                        "severity": definition.severity.value,
                    }
                )
    elif result.judge_result is not None:
        for item in result.judge_result.criteria:
            if item.applicability != JudgeApplicability.APPLICABLE:
                continue
            applicable += 1
            if item.decision == AtomicDecision.PASS:
                values.append(1)
            elif item.decision == AtomicDecision.FAIL:
                values.append(0)
                definition = semantic_by_id[item.criterion_id]
                error = {
                    "criterion_id": item.criterion_id,
                    "severity": definition.severity.value,
                }
                if judge_authoritative:
                    confirmed_errors.append(error)
                else:
                    review_candidates.append(error)
    return {
        "score": mean(values) if values else None,
        "decided": len(values),
        "applicable": applicable,
        "confirmed_errors": confirmed_errors,
        "machine_review_candidates": review_candidates,
    }


def _comparison(
    item_scores: dict[tuple[str, str], float | None],
    baseline: str,
    candidate: str,
    case_ids: list[str],
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    for case_id in case_ids:
        left = item_scores.get((baseline, case_id))
        right = item_scores.get((candidate, case_id))
        if left is None or right is None:
            category = "not_comparable"
        elif right > left:
            category = "fixed"
        elif right < left:
            category = "regressed"
        else:
            category = "tied"
        counts[category] += 1
        rows.append(
            {
                "case_id": case_id,
                "baseline_score": left,
                "candidate_score": right,
                "category": category,
            }
        )
    return {
        "baseline_config": baseline,
        "candidate_config": candidate,
        "counts": dict(sorted(counts.items())),
        "cases": rows,
    }


def build_scientific_report(
    *,
    store: ScientificExecutionStore,
    data_dir: str | Path,
    confirmed: bool,
    judge_authoritative: bool = False,
) -> dict[str, Any]:
    if confirmed and judge_authoritative:
        raise ValueError("human-confirmed and Judge-authoritative modes conflict")
    if confirmed:
        require_complete_candidate_review(store)
    cases = {item.case_id: item for item in load_target_comparison(data_dir)}
    results = _load_results(store)
    review_path = store.directory / "candidate_reviews.jsonl"
    reviews = _latest_reviews(review_path) if confirmed else {}
    item_rows: list[dict[str, Any]] = []
    item_scores: dict[tuple[str, str], float | None] = {}
    pack_scores: dict[str, dict[str, list[float]]] = defaultdict(
        lambda: defaultdict(list)
    )
    risk_scores: dict[str, dict[str, list[float]]] = defaultdict(
        lambda: defaultdict(list)
    )
    difficulty_scores: dict[str, dict[str, list[float]]] = defaultdict(
        lambda: defaultdict(list)
    )
    total_decided = 0
    total_applicable = 0
    confirmed_errors: Counter[str] = Counter()
    config_confirmed_errors: dict[str, Counter[str]] = defaultdict(Counter)
    review_candidates: Counter[str] = Counter()
    config_status_counts: dict[str, Counter[str]] = defaultdict(Counter)
    valid_results = 0
    reviewed_items = 0
    for result in results:
        case = cases[result.case_id]
        review = reviews.get((result.config_id, result.case_id))
        if review is not None:
            reviewed_items += 1
        scored = _case_score(
            case,
            result,
            review,
            judge_authoritative=judge_authoritative,
        )
        score = scored["score"]
        item_scores[(result.config_id, result.case_id)] = score
        if score is not None:
            pack_scores[result.config_id][case.task_pack.value].append(score)
            if case.risk_cell:
                risk_scores[result.config_id][str(case.risk_cell)].append(score)
            if case.difficulty:
                difficulty_scores[result.config_id][str(case.difficulty)].append(score)
        if result.machine_status != MachineStatus.RUNTIME_ERROR:
            valid_results += 1
        total_decided += scored["decided"]
        total_applicable += scored["applicable"]
        for error in scored["confirmed_errors"]:
            confirmed_errors[error["severity"]] += 1
            config_confirmed_errors[result.config_id][error["severity"]] += 1
        for error in scored["machine_review_candidates"]:
            review_candidates[error["severity"]] += 1
        config_status_counts[result.config_id][result.machine_status.value] += 1
        item_rows.append(
            {
                "config_id": result.config_id,
                "case_id": result.case_id,
                "task_pack": case.task_pack.value,
                "risk_cell": case.risk_cell,
                "difficulty": case.difficulty,
                "machine_status": result.machine_status.value,
                "reference_score": score,
                "judged_criteria": scored["decided"],
                "applicable_criteria": scored["applicable"],
                "human_reviewed": review is not None,
                "runtime_stage": result.runtime_stage,
                "runtime_error_type": result.runtime_error_type,
            }
        )
    config_summaries: dict[str, Any] = {}
    for config_id, per_pack in sorted(pack_scores.items()):
        pack_values = {
            pack: mean(values) * 100 for pack, values in sorted(per_pack.items())
        }
        overall = mean(pack_values.values()) if len(pack_values) == 4 else None
        config_summaries[config_id] = {
            "reference_score": overall,
            "task_pack_scores": pack_values,
            "risk_cell_scores": {
                risk: mean(values) * 100
                for risk, values in sorted(risk_scores[config_id].items())
            },
            "difficulty_scores": {
                difficulty: mean(values) * 100
                for difficulty, values in sorted(
                    difficulty_scores[config_id].items()
                )
            },
            "status_counts": dict(sorted(config_status_counts[config_id].items())),
            "confirmed_error_counts": dict(
                sorted(config_confirmed_errors[config_id].items())
            ),
            "critical_error_blocks_release": (
                config_confirmed_errors[config_id][Severity.CRITICAL.value] > 0
            ),
        }
    expected_items = len(cases) * 4
    case_ids = sorted(cases)
    if confirmed:
        report_type = "candidate_confirmed"
    elif judge_authoritative:
        report_type = "machine_final"
    else:
        report_type = "machine_preliminary"
    interpretation_boundary = [
        "Each final configuration has one retained output per question; provider "
        "attempts that produced no usable output are recorded separately.",
        "ABSTAIN is excluded from score and lowers judgment coverage.",
        "Runtime errors are not content zeros.",
        "Task packs are equally weighted because this POC has no "
        "production traffic weights.",
        "Data is public or synthetic; one candidate reference is not expert gold.",
    ]
    if judge_authoritative:
        interpretation_boundary.extend(
            [
                "The candidate explicitly waived manual blind review for this "
                "low-stakes POC; deterministic checks and the calibrated Judge "
                "form the final project evaluation.",
                "A Judge contract retry is allowed only when no parseable decision "
                "was obtained; a valid PASS or FAIL is never re-judged.",
                "This machine-final report is a reproducible POC conclusion, not "
                "objective ground truth or a production release decision.",
            ]
        )
    else:
        interpretation_boundary.extend(
            [
                "A total score cannot offset a candidate-confirmed critical error.",
                "No repeated stability experiment or second Judge was run.",
            ]
        )
    report = {
        "report_version": "scientific-report-v1",
        "report_type": report_type,
        "execution_id": store.directory.name,
        "generated_at": datetime.now(UTC).isoformat(),
        "completion_rate": valid_results / expected_items if expected_items else None,
        "judgment_coverage": (
            total_decided / total_applicable if total_applicable else None
        ),
        "human_review_coverage": (
            reviewed_items / expected_items if expected_items else None
        ),
        "confirmed_error_counts": dict(sorted(confirmed_errors.items())),
        "machine_review_candidate_counts": dict(sorted(review_candidates.items())),
        "critical_error_blocks_release": confirmed_errors[Severity.CRITICAL.value] > 0,
        "config_summaries": config_summaries,
        "comparisons": {
            "model_a_vs_model_b": _comparison(
                item_scores,
                "model_a_prompt_v1",
                "model_b_prompt_v1",
                case_ids,
            ),
            "weak_prompt_v1_vs_v2": _comparison(
                item_scores,
                "weak_prompt_v1",
                "weak_prompt_v2",
                case_ids,
            ),
        },
        "items": item_rows,
        "interpretation_boundary": interpretation_boundary,
    }
    return report


def build_machine_final_report(
    *,
    store: ScientificExecutionStore,
    data_dir: str | Path,
    minimum_judge_validation_agreement: float = 0.85,
    require_judge_validation: bool = True,
    judge_validation_reference: str | None = None,
) -> dict[str, Any]:
    cases = load_target_comparison(data_dir)
    results = _load_results(store)
    expected_items = len(cases) * 4
    if len(results) != expected_items:
        raise RuntimeError(
            f"machine-final result coverage incomplete: {len(results)}/{expected_items}"
        )
    runtime_errors = [
        item for item in results if item.machine_status == MachineStatus.RUNTIME_ERROR
    ]
    if runtime_errors:
        raise RuntimeError(
            f"machine-final report blocked by {len(runtime_errors)} runtime errors"
        )

    validation = judge_validation_report(store)
    validation_items = validation["items"]
    validation_runtime_errors = [
        item for item in validation_items if item.get("runtime_error")
    ]
    if validation_runtime_errors:
        raise RuntimeError(
            "machine-final report blocked by Judge-validation runtime errors"
        )
    agreement = validation.get("mean_item_agreement_supplemental")
    if require_judge_validation and (
        agreement is None or agreement < minimum_judge_validation_agreement
    ):
        raise RuntimeError(
            "machine-final report blocked by insufficient Judge-validation agreement"
        )

    report = build_scientific_report(
        store=store,
        data_dir=data_dir,
        confirmed=False,
        judge_authoritative=True,
    )
    report["machine_authority_policy"] = {
        "policy_version": "candidate-waived-human-review-v1",
        "candidate_waiver_date": "2026-08-04",
        "deterministic_checks_authoritative": True,
        "semantic_judge_authoritative": True,
        "human_blind_review_required": False,
        "runtime_errors_score_as_zero": False,
        "judge_validation_required_this_run": require_judge_validation,
        "judge_validation_reference": judge_validation_reference,
    }
    report["judge_validation_summary"] = {
        "completed_items": len(validation_items),
        "runtime_errors": len(validation_runtime_errors),
        "mean_item_agreement_supplemental": agreement,
        "minimum_required": minimum_judge_validation_agreement,
        "reference_authority": validation["reference_authority"],
        "required_this_run": require_judge_validation,
        "status": (
            "completed"
            if require_judge_validation
            else "reused_prior_engine_acceptance"
        ),
        "reference_version": judge_validation_reference,
    }
    return report


def judge_validation_report(store: ScientificExecutionStore) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    matches = 0
    decided = 0
    target_counts: dict[str, Counter[str]] = defaultdict(Counter)
    for node in store.all_node_artifacts():
        if node.get("stage") != "judge_validation":
            continue
        comparison = node.get("comparison")
        if not isinstance(comparison, dict):
            items.append(
                {
                    "response_id": node.get("probe_id"),
                    "runtime_error": node.get("error", {}).get("error_type"),
                }
            )
            continue
        item_match = bool(comparison.get("all_criteria_match"))
        matches += int(item_match)
        decided += 1
        for target in comparison.get("validation_targets", []):
            target_counts[str(target)]["match" if item_match else "mismatch"] += 1
        items.append(comparison)
    return {
        "reference_authority": "candidate_reference_v1_not_expert_gold",
        "mean_item_agreement_supplemental": matches / decided if decided else None,
        "agreement_is_not_a_100_percent_gate": True,
        "failure_taxonomy": {
            "contract_or_code": "must be fixed before formal use",
            "prompt_or_model_limitation": (
                "record and route to human; do not endlessly tune"
            ),
        },
        "confusion_analysis": {
            key: dict(sorted(value.items()))
            for key, value in sorted(target_counts.items())
        },
        "items": items,
    }


def write_machine_reports(
    *,
    store: ScientificExecutionStore,
    data_dir: str | Path,
) -> dict[str, Path]:
    report = build_scientific_report(store=store, data_dir=data_dir, confirmed=False)
    report_path = store.directory / "machine_preliminary_report.json"
    validation_path = store.directory / "judge_validation_report.json"
    atomic_write_json(report_path, report)
    atomic_write_json(validation_path, judge_validation_report(store))
    return {"machine": report_path, "judge_validation": validation_path}


def write_machine_final_report(
    *,
    store: ScientificExecutionStore,
    data_dir: str | Path,
    require_judge_validation: bool = True,
    judge_validation_reference: str | None = None,
) -> Path:
    report = build_machine_final_report(
        store=store,
        data_dir=data_dir,
        require_judge_validation=require_judge_validation,
        judge_validation_reference=judge_validation_reference,
    )
    path = store.directory / "machine_final_report.json"
    atomic_write_json(path, report)
    return path


def _assert_blind_package(value: Any) -> None:
    forbidden_keys = {
        "config_id",
        "model",
        "model_name",
        "model_alias",
        "prompt_id",
        "prompt_version",
        "judge_result",
        "machine_status",
    }
    if isinstance(value, dict):
        exposed = forbidden_keys & set(value)
        if exposed:
            raise ValueError(
                f"blind package exposes forbidden identity/result keys: {exposed}"
            )
        for item in value.values():
            _assert_blind_package(item)
    elif isinstance(value, list):
        for item in value:
            _assert_blind_package(item)


def create_blind_review_package(
    *,
    store: ScientificExecutionStore,
    data_dir: str | Path,
) -> dict[str, Path]:
    cases = {item.case_id: item for item in load_target_comparison(data_dir)}
    outputs = _load_outputs(store)
    candidates: list[tuple[str, str, str, dict[str, Any]]] = []
    for (config_id, case_id), output in outputs.items():
        review_hash = sha256_value(
            {
                "execution_id": store.directory.name,
                "config_id": config_id,
                "case_id": case_id,
                "output_hash": output["output_hash"],
            }
        )
        candidates.append((review_hash, config_id, case_id, output))
    candidates.sort(key=lambda item: item[0])
    package_items: list[dict[str, Any]] = []
    mapping: dict[str, Any] = {}
    template_items: list[dict[str, Any]] = []
    for index, (_, config_id, case_id, output) in enumerate(candidates, start=1):
        review_item_id = f"BR-{index:03d}"
        case = cases[case_id]
        package_items.append(
            {
                "review_item_id": review_item_id,
                "task_pack": case.task_pack.value,
                "capability": case.capability,
                "user_goal": case.user_goal,
                "input": case.input,
                "context": case.context,
                "turns": [turn.model_dump(mode="json") for turn in case.turns],
                "available_tools": case.available_tools,
                "tool_outputs": case.tool_outputs,
                "candidate_answer": {
                    "content": output["content"],
                    "tool_calls": output["tool_calls"],
                    "environment_state": output["environment_state"],
                },
                "direct_contracts": [
                    {
                        "criterion_id": item.criterion_id,
                        "description": item.description,
                        "authority": item.authority.value,
                        "severity": item.severity.value,
                        "applicability": item.applicability,
                    }
                    for item in case.direct_checks
                ],
                "semantic_criteria": [
                    item.model_dump(mode="json") for item in case.semantic_criteria
                ],
            }
        )
        mapping[review_item_id] = {
            "config_id": config_id,
            "case_id": case_id,
            "semantic_criterion_ids": [
                item.criterion_id for item in case.semantic_criteria
            ],
        }
        template_items.append(
            {
                "review_item_id": review_item_id,
                "criteria": [
                    {"criterion_id": item.criterion_id, "decision": "", "reason": ""}
                    for item in case.semantic_criteria
                ],
            }
        )
    package = {
        "package_version": "candidate-blind-review-v1",
        "execution_id": store.directory.name,
        "identity_hidden": True,
        "judge_results_hidden": True,
        "item_count": len(package_items),
        "items": package_items,
    }
    _assert_blind_package(package)
    package_path = store.directory / "candidate_blind_review_package.json"
    mapping_path = store.directory / "candidate_blind_review_mapping.json"
    template_path = store.directory / "candidate_blind_review_submission.json"
    atomic_write_json(package_path, package)
    atomic_write_json(
        mapping_path,
        {
            "mapping_version": "candidate-blind-review-mapping-v1",
            "execution_id": store.directory.name,
            "package_sha256": sha256_value(package),
            "items": mapping,
        },
    )
    atomic_write_json(
        template_path,
        {
            "submission_version": "candidate-blind-review-submission-v1",
            "execution_id": store.directory.name,
            "package_sha256": sha256_file(package_path),
            "items": template_items,
        },
    )
    return {
        "package": package_path,
        "mapping": mapping_path,
        "submission": template_path,
    }


def submit_blind_reviews(
    *,
    store: ScientificExecutionStore,
    submission_path: str | Path,
) -> list[ScientificHumanReview]:
    mapping_payload = json.loads(
        (store.directory / "candidate_blind_review_mapping.json").read_text(
            encoding="utf-8"
        )
    )
    submission = json.loads(Path(submission_path).read_text(encoding="utf-8"))
    if submission.get("execution_id") != store.directory.name:
        raise ValueError("blind review execution ID mismatch")
    mapping = mapping_payload["items"]
    reviews: list[ScientificHumanReview] = []
    for item in submission.get("items", []):
        review_item_id = str(item.get("review_item_id", ""))
        mapped = mapping.get(review_item_id)
        if mapped is None:
            raise ValueError(f"unknown blind review item: {review_item_id}")
        criteria = [
            HumanCriterionReview.model_validate(value)
            for value in item.get("criteria", [])
        ]
        expected_ids = set(mapped["semantic_criterion_ids"])
        actual_ids = {value.criterion_id for value in criteria}
        if actual_ids != expected_ids or len(criteria) != len(expected_ids):
            raise ValueError(f"criterion set mismatch for {review_item_id}")
        review = ScientificHumanReview(
            review_id=str(uuid.uuid4()),
            execution_id=store.directory.name,
            review_item_id=review_item_id,
            case_id=mapped["case_id"],
            config_id=mapped["config_id"],
            criteria=criteria,
            created_at=datetime.now(UTC),
        )
        append_jsonl(
            store.directory / "candidate_reviews.jsonl", review.model_dump(mode="json")
        )
        reviews.append(review)
    return reviews


def append_blind_review_item(
    *,
    store: ScientificExecutionStore,
    review_item_id: str,
    criteria: list[HumanCriterionReview],
) -> ScientificHumanReview:
    mapping_payload = json.loads(
        (store.directory / "candidate_blind_review_mapping.json").read_text(
            encoding="utf-8"
        )
    )
    mapped = mapping_payload["items"].get(review_item_id)
    if mapped is None:
        raise ValueError(f"unknown blind review item: {review_item_id}")
    expected_ids = set(mapped["semantic_criterion_ids"])
    actual_ids = {value.criterion_id for value in criteria}
    if actual_ids != expected_ids or len(criteria) != len(expected_ids):
        raise ValueError(f"criterion set mismatch for {review_item_id}")
    review = ScientificHumanReview(
        review_id=str(uuid.uuid4()),
        execution_id=store.directory.name,
        review_item_id=review_item_id,
        case_id=mapped["case_id"],
        config_id=mapped["config_id"],
        criteria=criteria,
        created_at=datetime.now(UTC),
    )
    append_jsonl(
        store.directory / "candidate_reviews.jsonl",
        review.model_dump(mode="json"),
    )
    return review

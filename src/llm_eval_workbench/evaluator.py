from __future__ import annotations

from statistics import mean
from typing import Protocol

from .metrics.deepeval_metrics import JudgeRun
from .metrics.deterministic import run_deterministic_checks
from .schemas import (
    CaseResult,
    CaseStatus,
    EvaluationCase,
    GeneratedOutput,
    JudgeConfig,
    JudgeScoreBand,
    RunMode,
    RuntimeIssue,
)
from .secrets import safe_exception_details


class JudgeProtocol(Protocol):
    def evaluate(self, case: EvaluationCase, output: GeneratedOutput) -> JudgeRun: ...


def evaluate_case(
    *,
    run_id: str,
    case: EvaluationCase,
    output: GeneratedOutput,
    mode: RunMode,
    judge_config: JudgeConfig,
    judge: JudgeProtocol | None,
) -> CaseResult:
    issues: list[RuntimeIssue] = []
    if not output.generation_complete:
        status = output.provider_response_status or "missing"
        reason = output.provider_incomplete_reason or "unknown"
        incomplete_message = (
            f"IncompleteTargetResponse(status={status}, reason={reason})"
        )
        return CaseResult(
            run_id=run_id,
            case_id=case.case_id,
            task_pack=case.task_pack,
            status=CaseStatus.RUNTIME_ERROR,
            evaluation_scope=mode,
            coverage_complete=False,
            generated_output_hash=output.output_hash,
            runtime_issues=[
                RuntimeIssue(
                    stage="target_generation",
                    error_type="IncompleteTargetResponse",
                    message=incomplete_message,
                    retryable=True,
                )
            ],
        )
    try:
        deterministic_results = run_deterministic_checks(case, output)
    except Exception as error:
        error_type, safe_message = safe_exception_details(error)
        return CaseResult(
            run_id=run_id,
            case_id=case.case_id,
            task_pack=case.task_pack,
            status=CaseStatus.RUNTIME_ERROR,
            evaluation_scope=mode,
            coverage_complete=False,
            generated_output_hash=output.output_hash,
            runtime_issues=[
                RuntimeIssue(
                    stage="deterministic_evaluation",
                    error_type=error_type,
                    message=safe_message,
                )
            ],
        )

    hard_failed = any(result.hard_failure for result in deterministic_results)
    if mode == RunMode.DETERMINISTIC_ONLY:
        if hard_failed:
            status = CaseStatus.FAIL
        elif deterministic_results:
            status = CaseStatus.PASS
        else:
            status = CaseStatus.REVIEW
        return CaseResult(
            run_id=run_id,
            case_id=case.case_id,
            task_pack=case.task_pack,
            status=status,
            evaluation_scope=mode,
            coverage_complete=False,
            metric_results=deterministic_results,
            generated_output_hash=output.output_hash,
        )

    if judge is None:
        return CaseResult(
            run_id=run_id,
            case_id=case.case_id,
            task_pack=case.task_pack,
            status=CaseStatus.RUNTIME_ERROR,
            evaluation_scope=mode,
            coverage_complete=False,
            metric_results=deterministic_results,
            generated_output_hash=output.output_hash,
            runtime_issues=[
                RuntimeIssue(
                    stage="judge_evaluation",
                    error_type="JudgeNotConfigured",
                    message="JudgeNotConfigured",
                )
            ],
        )

    try:
        judge_run = judge.evaluate(case, output)
    except Exception as error:
        error_type, safe_message = safe_exception_details(error)
        issues.append(
            RuntimeIssue(
                stage="judge_evaluation",
                error_type=error_type,
                message=safe_message,
                retryable=True,
            )
        )
        return CaseResult(
            run_id=run_id,
            case_id=case.case_id,
            task_pack=case.task_pack,
            status=CaseStatus.RUNTIME_ERROR,
            evaluation_scope=mode,
            coverage_complete=False,
            metric_results=deterministic_results,
            generated_output_hash=output.output_hash,
            runtime_issues=issues,
        )

    scores = judge_run.scores
    score_mean = mean(scores) if scores else None
    score_min = min(scores) if scores else None
    score_max = max(scores) if scores else None
    unstable = (
        score_min is not None
        and score_max is not None
        and (score_max - score_min) >= judge_config.instability_delta
    )
    if score_mean is None:
        score_band = None
    elif score_mean >= judge_config.threshold:
        score_band = JudgeScoreBand.PASS_CANDIDATE
    elif score_mean >= judge_config.review_floor:
        score_band = JudgeScoreBand.BORDERLINE_REVIEW
    else:
        score_band = JudgeScoreBand.LOW_SCORE_REVIEW

    if hard_failed:
        status = CaseStatus.FAIL
    elif score_mean is None:
        status = CaseStatus.REVIEW
    elif unstable:
        status = CaseStatus.REVIEW
    elif score_mean >= judge_config.threshold:
        status = CaseStatus.PASS
    else:
        # A semantic Judge alone never creates a hard FAIL.
        status = CaseStatus.REVIEW

    return CaseResult(
        run_id=run_id,
        case_id=case.case_id,
        task_pack=case.task_pack,
        status=status,
        evaluation_scope=mode,
        coverage_complete=True,
        metric_results=deterministic_results + judge_run.metrics,
        runtime_issues=issues,
        judge_score_mean=score_mean,
        judge_score_min=score_min,
        judge_score_max=score_max,
        judge_score_band=score_band,
        judge_unstable=unstable,
        judge_request_count=judge_run.request_count,
        judge_usage=judge_run.usage,
        generated_output_hash=output.output_hash,
    )

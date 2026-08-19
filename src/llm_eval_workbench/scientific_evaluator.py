from __future__ import annotations

from .atomic_judge import AtomicJudgeRun
from .schemas import UsageInfo
from .scientific_checks import run_direct_checks
from .scientific_schemas import (
    AtomicDecision,
    JudgeApplicability,
    JudgmentAuthority,
    MachineStatus,
    ScientificCase,
    ScientificCaseResult,
    ScientificOutput,
    Severity,
)


def evaluate_scientific_case(
    *,
    case: ScientificCase,
    config_id: str,
    output: ScientificOutput,
    judge_run: AtomicJudgeRun,
) -> ScientificCaseResult:
    direct_results = run_direct_checks(case, output)
    direct_failures = [
        item
        for item in direct_results
        if item.authority == JudgmentAuthority.DIRECT_VERIFIER and not item.passed
    ]
    signal_failures = [
        item
        for item in direct_results
        if item.authority == JudgmentAuthority.SIGNAL_ONLY and not item.passed
    ]
    blocking_direct = any(
        item.severity in {Severity.CRITICAL, Severity.MAJOR} for item in direct_failures
    )
    semantic_review = any(
        item.applicability == JudgeApplicability.APPLICABLE
        and item.decision in {AtomicDecision.FAIL, AtomicDecision.ABSTAIN}
        for item in judge_run.envelope.criteria
    )
    if blocking_direct:
        status = MachineStatus.FAIL
    elif direct_failures or signal_failures or semantic_review:
        status = MachineStatus.REVIEW
    else:
        status = MachineStatus.PASS
    return ScientificCaseResult(
        case_id=case.case_id,
        config_id=config_id,
        task_pack=case.task_pack,
        machine_status=status,
        direct_results=direct_results,
        judge_result=judge_run.envelope,
        target_request_count=output.request_count,
        judge_request_count=judge_run.request_count,
        target_usage=output.usage,
        judge_usage=judge_run.usage,
        output_hash=output.output_hash,
    )


def runtime_result(
    *,
    case: ScientificCase,
    config_id: str,
    stage: str,
    error_type: str,
    safe_message: str,
    output: ScientificOutput | None = None,
    target_request_count: int = 0,
    judge_request_count: int = 0,
) -> ScientificCaseResult:
    direct_results = run_direct_checks(case, output) if output is not None else []
    return ScientificCaseResult(
        case_id=case.case_id,
        config_id=config_id,
        task_pack=case.task_pack,
        machine_status=MachineStatus.RUNTIME_ERROR,
        direct_results=direct_results,
        runtime_stage=stage,
        runtime_error_type=error_type,
        runtime_error_message=safe_message,
        target_request_count=target_request_count,
        judge_request_count=judge_request_count,
        target_usage=output.usage if output is not None else UsageInfo(),
        output_hash=output.output_hash if output is not None else None,
    )

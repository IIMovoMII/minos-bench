from __future__ import annotations

from pathlib import Path

from llm_eval_workbench.atomic_judge import AtomicJudgeRun
from llm_eval_workbench.hashing import sha256_text
from llm_eval_workbench.schemas import UsageInfo
from llm_eval_workbench.scientific_data import load_target_comparison
from llm_eval_workbench.scientific_evaluator import evaluate_scientific_case
from llm_eval_workbench.scientific_schemas import (
    AtomicDecision,
    AtomicJudgeEnvelope,
    AtomicJudgeItem,
    EvidenceSufficiency,
    JudgeApplicability,
    JudgmentAuthority,
    MachineStatus,
    ScientificCase,
    ScientificOutput,
    Severity,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "datasets" / "scientific_v1"


def _case() -> ScientificCase:
    return {
        item.case_id: item for item in load_target_comparison(DATA_DIR)
    }["CMP-IG-04"]


def _judge_run(
    case: ScientificCase,
    *,
    first_decision: AtomicDecision = AtomicDecision.PASS,
) -> AtomicJudgeRun:
    items = []
    for index, criterion in enumerate(case.semantic_criteria):
        items.append(
            AtomicJudgeItem(
                criterion_id=criterion.criterion_id,
                applicability=JudgeApplicability.APPLICABLE,
                evidence_sufficiency=EvidenceSufficiency.SUFFICIENT,
                decision=first_decision if index == 0 else AtomicDecision.PASS,
                answer_evidence=["fixture"],
                source_evidence=[criterion.evidence[0]],
                reason="fixed unit-test decision",
            )
        )
    return AtomicJudgeRun(
        envelope=AtomicJudgeEnvelope(criteria=items),
        usage=UsageInfo(),
        request_count=1,
        latency_ms=1,
        response_hash="judge-hash",
        provider_status="completed",
    )


def _output(case: ScientificCase, content: str) -> ScientificOutput:
    return ScientificOutput(
        case_id=case.case_id,
        content=content,
        output_hash=sha256_text(content),
    )


def test_signal_only_failure_never_becomes_hard_fail() -> None:
    case = _case()
    output = _output(
        case,
        "1. 风险：自审；证据：同一人复核\n"
        "2. 风险：误发；证据：同一人发布\n建议增加双人复核",
    )
    result = evaluate_scientific_case(
        case=case,
        config_id="model_a_prompt_v1",
        output=output,
        judge_run=_judge_run(case),
    )
    assert any(
        item.authority == JudgmentAuthority.SIGNAL_ONLY and not item.passed
        for item in result.direct_results
    )
    assert result.machine_status == MachineStatus.REVIEW


def test_major_direct_verifier_failure_is_hard_fail() -> None:
    original = _case()
    value = original.model_dump(mode="json")
    signal = value["direct_checks"][1]
    signal["authority"] = JudgmentAuthority.DIRECT_VERIFIER.value
    signal["severity"] = Severity.MAJOR.value
    value["judgment_authority"] = [
        JudgmentAuthority.DIRECT_VERIFIER.value,
        JudgmentAuthority.SEMANTIC_REVIEW.value,
    ]
    case = ScientificCase.model_validate(value)
    output = _output(
        case,
        "1. 风险：自审；证据：同一人复核\n"
        "2. 风险：误发；证据：同一人发布\n建议增加双人复核",
    )
    result = evaluate_scientific_case(
        case=case,
        config_id="model_a_prompt_v1",
        output=output,
        judge_run=_judge_run(case),
    )
    assert result.machine_status == MachineStatus.FAIL


def test_semantic_judge_failure_requires_review_not_automatic_fail() -> None:
    case = _case()
    output = _output(
        case,
        "1. 风险：自审；证据：同一人复核\n"
        "2. 风险：误发；证据：同一人发布",
    )
    result = evaluate_scientific_case(
        case=case,
        config_id="model_a_prompt_v1",
        output=output,
        judge_run=_judge_run(case, first_decision=AtomicDecision.FAIL),
    )
    assert result.machine_status == MachineStatus.REVIEW


def test_keyword_absence_or_presence_is_only_a_signal_for_advice_semantics() -> None:
    case = _case()
    keyword_check = next(
        item for item in case.direct_checks if item.check_type == "forbidden_literals"
    )
    advice_criterion = next(
        item for item in case.semantic_criteria if "建议" in item.behavior
    )
    assert keyword_check.authority == JudgmentAuthority.SIGNAL_ONLY
    assert advice_criterion.authority == JudgmentAuthority.SEMANTIC_REVIEW

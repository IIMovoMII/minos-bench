from __future__ import annotations

from llm_eval_workbench.evaluator import evaluate_case
from llm_eval_workbench.metrics.deepeval_metrics import JudgeRun
from llm_eval_workbench.schemas import (
    CaseStatus,
    DeterministicCheckSpec,
    JudgeConfig,
    JudgeScoreBand,
    MetricResult,
    RunMode,
)


class FakeJudge:
    def __init__(self, scores):
        self.scores = scores

    def evaluate(self, case, output):
        return JudgeRun(
            metrics=[
                MetricResult(
                    metric_id=f"judge.r{index}",
                    kind="judge",
                    passed=score >= 0.75,
                    score=score,
                    threshold=0.75,
                    reason="fake",
                )
                for index, score in enumerate(self.scores, start=1)
            ],
            scores=self.scores,
        )


class BrokenJudge:
    def evaluate(self, case, output):
        raise TimeoutError("secret-provider-message")


class UnexpectedJudge:
    def evaluate(self, case, output):
        raise AssertionError("incomplete target output must not reach the Judge")


def judge_config(repetitions=1):
    return JudgeConfig(
        model_alias="judge",
        threshold=0.75,
        review_floor=0.45,
        repetitions=repetitions,
        instability_delta=0.2,
    )


def test_semantic_pass(sample_case, sample_output):
    result = evaluate_case(
        run_id=sample_output.run_id,
        case=sample_case,
        output=sample_output,
        mode=RunMode.LIVE,
        judge_config=judge_config(),
        judge=FakeJudge([0.9]),
    )
    assert result.status == CaseStatus.PASS
    assert result.coverage_complete is True
    assert result.judge_score_band == JudgeScoreBand.PASS_CANDIDATE


def test_score_between_review_floor_and_threshold_is_borderline_review(
    sample_case, sample_output
):
    result = evaluate_case(
        run_id=sample_output.run_id,
        case=sample_case,
        output=sample_output,
        mode=RunMode.LIVE,
        judge_config=judge_config(),
        judge=FakeJudge([0.6]),
    )
    assert result.status == CaseStatus.REVIEW
    assert result.judge_score_band == JudgeScoreBand.BORDERLINE_REVIEW


def test_low_judge_score_routes_to_review_not_fail(sample_case, sample_output):
    result = evaluate_case(
        run_id=sample_output.run_id,
        case=sample_case,
        output=sample_output,
        mode=RunMode.LIVE,
        judge_config=judge_config(),
        judge=FakeJudge([0.1]),
    )
    assert result.status == CaseStatus.REVIEW
    assert result.judge_score_band == JudgeScoreBand.LOW_SCORE_REVIEW


def test_judge_instability_routes_to_review(sample_case, sample_output):
    result = evaluate_case(
        run_id=sample_output.run_id,
        case=sample_case,
        output=sample_output,
        mode=RunMode.LIVE,
        judge_config=judge_config(repetitions=3),
        judge=FakeJudge([0.9, 0.5, 0.85]),
    )
    assert result.status == CaseStatus.REVIEW
    assert result.judge_unstable is True


def test_hard_deterministic_failure_remains_fail(sample_case, sample_output):
    case = sample_case.model_copy(
        update={
            "deterministic_checks": [
                DeterministicCheckSpec(
                    check_id="missing",
                    type="required_terms",
                    description="must exist",
                    hard=True,
                    params={"terms": ["绝对不存在"]},
                )
            ]
        }
    )
    result = evaluate_case(
        run_id=sample_output.run_id,
        case=case,
        output=sample_output,
        mode=RunMode.LIVE,
        judge_config=judge_config(),
        judge=FakeJudge([0.99]),
    )
    assert result.status == CaseStatus.FAIL


def test_judge_error_is_runtime_error_and_message_is_sanitized(
    sample_case, sample_output
):
    result = evaluate_case(
        run_id=sample_output.run_id,
        case=sample_case,
        output=sample_output,
        mode=RunMode.LIVE,
        judge_config=judge_config(),
        judge=BrokenJudge(),
    )
    assert result.status == CaseStatus.RUNTIME_ERROR
    serialized = result.model_dump_json()
    assert "secret-provider-message" not in serialized
    assert "TimeoutError" in serialized


def test_incomplete_target_output_is_runtime_error_before_quality_checks(
    sample_case, sample_output
):
    incomplete_output = sample_output.model_copy(
        update={
            "generation_complete": False,
            "provider_response_status": "incomplete",
            "provider_incomplete_reason": "max_output_tokens",
        }
    )
    result = evaluate_case(
        run_id=sample_output.run_id,
        case=sample_case,
        output=incomplete_output,
        mode=RunMode.LIVE,
        judge_config=judge_config(),
        judge=UnexpectedJudge(),
    )
    assert result.status == CaseStatus.RUNTIME_ERROR
    assert result.coverage_complete is False
    assert result.generated_output_hash == sample_output.output_hash
    assert result.runtime_issues[0].stage == "target_generation"
    assert result.runtime_issues[0].error_type == "IncompleteTargetResponse"


def test_deterministic_only_marks_scope_incomplete(sample_case, sample_output):
    result = evaluate_case(
        run_id=sample_output.run_id,
        case=sample_case,
        output=sample_output,
        mode=RunMode.DETERMINISTIC_ONLY,
        judge_config=judge_config(),
        judge=None,
    )
    assert result.status == CaseStatus.PASS
    assert result.coverage_complete is False

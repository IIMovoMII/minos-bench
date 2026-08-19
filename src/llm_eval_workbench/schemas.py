from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


def utc_now() -> datetime:
    return datetime.now(UTC)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TaskPack(StrEnum):
    INSTRUCTION_GENERATION = "instruction_generation"
    GROUNDED_QA = "grounded_qa"
    MULTI_TURN = "multi_turn"
    STRUCTURED_TOOL = "structured_tool"


class Language(StrEnum):
    CHINESE = "zh-CN"
    ENGLISH = "en"


class DataSplit(StrEnum):
    DEVELOPMENT = "development"
    HOLDOUT = "holdout"
    REGRESSION = "regression"


class RunMode(StrEnum):
    LIVE = "live"
    REPLAY = "replay"
    DETERMINISTIC_ONLY = "deterministic-only"


class RunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"


class RunStopReason(StrEnum):
    CONSECUTIVE_RUNTIME_ERRORS = "consecutive_runtime_errors"
    TARGET_REQUEST_BUDGET = "target_request_budget"
    JUDGE_REQUEST_BUDGET = "judge_request_budget"


class CaseStatus(StrEnum):
    PASS = "PASS"
    REVIEW = "REVIEW"
    FAIL = "FAIL"
    RUNTIME_ERROR = "RUNTIME_ERROR"


class JudgeScoreBand(StrEnum):
    PASS_CANDIDATE = "PASS_CANDIDATE"
    BORDERLINE_REVIEW = "BORDERLINE_REVIEW"
    LOW_SCORE_REVIEW = "LOW_SCORE_REVIEW"


class ReviewDecision(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    NEEDS_MORE_EVIDENCE = "NEEDS_MORE_EVIDENCE"


class BadCaseCategory(StrEnum):
    CONSTRAINT_OMISSION = "constraint_omission"
    FACTUAL_ERROR_OR_HALLUCINATION = "factual_error_or_hallucination"
    CONTEXT_INCONSISTENCY = "context_inconsistency"
    INCOMPLETE_OR_REDUNDANT = "incomplete_or_redundant"
    JSON_OR_FORMAT_ERROR = "json_or_format_error"
    MULTI_TURN_CONTEXT_LOSS = "multi_turn_context_loss"
    ROLE_DRIFT = "role_drift"
    WRONG_TOOL = "wrong_tool"
    WRONG_TOOL_ARGUMENTS_OR_ORDER = "wrong_tool_arguments_or_order"
    TOOL_RESULT_MISUSE = "tool_result_misuse"
    UNREASONABLE_REFUSAL_OR_SAFETY = "unreasonable_refusal_or_safety"
    RUNTIME_OR_EVALUATOR_ERROR = "runtime_or_evaluator_error"
    OTHER = "other"


class SourceInfo(StrictModel):
    type: Literal["public", "synthetic"]
    name: str = Field(min_length=1)
    reference: str = Field(min_length=1)
    license: str = Field(min_length=1)
    transformed: bool = False
    design_reason: str = Field(min_length=1)


class ConversationTurn(StrictModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str
    name: str | None = None
    tool_call_id: str | None = None


class ExpectedToolCall(StrictModel):
    name: str = Field(min_length=1)
    arguments: dict[str, Any] = Field(default_factory=dict)
    order: int = Field(default=0, ge=0)
    allow_extra_arguments: bool = False


class DeterministicCheckSpec(StrictModel):
    check_id: str = Field(min_length=1)
    type: Literal[
        "required_terms",
        "forbidden_terms",
        "max_length",
        "min_length",
        "list_item_count",
        "json_schema",
        "json_field_values",
        "tool_calls",
        "language",
    ]
    description: str = Field(min_length=1)
    hard: bool = True
    params: dict[str, Any] = Field(default_factory=dict)


class EvaluationCase(StrictModel):
    case_id: str = Field(pattern=r"^[A-Z]{2,4}-\d{3}$")
    task_pack: TaskPack
    task_type: str = Field(min_length=1)
    language: Language
    title: str = Field(min_length=1)
    input: str = Field(min_length=1)
    context: list[str] = Field(default_factory=list)
    expected_output: str | None = None
    expected_facts: list[str] = Field(default_factory=list)
    forbidden_facts: list[str] = Field(default_factory=list)
    rubric_id: str = Field(min_length=1)
    rubric: str = Field(min_length=1)
    deterministic_checks: list[DeterministicCheckSpec] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    source: SourceInfo
    split: DataSplit
    version: str = Field(min_length=1)
    turns: list[ConversationTurn] = Field(default_factory=list)
    available_tools: list[dict[str, Any]] = Field(default_factory=list)
    expected_tools: list[ExpectedToolCall] = Field(default_factory=list)
    tool_outputs: list[dict[str, Any]] = Field(default_factory=list)
    expected_final_behavior: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_pack_contract(self) -> EvaluationCase:
        if self.task_pack == TaskPack.GROUNDED_QA and not self.context:
            raise ValueError("grounded_qa cases require context")
        if self.task_pack == TaskPack.MULTI_TURN and not self.turns:
            raise ValueError("multi_turn cases require turns")
        if self.task_type == "function_call" and (
            not self.available_tools or not self.expected_tools
        ):
            raise ValueError(
                "function_call cases require available_tools and expected_tools"
            )
        return self


class GenerationParams(StrictModel):
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    top_p: float | None = Field(default=None, gt=0.0, le=1.0)
    max_tokens: int = Field(default=1200, ge=1, le=32768)
    seed: int | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class ModelConfig(StrictModel):
    alias: str = Field(min_length=1)
    role: Literal["target", "judge"]
    model_env: str = Field(min_length=1)
    api_key_env: str = Field(min_length=1)
    base_url_env: str | None = None
    api_mode_env: str | None = None
    reasoning_effort_env: str | None = None
    params: GenerationParams = Field(default_factory=GenerationParams)


class PromptConfig(StrictModel):
    prompt_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    system_template: str = Field(min_length=1)
    user_template: str = "{input}"


class JudgeConfig(StrictModel):
    model_alias: str
    threshold: float = Field(default=0.75, ge=0.0, le=1.0)
    review_floor: float = Field(default=0.45, ge=0.0, le=1.0)
    repetitions: int = Field(default=1, ge=1, le=5)
    instability_delta: float = Field(default=0.2, ge=0.0, le=1.0)
    include_reason: bool = True

    @model_validator(mode="after")
    def validate_thresholds(self) -> JudgeConfig:
        if self.review_floor > self.threshold:
            raise ValueError("review_floor cannot exceed threshold")
        return self


class ProjectConfig(StrictModel):
    project_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    version: str = Field(min_length=1)
    dataset_paths: list[str] = Field(min_length=1)
    metric_profile_path: str = "configs/metrics.yaml"
    artifact_dir: str = "artifacts/runs"
    models: list[ModelConfig]
    prompts: list[PromptConfig]
    target_model_alias: str
    prompt_id: str
    judge: JudgeConfig

    @model_validator(mode="after")
    def validate_references(self) -> ProjectConfig:
        aliases = {model.alias for model in self.models}
        prompt_ids = {prompt.prompt_id for prompt in self.prompts}
        if self.target_model_alias not in aliases:
            raise ValueError("target_model_alias is not defined in models")
        if self.judge.model_alias not in aliases:
            raise ValueError("judge.model_alias is not defined in models")
        if self.prompt_id not in prompt_ids:
            raise ValueError("prompt_id is not defined in prompts")
        return self

    def model_by_alias(self, alias: str) -> ModelConfig:
        for model in self.models:
            if model.alias == alias:
                return model
        raise KeyError(alias)

    def prompt_by_id(self, prompt_id: str) -> PromptConfig:
        for prompt in self.prompts:
            if prompt.prompt_id == prompt_id:
                return prompt
        raise KeyError(prompt_id)


class ToolCall(StrictModel):
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    call_id: str | None = None
    order: int = 0


class UsageInfo(StrictModel):
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    cost: float | None = None
    currency: str = "USD"


class GeneratedOutput(StrictModel):
    run_id: str
    source_run_id: str | None = None
    source_artifact_hash: str | None = None
    case_id: str
    model_alias: str
    model_name: str
    prompt_id: str
    prompt_version: str
    content: str
    tool_calls: list[ToolCall] = Field(default_factory=list)
    usage: UsageInfo = Field(default_factory=UsageInfo)
    latency_ms: int | None = None
    attempts: int = 1
    request_count: int = 1
    generation_complete: bool = True
    provider_response_status: str | None = None
    provider_incomplete_reason: str | None = None
    output_hash: str
    created_at: datetime = Field(default_factory=utc_now)


class ImportedOutput(StrictModel):
    case_id: str
    model_alias: str
    model_name: str
    prompt_id: str
    prompt_version: str
    content: str
    tool_calls: list[ToolCall] = Field(default_factory=list)
    usage: UsageInfo = Field(default_factory=UsageInfo)
    latency_ms: int | None = None
    attempts: int = Field(default=0, ge=0)
    request_count: int = Field(default=0, ge=0)
    generation_complete: bool = True
    provider_response_status: str | None = None
    provider_incomplete_reason: str | None = None
    output_hash: str | None = None
    fixture: bool = False


class MetricResult(StrictModel):
    metric_id: str
    kind: Literal["deterministic", "judge"]
    passed: bool | None
    score: float | None = None
    threshold: float | None = None
    reason: str
    hard_failure: bool = False
    details: dict[str, Any] = Field(default_factory=dict)


class RuntimeIssue(StrictModel):
    stage: Literal[
        "configuration",
        "dataset",
        "target_generation",
        "deterministic_evaluation",
        "judge_evaluation",
        "persistence",
    ]
    error_type: str
    message: str
    retryable: bool = False


class CaseResult(StrictModel):
    run_id: str
    case_id: str
    task_pack: TaskPack
    status: CaseStatus
    evaluation_scope: RunMode
    coverage_complete: bool
    metric_results: list[MetricResult] = Field(default_factory=list)
    runtime_issues: list[RuntimeIssue] = Field(default_factory=list)
    judge_score_mean: float | None = None
    judge_score_min: float | None = None
    judge_score_max: float | None = None
    judge_score_band: JudgeScoreBand | None = None
    judge_unstable: bool = False
    judge_request_count: int = 0
    judge_usage: UsageInfo = Field(default_factory=UsageInfo)
    generated_output_hash: str | None = None
    created_at: datetime = Field(default_factory=utc_now)


class HumanReview(StrictModel):
    review_id: str
    run_id: str
    case_id: str
    reviewer: str
    decision: ReviewDecision
    reason: str = Field(min_length=1)
    issue_categories: list[BadCaseCategory] = Field(default_factory=list)
    root_cause_hypothesis: str | None = None
    improvement_suggestion: str | None = None
    blind: bool = True
    machine_status_before_review: CaseStatus
    created_at: datetime = Field(default_factory=utc_now)


class RunManifest(StrictModel):
    run_id: str
    project_id: str
    project_version: str
    mode: RunMode
    status: RunStatus
    target_model_alias: str
    target_model_name: str
    target_api_mode: str | None = None
    target_streaming: bool = False
    target_reasoning_effort: str | None = None
    judge_model_alias: str | None = None
    judge_model_name: str | None = None
    judge_api_mode: str | None = None
    judge_streaming: bool = False
    judge_reasoning_effort: str | None = None
    judge_target_identity_blinded: bool | None = None
    judge_blind_policy_version: str | None = None
    provider_storage_enabled: bool = False
    prompt_id: str
    prompt_version: str
    dataset_hash: str
    config_hash: str
    generation_config_hash: str
    metric_config_hash: str
    code_hash: str
    replay_source_run_id: str | None = None
    started_at: datetime = Field(default_factory=utc_now)
    finished_at: datetime | None = None
    case_count: int
    completed_count: int = 0
    max_consecutive_runtime_errors: int | None = None
    max_target_requests: int | None = None
    max_judge_requests: int | None = None
    stop_reason: RunStopReason | None = None
    sensitive_fields_persisted: bool = False
    notes: list[str] = Field(default_factory=list)


class RunSummary(StrictModel):
    run_id: str
    case_count: int
    status_counts: dict[str, int]
    task_pack_counts: dict[str, dict[str, int]]
    mean_judge_score: float | None = None
    runtime_error_count: int = 0
    human_review_count: int = 0
    target_request_count: int = 0
    target_prompt_tokens: int | None = None
    target_completion_tokens: int | None = None
    target_cost: float | None = None
    judge_request_count: int = 0
    judge_prompt_tokens: int | None = None
    judge_completion_tokens: int | None = None
    judge_cost: float | None = None
    generated_at: datetime = Field(default_factory=utc_now)

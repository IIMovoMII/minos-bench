from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .schemas import TaskPack, ToolCall, UsageInfo


class ScientificModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DataUse(StrEnum):
    RULE_DEVELOPMENT = "rule_development"
    TECHNICAL_PROBES = "technical_probes"
    JUDGE_VALIDATION = "judge_validation"
    TARGET_COMPARISON = "target_comparison"
    REGRESSION = "regression"


class SourceType(StrEnum):
    LICENSED_ADAPTATION = "licensed_adaptation"
    METHOD_TRANSFER = "method_transfer"
    SELF_BUILT_MINIMAL = "self_built_minimal"
    CONFIRMED_REAL_BAD_CASE = "confirmed_real_bad_case"
    SYNTHETIC_REGRESSION_SEED = "synthetic_regression_seed"
    SYNTHETIC_DRAFT = "synthetic_draft"


class TestType(StrEnum):
    NORMAL = "normal"
    BOUNDARY = "boundary"
    EXPLICIT_FAILURE = "explicit_failure"
    MINIMAL_CONTRAST = "minimal_contrast"
    INVARIANCE = "invariance"
    TEMPTATION = "temptation"
    TECHNICAL_PROBE = "technical_probe"
    REGRESSION_SEED = "regression_seed"


class Severity(StrEnum):
    CRITICAL = "critical"
    MAJOR = "major"
    MINOR = "minor"


class JudgmentAuthority(StrEnum):
    DIRECT_VERIFIER = "DIRECT_VERIFIER"
    SIGNAL_ONLY = "SIGNAL_ONLY"
    SEMANTIC_REVIEW = "SEMANTIC_REVIEW"
    HUMAN_REQUIRED = "HUMAN_REQUIRED"


class JudgeApplicability(StrEnum):
    APPLICABLE = "APPLICABLE"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class EvidenceSufficiency(StrEnum):
    SUFFICIENT = "SUFFICIENT"
    INSUFFICIENT = "INSUFFICIENT"


class AtomicDecision(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    ABSTAIN = "ABSTAIN"


class MachineStatus(StrEnum):
    PASS = "PASS"
    REVIEW = "REVIEW"
    FAIL = "FAIL"
    RUNTIME_ERROR = "RUNTIME_ERROR"


class ScientificTurn(ScientificModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str
    name: str | None = None
    call_id: str | None = None


class ScientificSource(ScientificModel):
    source_type: SourceType
    source_name: str = Field(min_length=1)
    paper_url: str = Field(min_length=1)
    repository_url: str = Field(min_length=1)
    original_case_id_or_method: str = Field(min_length=1)
    license: str = Field(min_length=1)
    adaptation_note: str = Field(min_length=1)
    source_success_definition: str | None = Field(default=None, min_length=1)
    source_checker_reference: str | None = Field(default=None, min_length=1)
    preserved_invariants: list[str] = Field(default_factory=list)
    surface_changes: list[str] = Field(default_factory=list)
    license_use: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def validate_license_use(self) -> ScientificSource:
        undeclared = self.license.casefold() in {
            "undeclared",
            "not_declared",
            "未声明",
        }
        if undeclared and self.source_type != SourceType.METHOD_TRANSFER:
            raise ValueError("unlicensed sources may be used only as method_transfer")
        if (
            self.source_type == SourceType.LICENSED_ADAPTATION
            and "method" in self.original_case_id_or_method.casefold()
        ):
            raise ValueError("licensed adaptations require a concrete original case ID")
        return self


class DirectCheckSpec(ScientificModel):
    criterion_id: str = Field(min_length=1)
    check_type: Literal[
        "exact_line_count",
        "line_prefixes",
        "list_item_count",
        "item_max_length",
        "placeholder_count",
        "required_literals",
        "forbidden_literals",
        "headings_exact",
        "max_length",
        "min_length_without_whitespace",
        "json_schema",
        "tool_calls_exact",
        "tool_observation_sequence",
        "no_tool_call",
        "final_state_any_path",
    ]
    description: str = Field(min_length=1)
    authority: JudgmentAuthority
    severity: Severity
    applicability: str = Field(min_length=1)
    params: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_authority(self) -> DirectCheckSpec:
        if self.authority not in {
            JudgmentAuthority.DIRECT_VERIFIER,
            JudgmentAuthority.SIGNAL_ONLY,
        }:
            raise ValueError("direct checks require DIRECT_VERIFIER or SIGNAL_ONLY")
        return self


class AtomicCriterion(ScientificModel):
    criterion_id: str = Field(min_length=1)
    behavior: str = Field(min_length=1)
    applicability: str = Field(min_length=1)
    evidence: list[str] = Field(min_length=1)
    pass_condition: str = Field(min_length=1)
    fail_condition: str = Field(min_length=1)
    abstain_condition: str = Field(min_length=1)
    not_applicable_condition: str = Field(min_length=1)
    severity: Severity
    authority: JudgmentAuthority
    positive_example: str = Field(min_length=1)
    negative_example: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_authority(self) -> AtomicCriterion:
        if self.authority not in {
            JudgmentAuthority.SEMANTIC_REVIEW,
            JudgmentAuthority.HUMAN_REQUIRED,
        }:
            raise ValueError("semantic criteria require semantic or human authority")
        return self


class ScientificCase(ScientificModel):
    case_id: str = Field(pattern=r"^(?:ANCHOR|CMP|JV|REG)-[A-Z]{2}-\d{2}$")
    title: str = Field(min_length=1)
    task_pack: TaskPack
    capability: str = Field(min_length=1)
    user_goal: str = Field(min_length=1)
    failure_behavior: str = Field(min_length=1)
    severity: Severity
    test_type: TestType
    data_use: DataUse
    scenario_family: str = Field(min_length=1)
    version: str = Field(min_length=1)
    applicability: str = Field(min_length=1)
    judgment_authority: list[JudgmentAuthority] = Field(min_length=1)
    evidence: list[str] = Field(min_length=1)
    source: ScientificSource
    input: str = Field(min_length=1)
    context: list[str] = Field(default_factory=list)
    turns: list[ScientificTurn] = Field(default_factory=list)
    available_tools: list[dict[str, Any]] = Field(default_factory=list)
    tool_outputs: list[dict[str, Any]] = Field(default_factory=list)
    max_agent_turns: int = Field(default=1, ge=1, le=8)
    expected_behavior: str = Field(min_length=1)
    direct_checks: list[DirectCheckSpec] = Field(default_factory=list)
    semantic_criteria: list[AtomicCriterion] = Field(default_factory=list)
    risk_cell: str | None = Field(default=None, min_length=1)
    difficulty: Literal["D1", "D2", "D3"] | None = None
    difficulty_rationale: str | None = Field(default=None, min_length=1)
    gold_answer: str | None = Field(default=None, min_length=1)
    gold_tool_calls: list[ToolCall] = Field(default_factory=list)
    gold_environment_state: dict[str, Any] = Field(default_factory=dict)
    counterexample: str | None = Field(default=None, min_length=1)
    counterexample_tool_calls: list[ToolCall] = Field(default_factory=list)
    checker_boundary: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def validate_contract(self) -> ScientificCase:
        criterion_ids = [
            *(item.criterion_id for item in self.direct_checks),
            *(item.criterion_id for item in self.semantic_criteria),
        ]
        if len(criterion_ids) != len(set(criterion_ids)):
            raise ValueError("criterion IDs must be unique within a case")
        declared = set(self.judgment_authority)
        actual = {
            *(item.authority for item in self.direct_checks),
            *(item.authority for item in self.semantic_criteria),
        }
        if declared != actual:
            raise ValueError("question judgment_authority must match its criteria")
        if self.data_use == DataUse.TARGET_COMPARISON and not self.semantic_criteria:
            raise ValueError("comparison cases require atomic semantic criteria")
        if self.data_use == DataUse.TARGET_COMPARISON and self.version.startswith(
            ("2", "3")
        ):
            required_comparison = {
                "risk_cell": self.risk_cell,
                "difficulty": self.difficulty,
                "difficulty_rationale": self.difficulty_rationale,
                "counterexample": self.counterexample,
                "checker_boundary": self.checker_boundary,
            }
            missing = [
                name for name, value in required_comparison.items() if not value
            ]
            if missing:
                raise ValueError(
                    f"scientific comparison metadata missing: {missing}"
                )
            if not self.gold_answer and not self.gold_tool_calls:
                raise ValueError(
                    "scientific comparison cases require a complete gold"
                )
        if self.data_use == DataUse.TARGET_COMPARISON and self.version.startswith("3"):
            source_requirements = {
                "source_success_definition": self.source.source_success_definition,
                "source_checker_reference": self.source.source_checker_reference,
                "preserved_invariants": self.source.preserved_invariants,
                "surface_changes": self.source.surface_changes,
                "license_use": self.source.license_use,
            }
            missing = [
                name for name, value in source_requirements.items() if not value
            ]
            if missing:
                raise ValueError(
                    f"scientific v3 source provenance missing: {missing}"
                )
        if self.max_agent_turns > 1:
            if not self.available_tools:
                raise ValueError("multi-turn agent cases require available tools")
            simulated = {
                str(item.get("name"))
                for item in self.tool_outputs
                if item.get("simulation") is True
            }
            available = {
                str(item.get("name"))
                for item in self.available_tools
                if item.get("name")
            }
            missing = sorted(available - simulated)
            if missing:
                raise ValueError(
                    "multi-turn agent cases require a simulation for every tool: "
                    f"{missing}"
                )
        return self


class SourceLedgerEntry(ScientificModel):
    case_id: str
    task_pack: TaskPack
    capability: str
    user_goal: str
    failure_behavior: str
    severity: Severity
    test_type: TestType
    source_type: SourceType
    source_name: str
    paper_url: str
    repository_url: str
    original_case_id_or_method: str
    license: str
    adaptation_note: str
    source_success_definition: str | None = None
    source_checker_reference: str | None = None
    preserved_invariants: list[str] = Field(default_factory=list)
    surface_changes: list[str] = Field(default_factory=list)
    license_use: str | None = None
    data_use: DataUse
    scenario_family: str
    version: str
    applicability: str
    judgment_authority: list[JudgmentAuthority]
    evidence: list[str]
    risk_cell: str | None = None
    difficulty: Literal["D1", "D2", "D3"] | None = None
    difficulty_rationale: str | None = None
    checker_boundary: str | None = None


class JudgeValidationResponse(ScientificModel):
    response_id: str = Field(pattern=r"^JV-[A-Z]{2}-\d{2}-(?:PASS|FAIL)$")
    case_id: str = Field(pattern=r"^JV-[A-Z]{2}-\d{2}$")
    scenario_family: str
    expected_decision: Literal["PASS", "FAIL"]
    expected_criterion_decisions: dict[str, AtomicDecision] = Field(min_length=1)
    answer: str = Field(min_length=1)
    tool_calls: list[ToolCall] = Field(default_factory=list)
    environment_state: dict[str, Any] = Field(default_factory=dict)
    reference_authority: Literal["candidate_reference"] = "candidate_reference"
    reference_version: str = Field(min_length=1)
    reference_status: Literal["candidate_approved_direction"] = (
        "candidate_approved_direction"
    )
    validation_targets: list[str] = Field(min_length=1)
    rationale: str = Field(min_length=1)


class AtomicJudgeItem(ScientificModel):
    criterion_id: str
    applicability: JudgeApplicability
    evidence_sufficiency: EvidenceSufficiency
    decision: AtomicDecision
    answer_evidence: list[str] = Field(default_factory=list)
    source_evidence: list[str] = Field(default_factory=list)
    reason: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_decision_logic(self) -> AtomicJudgeItem:
        if self.applicability == JudgeApplicability.NOT_APPLICABLE:
            if self.decision != AtomicDecision.ABSTAIN:
                raise ValueError("not-applicable criteria must use ABSTAIN")
        elif self.evidence_sufficiency == EvidenceSufficiency.INSUFFICIENT:
            if self.decision != AtomicDecision.ABSTAIN:
                raise ValueError("insufficient evidence must use ABSTAIN")
        elif self.decision == AtomicDecision.ABSTAIN:
            raise ValueError("applicable criteria with sufficient evidence must decide")
        return self


class AtomicJudgeEnvelope(ScientificModel):
    protocol_version: Literal["atomic-judge-v1"] = "atomic-judge-v1"
    criteria: list[AtomicJudgeItem] = Field(min_length=1)


class DirectCheckResult(ScientificModel):
    criterion_id: str
    authority: JudgmentAuthority
    severity: Severity
    passed: bool
    reason: str
    details: dict[str, Any] = Field(default_factory=dict)


class ScientificOutput(ScientificModel):
    case_id: str
    content: str
    tool_calls: list[ToolCall] = Field(default_factory=list)
    environment_state: dict[str, Any] = Field(default_factory=dict)
    tool_trace: list[dict[str, Any]] = Field(default_factory=list)
    model_turns: int = 1
    usage: UsageInfo = Field(default_factory=UsageInfo)
    latency_ms: int | None = None
    request_count: int = 1
    provider_status: str | None = None
    output_hash: str


class ScientificCaseResult(ScientificModel):
    case_id: str
    config_id: str
    task_pack: TaskPack
    machine_status: MachineStatus
    direct_results: list[DirectCheckResult] = Field(default_factory=list)
    judge_result: AtomicJudgeEnvelope | None = None
    runtime_stage: str | None = None
    runtime_error_type: str | None = None
    runtime_error_message: str | None = None
    target_request_count: int = 0
    judge_request_count: int = 0
    target_usage: UsageInfo = Field(default_factory=UsageInfo)
    judge_usage: UsageInfo = Field(default_factory=UsageInfo)
    output_hash: str | None = None


class HumanCriterionDecision(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    NEEDS_MORE_EVIDENCE = "NEEDS_MORE_EVIDENCE"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class HumanCriterionReview(ScientificModel):
    criterion_id: str
    decision: HumanCriterionDecision
    reason: str = Field(min_length=1)


class ScientificHumanReview(ScientificModel):
    review_id: str
    execution_id: str
    review_item_id: str
    case_id: str
    config_id: str
    reviewer: Literal["candidate"] = "candidate"
    blind: Literal[True] = True
    criteria: list[HumanCriterionReview] = Field(min_length=1)
    created_at: datetime


class ExecutionStage(StrEnum):
    OFFLINE_GATE = "offline_gate"
    PROVIDER_PROBE = "provider_probe"
    TECHNICAL_PROBE = "technical_probe"
    JUDGE_VALIDATION = "judge_validation"
    TARGET_GENERATION = "target_generation"
    TARGET_BARRIER = "target_barrier"
    JUDGE_EVALUATION = "judge_evaluation"
    REPORT = "report"


class ExecutionNode(ScientificModel):
    node_id: str
    stage: ExecutionStage
    dependencies: list[str] = Field(default_factory=list)
    request_owner: Literal["none", "target", "judge"] = "none"
    planned_requests: int = Field(default=0, ge=0, le=8)
    config_id: str | None = None
    case_id: str | None = None
    probe_id: str | None = None


class ScientificExecutionPlan(ScientificModel):
    schema_version: Literal["scientific-execution-plan-v1"] = (
        "scientific-execution-plan-v1"
    )
    execution_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{4,100}$")
    created_at: datetime
    dataset_manifest_sha256: str
    dataset_seal_sha256: str
    protocol_sha256: str
    config_ids: list[str]
    formal_case_count: int
    formal_target_requests: int
    formal_judge_requests: int
    provider_probe_requests: int
    technical_probe_requests: int
    judge_validation_requests: int
    transient_retry_cap: int | None
    planned_base_requests: int
    absolute_request_ceiling: int | None
    max_consecutive_runtime_errors: int
    estimated_token_range: dict[str, int]
    nodes: list[ExecutionNode]

    @model_validator(mode="after")
    def validate_request_math(self) -> ScientificExecutionPlan:
        planned = sum(node.planned_requests for node in self.nodes)
        if planned != self.planned_base_requests:
            raise ValueError("node request sum does not match planned_base_requests")
        if self.transient_retry_cap is None:
            if self.absolute_request_ceiling is not None:
                raise ValueError(
                    "unbounded retries require no absolute request ceiling"
                )
        elif self.absolute_request_ceiling != planned + self.transient_retry_cap:
            raise ValueError("absolute request ceiling must equal base plus retry cap")
        node_ids = [node.node_id for node in self.nodes]
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("execution node IDs must be unique")
        known = set(node_ids)
        for node in self.nodes:
            if not set(node.dependencies) <= known:
                raise ValueError(f"unknown dependency in {node.node_id}")
        return self


class ScientificDatasetManifest(ScientificModel):
    schema_version: Literal[
        "scientific-dataset-v1",
        "scientific-dataset-v2",
        "scientific-dataset-v3",
    ] = "scientific-dataset-v1"
    dataset_version: str
    created_at: datetime
    source_audit_version: str
    source_audit_path: str
    source_audit_sha256: str
    schema_module: str
    file_sha256: dict[str, str]
    counts: dict[str, int]
    task_pack_distribution: dict[str, int]
    data_use_distribution: dict[str, int]
    excluded_source_types: list[SourceType]
    difficulty_distribution: dict[str, int] | None = None
    risk_cell_distribution: dict[str, int] | None = None


class ScientificDatasetSeal(ScientificModel):
    seal_version: Literal[
        "scientific-dataset-seal-v1",
        "scientific-dataset-seal-v2",
        "scientific-dataset-seal-v3",
    ] = "scientific-dataset-seal-v1"
    status: Literal["sealed"] = "sealed"
    dataset_version: str
    sealed_at: datetime
    manifest_sha256: str
    aggregate_content_sha256: str
    case_ids_sha256: str
    source_audit_sha256: str

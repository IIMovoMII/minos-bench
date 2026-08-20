from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .hashing import sha256_file
from .scientific_data import (
    audit_scientific_dataset,
    load_judge_validation,
    load_target_comparison,
)
from .scientific_schemas import (
    ExecutionNode,
    ExecutionStage,
    ScientificExecutionPlan,
)

CONFIG_IDS = (
    "model_a_prompt_v1",
    "model_b_prompt_v1",
    "weak_prompt_v1",
    "weak_prompt_v2",
)


def load_scientific_protocol(path: str | Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("scientific protocol must be a JSON object")
    configured_ids = tuple(item["config_id"] for item in value.get("configs", []))
    if configured_ids != CONFIG_IDS:
        raise ValueError(f"scientific protocol config order must be {CONFIG_IDS}")
    protocol_version = str(value.get("protocol_version", ""))
    expected_judge_protocol = (
        "atomic-judge-v2"
        if protocol_version.startswith("scientific-v3")
        else "atomic-judge-v1"
    )
    if value.get("judge", {}).get("protocol_version") != expected_judge_protocol:
        raise ValueError(
            f"{protocol_version or 'scientific protocol'} must use "
            f"{expected_judge_protocol}"
        )
    if value.get("api_contract", {}).get("endpoint_mode") != "responses":
        raise ValueError("scientific protocol must use Responses")
    if value.get("api_contract", {}).get("stream") is not False:
        raise ValueError("scientific execution freezes non-streaming transport")
    if value.get("api_contract", {}).get("store") is not False:
        raise ValueError("scientific execution requires store=false")
    if value.get("target_generation", {}).get("quality_triggered_regeneration"):
        raise ValueError("quality-triggered target regeneration is forbidden")
    if value.get("judge", {}).get("requests_per_answer") != 1:
        raise ValueError("every saved answer must use one logical Judge request")
    retry_attempts = int(
        value.get("stop_rules", {}).get(
            "empty_or_api_failure_retry_attempts",
            0,
        )
    )
    if retry_attempts < 0:
        raise ValueError("empty/API retry attempts must not be negative")
    return value


def _build_nodes(
    cases: list[tuple[str, int]],
    validation_response_ids: list[tuple[str, str]],
    *,
    run_provider_probes: bool = True,
    run_technical_probes: bool = True,
    run_judge_validation: bool = True,
) -> list[ExecutionNode]:
    nodes = [
        ExecutionNode(
            node_id="offline-gate",
            stage=ExecutionStage.OFFLINE_GATE,
        )
    ]
    provider_nodes = [
        ("provider-probe-model-a", "target", "model_a"),
        ("provider-probe-model-b", "target", "model_b"),
        ("provider-probe-weak", "target", "weak_model"),
        ("provider-probe-judge", "judge", "judge"),
    ]
    if run_provider_probes:
        for node_id, owner, probe_id in provider_nodes:
            nodes.append(
                ExecutionNode(
                    node_id=node_id,
                    stage=ExecutionStage.PROVIDER_PROBE,
                    dependencies=["offline-gate"],
                    request_owner=owner,
                    planned_requests=1,
                    probe_id=probe_id,
                )
            )
    provider_ids = [item[0] for item in provider_nodes] if run_provider_probes else []
    upstream_ids = provider_ids or ["offline-gate"]
    technical_nodes = [
        ("technical-plain", 1),
        ("technical-grounded", 1),
        ("technical-multi-turn", 1),
        ("technical-json", 1),
        ("technical-tool-roundtrip", 2),
    ]
    if run_technical_probes:
        for node_id, requests in technical_nodes:
            nodes.append(
                ExecutionNode(
                    node_id=node_id,
                    stage=ExecutionStage.TECHNICAL_PROBE,
                    dependencies=upstream_ids,
                    request_owner="target",
                    planned_requests=requests,
                    probe_id=node_id.removeprefix("technical-"),
                )
            )
    technical_ids = (
        [item[0] for item in technical_nodes] if run_technical_probes else []
    )
    upstream_ids = technical_ids or upstream_ids
    validation_ids: list[str] = []
    if run_judge_validation:
        for case_id, response_id in validation_response_ids:
            node_id = f"judge-validation--{response_id}"
            validation_ids.append(node_id)
            nodes.append(
                ExecutionNode(
                    node_id=node_id,
                    stage=ExecutionStage.JUDGE_VALIDATION,
                    dependencies=upstream_ids,
                    request_owner="judge",
                    planned_requests=1,
                    case_id=case_id,
                    probe_id=response_id,
                )
            )
    nodes.append(
        ExecutionNode(
            node_id="judge-validation-complete",
            stage=ExecutionStage.TARGET_BARRIER,
            dependencies=validation_ids or upstream_ids,
        )
    )
    target_ids: list[str] = []
    for config_id in CONFIG_IDS:
        for case_id, max_agent_turns in cases:
            node_id = f"target--{config_id}--{case_id}"
            target_ids.append(node_id)
            nodes.append(
                ExecutionNode(
                    node_id=node_id,
                    stage=ExecutionStage.TARGET_GENERATION,
                    dependencies=["judge-validation-complete"],
                    request_owner="target",
                    planned_requests=max_agent_turns,
                    config_id=config_id,
                    case_id=case_id,
                )
            )
    nodes.append(
        ExecutionNode(
            node_id="formal-targets-complete",
            stage=ExecutionStage.TARGET_BARRIER,
            dependencies=target_ids,
        )
    )
    judge_ids: list[str] = []
    for config_id in CONFIG_IDS:
        for case_id, _ in cases:
            node_id = f"judge--{config_id}--{case_id}"
            judge_ids.append(node_id)
            nodes.append(
                ExecutionNode(
                    node_id=node_id,
                    stage=ExecutionStage.JUDGE_EVALUATION,
                    dependencies=["formal-targets-complete"],
                    request_owner="judge",
                    planned_requests=1,
                    config_id=config_id,
                    case_id=case_id,
                )
            )
    nodes.append(
        ExecutionNode(
            node_id="machine-report",
            stage=ExecutionStage.REPORT,
            dependencies=judge_ids,
        )
    )
    return nodes


def build_execution_plan(
    *,
    execution_id: str,
    data_dir: str | Path,
    source_audit_path: str | Path,
    protocol_path: str | Path,
    created_at: datetime | None = None,
) -> ScientificExecutionPlan:
    audit = audit_scientific_dataset(
        data_dir=data_dir,
        source_audit_path=source_audit_path,
        verify_seal=True,
    )
    if not audit["valid"]:
        raise ValueError(f"scientific dataset gate failed: {audit['errors']}")
    protocol = load_scientific_protocol(protocol_path)
    directory = Path(data_dir)
    cases = sorted(load_target_comparison(directory), key=lambda item: item.case_id)
    _, validation_responses = load_judge_validation(directory)
    validation_pairs = sorted(
        (item.case_id, item.response_id) for item in validation_responses
    )
    nodes = _build_nodes(
        [(case.case_id, case.max_agent_turns) for case in cases],
        validation_pairs,
        run_provider_probes=bool(
            protocol.get("matrix", {}).get("run_provider_probes", True)
        ),
        run_technical_probes=bool(
            protocol.get("matrix", {}).get("run_technical_probes", True)
        ),
        run_judge_validation=bool(
            protocol.get("matrix", {}).get("run_judge_validation", True)
        ),
    )
    base_requests = sum(node.planned_requests for node in nodes)
    matrix = protocol.get("matrix", {})
    formal_target_requests = sum(
        case.max_agent_turns for case in cases
    ) * len(CONFIG_IDS)
    expected_matrix = {
        "formal_cases": len(cases),
        "configurations": len(CONFIG_IDS),
        "formal_target_requests": formal_target_requests,
        "formal_judge_requests": len(cases) * len(CONFIG_IDS),
        "planned_base_requests": base_requests,
    }
    mismatches = {
        key: {"expected": expected, "actual": matrix.get(key)}
        for key, expected in expected_matrix.items()
        if key in matrix and matrix.get(key) != expected
    }
    if mismatches:
        raise ValueError(f"scientific protocol matrix mismatch: {mismatches}")
    # Character-based planning estimate only; actual provider usage is logged.
    source_characters = sum(
        len(case.input)
        + sum(len(value) for value in case.context)
        + sum(len(turn.content) for turn in case.turns)
        for case in cases
    )
    return ScientificExecutionPlan(
        execution_id=execution_id,
        created_at=created_at or datetime.now(UTC),
        dataset_manifest_sha256=sha256_file(directory / "manifest.json"),
        dataset_seal_sha256=sha256_file(directory / "seal.json"),
        protocol_sha256=sha256_file(protocol_path),
        config_ids=list(CONFIG_IDS),
        formal_case_count=len(cases),
        formal_target_requests=formal_target_requests,
        formal_judge_requests=len(cases) * len(CONFIG_IDS),
        provider_probe_requests=sum(
            node.planned_requests
            for node in nodes
            if node.stage == ExecutionStage.PROVIDER_PROBE
        ),
        technical_probe_requests=sum(
            node.planned_requests
            for node in nodes
            if node.stage == ExecutionStage.TECHNICAL_PROBE
        ),
        judge_validation_requests=sum(
            node.planned_requests
            for node in nodes
            if node.stage == ExecutionStage.JUDGE_VALIDATION
        ),
        transient_retry_cap=None,
        planned_base_requests=base_requests,
        absolute_request_ceiling=None,
        max_consecutive_runtime_errors=3,
        estimated_token_range={
            "lower": max(1, source_characters * len(CONFIG_IDS) // 3),
            "upper": max(1, source_characters * len(CONFIG_IDS) * 6),
        },
        nodes=nodes,
    )


def create_immutable_plan(
    *,
    execution_root: str | Path,
    plan: ScientificExecutionPlan,
) -> Path:
    root = Path(execution_root).resolve()
    directory = (root / plan.execution_id).resolve()
    if root not in directory.parents:
        raise ValueError("execution path escapes artifact root")
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "execution_plan.json"
    if path.exists():
        existing = ScientificExecutionPlan.model_validate_json(
            path.read_text(encoding="utf-8")
        )
        if existing != plan:
            raise FileExistsError("immutable execution plan already exists and differs")
        return path
    payload = json.dumps(
        plan.model_dump(mode="json"),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(payload + "\n")
    return path


def load_and_verify_plan(
    *,
    plan_path: str | Path,
    data_dir: str | Path,
    protocol_path: str | Path,
) -> ScientificExecutionPlan:
    plan = ScientificExecutionPlan.model_validate_json(
        Path(plan_path).read_text(encoding="utf-8")
    )
    directory = Path(data_dir)
    checks = {
        "dataset_manifest": plan.dataset_manifest_sha256
        == sha256_file(directory / "manifest.json"),
        "dataset_seal": plan.dataset_seal_sha256
        == sha256_file(directory / "seal.json"),
        "protocol": plan.protocol_sha256 == sha256_file(protocol_path),
    }
    if not all(checks.values()):
        raise ValueError(f"execution plan hash mismatch: {checks}")
    formal_case_ids = {
        item.case_id for item in load_target_comparison(directory)
    }
    validation_cases, validation_responses = load_judge_validation(directory)
    validation_case_ids = {item.case_id for item in validation_cases}
    validation_pairs = {
        (item.case_id, item.response_id) for item in validation_responses
    }
    target_pairs = {
        (str(node.config_id), str(node.case_id))
        for node in plan.nodes
        if node.stage == ExecutionStage.TARGET_GENERATION
    }
    judge_pairs = {
        (str(node.config_id), str(node.case_id))
        for node in plan.nodes
        if node.stage == ExecutionStage.JUDGE_EVALUATION
    }
    expected_formal_pairs = {
        (config_id, case_id)
        for config_id in CONFIG_IDS
        for case_id in formal_case_ids
    }
    if target_pairs != expected_formal_pairs or judge_pairs != expected_formal_pairs:
        raise ValueError("execution plan formal case/config references are not frozen")
    actual_validation_pairs = {
        (str(node.case_id), str(node.probe_id))
        for node in plan.nodes
        if node.stage == ExecutionStage.JUDGE_VALIDATION
    }
    run_judge_validation = bool(
        load_scientific_protocol(protocol_path)
        .get("matrix", {})
        .get("run_judge_validation", True)
    )
    expected_validation_pairs = validation_pairs if run_judge_validation else set()
    if actual_validation_pairs != expected_validation_pairs:
        raise ValueError("execution plan Judge-validation references are not frozen")
    for node in plan.nodes:
        if node.stage in {
            ExecutionStage.TARGET_GENERATION,
            ExecutionStage.JUDGE_EVALUATION,
        } and node.case_id not in formal_case_ids:
            raise ValueError(f"unknown formal case ID in plan: {node.case_id}")
        if (
            node.stage == ExecutionStage.JUDGE_VALIDATION
            and node.case_id not in validation_case_ids
        ):
            raise ValueError(f"unknown Judge-validation case ID: {node.case_id}")
    return plan

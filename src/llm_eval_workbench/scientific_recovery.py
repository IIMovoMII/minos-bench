from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .hashing import sha256_file
from .scientific_plan import (
    build_execution_plan,
    create_immutable_plan,
    load_and_verify_plan,
)
from .scientific_schemas import ExecutionStage, ScientificExecutionPlan
from .scientific_store import ScientificExecutionStore, atomic_write_json

RECOVERY_STRATEGY_VERSION = "scientific-runtime-recovery-v1"


def _node_contract(plan: ScientificExecutionPlan) -> list[dict[str, Any]]:
    return [node.model_dump(mode="json") for node in plan.nodes]


def prepare_runtime_recovery(
    *,
    execution_root: str | Path,
    source_execution_id: str,
    recovery_execution_id: str,
    data_dir: str | Path,
    source_audit_path: str | Path,
    protocol_path: str | Path,
) -> dict[str, Any]:
    if source_execution_id == recovery_execution_id:
        raise ValueError("recovery execution must use a new execution ID")

    source_store = ScientificExecutionStore(execution_root, source_execution_id)
    source_state = source_store.load_state()
    if source_state is None or source_state.get("status") != "completed":
        raise RuntimeError("source scientific execution must be completed")
    source_plan = load_and_verify_plan(
        plan_path=source_store.plan_path,
        data_dir=data_dir,
        protocol_path=protocol_path,
    )

    recovery_store = ScientificExecutionStore(execution_root, recovery_execution_id)
    if recovery_store.directory.exists():
        raise FileExistsError("recovery execution directory already exists")
    recovery_plan = build_execution_plan(
        execution_id=recovery_execution_id,
        data_dir=data_dir,
        source_audit_path=source_audit_path,
        protocol_path=protocol_path,
    )
    if _node_contract(source_plan) != _node_contract(
        recovery_plan.model_copy(
            update={
                "execution_id": source_plan.execution_id,
                "created_at": source_plan.created_at,
            }
        )
    ):
        raise RuntimeError("source and recovery execution graphs differ")
    create_immutable_plan(execution_root=execution_root, plan=recovery_plan)

    recomputed_stages = {
        ExecutionStage.OFFLINE_GATE,
        ExecutionStage.TARGET_BARRIER,
        ExecutionStage.REPORT,
    }
    reused_node_ids: list[str] = []
    retry_node_ids: list[str] = []
    retry_nodes: list[dict[str, Any]] = []
    reused_at = datetime.now(UTC).isoformat()
    for node in source_plan.nodes:
        if node.stage in recomputed_stages:
            continue
        if not source_store.has_node(node.node_id):
            retry_node_ids.append(node.node_id)
            retry_nodes.append(
                {
                    "node_id": node.node_id,
                    "stage": node.stage.value,
                    "reason": "source_node_missing",
                    "planned_requests": node.planned_requests,
                }
            )
            continue
        artifact = source_store.load_node(node.node_id)
        if artifact.get("status") != "completed":
            retry_node_ids.append(node.node_id)
            retry_nodes.append(
                {
                    "node_id": node.node_id,
                    "stage": node.stage.value,
                    "reason": "source_runtime_error",
                    "planned_requests": node.planned_requests,
                    "safe_error_type": artifact.get("error", {}).get("error_type"),
                    "safe_error_classification": artifact.get("error", {}).get(
                        "classification"
                    ),
                }
            )
            continue
        reused = deepcopy(artifact)
        reused["source_actual_requests"] = int(reused.get("actual_requests", 0))
        reused["actual_requests"] = 0
        reused["recovery_provenance"] = {
            "strategy_version": RECOVERY_STRATEGY_VERSION,
            "source_execution_id": source_execution_id,
            "reused_at": reused_at,
        }
        recovery_store.write_node_once(node.node_id, reused)
        reused_node_ids.append(node.node_id)

    if not retry_node_ids:
        raise RuntimeError("source execution has no runtime errors to recover")

    manifest = {
        "strategy_version": RECOVERY_STRATEGY_VERSION,
        "source_execution_id": source_execution_id,
        "recovery_execution_id": recovery_execution_id,
        "created_at": reused_at,
        "source_plan_sha256": sha256_file(source_store.plan_path),
        "recovery_plan_sha256": sha256_file(recovery_store.plan_path),
        "reused_node_count": len(reused_node_ids),
        "retry_node_count": len(retry_node_ids),
        "expected_new_provider_requests_minimum": sum(
            int(item["planned_requests"]) for item in retry_nodes
        ),
        "retry_nodes": retry_nodes,
        "policy": {
            "successful_nodes_are_not_replayed": True,
            "source_artifacts_are_immutable": True,
            "runtime_errors_are_not_content_zeros": True,
            "contract_retry_only_until_first_valid_judgment": True,
        },
    }
    atomic_write_json(recovery_store.directory / "recovery_manifest.json", manifest)
    recovery_store.append_event(
        {
            "event": "runtime_recovery_prepared",
            "source_execution_id": source_execution_id,
            "reused_node_count": len(reused_node_ids),
            "retry_node_count": len(retry_node_ids),
            "at": reused_at,
        }
    )
    return manifest

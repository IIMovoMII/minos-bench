from __future__ import annotations

from pathlib import Path

from llm_eval_workbench.scientific_plan import (
    build_execution_plan,
    create_immutable_plan,
)
from llm_eval_workbench.scientific_recovery import prepare_runtime_recovery
from llm_eval_workbench.scientific_store import ScientificExecutionStore

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "datasets" / "scientific_v1"
PROTOCOL_PATH = PROJECT_ROOT / "configs" / "scientific_v1.json"
SOURCE_AUDIT = (
    PROJECT_ROOT.parents[1]
    / "research"
    / "PROJECT3_BENCHMARK_SOURCE_AUDIT_20260802.md"
)


def test_runtime_recovery_reuses_successes_and_retries_only_failures(
    tmp_path: Path,
) -> None:
    source_id = "scientific-source-runtime-errors"
    recovery_id = "scientific-recovery-runtime-errors"
    source_plan = build_execution_plan(
        execution_id=source_id,
        data_dir=DATA_DIR,
        source_audit_path=SOURCE_AUDIT,
        protocol_path=PROTOCOL_PATH,
    )
    create_immutable_plan(execution_root=tmp_path, plan=source_plan)
    source_store = ScientificExecutionStore(tmp_path, source_id)
    failed_ids = {
        "target--model_b_prompt_v1--CMP-ST-04",
        "judge--weak_prompt_v1--CMP-IG-02",
    }
    for node in source_plan.nodes:
        source_store.write_node_once(
            node.node_id,
            {
                "node_id": node.node_id,
                "stage": node.stage.value,
                "status": (
                    "runtime_error" if node.node_id in failed_ids else "completed"
                ),
                "actual_requests": node.planned_requests,
                "error": (
                    {
                        "error_type": "UnitRuntimeError",
                        "classification": "unit_runtime",
                    }
                    if node.node_id in failed_ids
                    else None
                ),
            },
        )
    source_store.write_state({"status": "completed"})

    manifest = prepare_runtime_recovery(
        execution_root=tmp_path,
        source_execution_id=source_id,
        recovery_execution_id=recovery_id,
        data_dir=DATA_DIR,
        source_audit_path=SOURCE_AUDIT,
        protocol_path=PROTOCOL_PATH,
    )

    assert manifest["retry_node_count"] == 2
    assert {item["node_id"] for item in manifest["retry_nodes"]} == failed_ids
    recovery_store = ScientificExecutionStore(tmp_path, recovery_id)
    for node_id in failed_ids:
        assert not recovery_store.has_node(node_id)
    reused_id = "target--model_a_prompt_v1--CMP-IG-01"
    reused = recovery_store.load_node(reused_id)
    assert reused["actual_requests"] == 0
    assert reused["source_actual_requests"] == 1
    assert reused["recovery_provenance"]["source_execution_id"] == source_id
    assert not recovery_store.has_node("machine-report")
    assert source_store.load_node(reused_id).get("recovery_provenance") is None

from __future__ import annotations

import json
from pathlib import Path

import pytest

from llm_eval_workbench.scientific_plan import (
    build_execution_plan,
    create_immutable_plan,
)
from llm_eval_workbench.scientific_probe_receipts import (
    PROBE_NODE_BY_SLOT,
    import_provider_probe_receipts,
)
from llm_eval_workbench.scientific_store import ScientificExecutionStore

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "datasets" / "scientific_v1"
PROTOCOL_PATH = PROJECT_ROOT / "configs" / "scientific_v1.json"
SOURCE_AUDIT = (
    PROJECT_ROOT.parents[1]
    / "research"
    / "PROJECT3_BENCHMARK_SOURCE_AUDIT_20260802.md"
)


def _receipt(protocol_sha256: str) -> dict[str, object]:
    return {
        "recorded_at": "2026-08-03T00:00:00Z",
        "protocol_sha256": protocol_sha256,
        "credentials_recorded": False,
        "model_identities_recorded": False,
        "receipts": [
            {
                "logical_slot": slot,
                "status": "completed",
                "requests_used_for_successful_probe": 1,
                "transport": "unit-test-transport",
            }
            for slot in PROBE_NODE_BY_SLOT
        ],
    }


def test_successful_provider_receipts_are_imported_without_requests(
    tmp_path: Path,
) -> None:
    root = tmp_path / "executions"
    execution_id = "receipt-import-v1"
    plan = build_execution_plan(
        execution_id=execution_id,
        data_dir=DATA_DIR,
        source_audit_path=SOURCE_AUDIT,
        protocol_path=PROTOCOL_PATH,
    )
    create_immutable_plan(execution_root=root, plan=plan)
    receipt_path = tmp_path / "receipt.json"
    receipt_path.write_text(
        json.dumps(_receipt(plan.protocol_sha256)),
        encoding="utf-8",
    )
    store = ScientificExecutionStore(root, execution_id)

    written = import_provider_probe_receipts(
        store=store,
        receipt_path=receipt_path,
    )

    assert len(written) == 4
    assert store.load_state() is None
    for slot, node_id in PROBE_NODE_BY_SLOT.items():
        artifact = store.load_node(node_id)
        assert artifact["probe_id"] == slot
        assert artifact["actual_requests"] == 0
        assert artifact["probe"]["probe_reused"] is True


def test_provider_receipt_protocol_mismatch_is_rejected(tmp_path: Path) -> None:
    root = tmp_path / "executions"
    execution_id = "receipt-mismatch-v1"
    plan = build_execution_plan(
        execution_id=execution_id,
        data_dir=DATA_DIR,
        source_audit_path=SOURCE_AUDIT,
        protocol_path=PROTOCOL_PATH,
    )
    create_immutable_plan(execution_root=root, plan=plan)
    receipt_path = tmp_path / "receipt.json"
    receipt_path.write_text(
        json.dumps(_receipt("0" * 64)),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="protocol hash"):
        import_provider_probe_receipts(
            store=ScientificExecutionStore(root, execution_id),
            receipt_path=receipt_path,
        )

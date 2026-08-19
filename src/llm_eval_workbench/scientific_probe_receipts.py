from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .scientific_schemas import ExecutionStage, ScientificExecutionPlan
from .scientific_store import ScientificExecutionStore

PROBE_NODE_BY_SLOT = {
    "model_a": "provider-probe-model-a",
    "model_b": "provider-probe-model-b",
    "weak_model": "provider-probe-weak",
    "judge": "provider-probe-judge",
}


def import_provider_probe_receipts(
    *,
    store: ScientificExecutionStore,
    receipt_path: str | Path,
) -> list[Path]:
    """Reuse successful slot probes without issuing duplicate health requests."""
    if not store.plan_path.is_file():
        raise FileNotFoundError("scientific execution plan must exist before import")
    if store.load_state() is not None or store.all_node_artifacts():
        raise ValueError(
            "provider probe receipts must be imported before execution starts"
        )

    plan = ScientificExecutionPlan.model_validate_json(
        store.plan_path.read_text(encoding="utf-8")
    )
    value = json.loads(Path(receipt_path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("provider probe receipt must be a JSON object")
    if value.get("credentials_recorded") is not False:
        raise ValueError("provider probe receipt must not record credentials")
    if value.get("model_identities_recorded") is not False:
        raise ValueError("provider probe receipt must hide model identities")
    receipt_protocol = str(value.get("protocol_sha256", "")).casefold()
    if receipt_protocol != plan.protocol_sha256.casefold():
        raise ValueError("provider probe receipt protocol hash does not match plan")

    records = value.get("receipts")
    if not isinstance(records, list):
        raise ValueError("provider probe receipt list is missing")
    indexed: dict[str, dict[str, Any]] = {}
    for record in records:
        if not isinstance(record, dict):
            raise ValueError("provider probe receipt entry must be an object")
        slot = str(record.get("logical_slot", ""))
        if slot in indexed:
            raise ValueError(f"duplicate provider probe receipt slot: {slot}")
        indexed[slot] = record
    if set(indexed) != set(PROBE_NODE_BY_SLOT):
        raise ValueError(
            "provider probe receipts must cover exactly four logical slots"
        )

    plan_nodes = {node.node_id: node for node in plan.nodes}
    written: list[Path] = []
    for slot, node_id in PROBE_NODE_BY_SLOT.items():
        record = indexed[slot]
        if record.get("status") != "completed":
            raise ValueError(f"provider probe receipt is not successful: {slot}")
        successful_requests = record.get("requests_used_for_successful_probe")
        if not isinstance(successful_requests, int) or successful_requests < 1:
            raise ValueError(f"provider probe request count is invalid: {slot}")
        node = plan_nodes.get(node_id)
        if (
            node is None
            or node.stage != ExecutionStage.PROVIDER_PROBE
            or node.probe_id != slot
        ):
            raise ValueError(f"execution plan provider node mismatch: {slot}")
        probe = {
            "provider_status": "completed",
            "probe_reused": True,
            "successful_probe_requests": successful_requests,
            "transport": record.get("transport"),
            "source_receipt": Path(receipt_path).name,
        }
        for optional in ("latency_ms", "auth_contract"):
            if optional in record:
                probe[optional] = record[optional]
        artifact = {
            "node_id": node.node_id,
            "stage": node.stage.value,
            "config_id": None,
            "case_id": None,
            "probe_id": node.probe_id,
            "completed_at": value.get("recorded_at"),
            "status": "completed",
            "actual_requests": 0,
            "probe": probe,
        }
        written.append(store.write_node_once(node.node_id, artifact))
    return written

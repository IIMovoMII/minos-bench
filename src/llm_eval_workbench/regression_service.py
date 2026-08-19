from __future__ import annotations

import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .dataset_service import dataset_hash, load_jsonl
from .hashing import sha256_file
from .result_store import ResultStore
from .review_service import latest_reviews
from .schemas import DataSplit, EvaluationCase, ReviewDecision


def _atomic_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(value, encoding="utf-8")
    os.replace(temporary, path)


def _atomic_json(path: Path, value: Any) -> None:
    _atomic_text(
        path,
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True),
    )


def _snapshots(regression_dir: Path) -> list[tuple[int, Path]]:
    values: list[tuple[int, Path]] = []
    for path in regression_dir.glob("regression_v*.jsonl"):
        matched = re.fullmatch(r"regression_v(\d{3})\.jsonl", path.name)
        if matched:
            values.append((int(matched.group(1)), path))
    return sorted(values)


def _serialize_cases(cases: list[EvaluationCase]) -> str:
    return "".join(
        case.model_dump_json(exclude_none=False) + "\n"
        for case in sorted(cases, key=lambda item: item.case_id)
    )


def promote_case_to_regression(
    *,
    regression_dir: str | Path,
    store: ResultStore,
    run_id: str,
    case: EvaluationCase,
    reason: str,
) -> dict[str, Any]:
    if not reason.strip():
        raise ValueError("Regression promotion requires a reason")
    reviews = latest_reviews(store, run_id)
    review = reviews.get(case.case_id)
    if review is None or review.decision != ReviewDecision.FAIL:
        raise ValueError("A latest human FAIL review is required before promotion")
    result = store.result_by_case(run_id).get(case.case_id)
    output = store.output_by_case(run_id).get(case.case_id)
    if result is None or output is None:
        raise LookupError("Source result and output are required")

    target_dir = Path(regression_dir).resolve()
    target_dir.mkdir(parents=True, exist_ok=True)
    snapshots = _snapshots(target_dir)
    previous_version, previous_path = snapshots[-1] if snapshots else (0, None)
    existing = load_jsonl(previous_path) if previous_path else []
    source_ids = {
        str(item.metadata.get("regression_origin", {}).get("source_case_id"))
        for item in existing
    }
    if case.case_id in source_ids:
        raise ValueError(f"{case.case_id} is already in the regression set")

    next_version = previous_version + 1
    used_numbers = [
        int(item.case_id.split("-")[1])
        for item in existing
        if re.fullmatch(r"RG-\d{3}", item.case_id)
    ]
    regression_case_id = f"RG-{max(used_numbers, default=0) + 1:03d}"
    now = datetime.now(UTC)
    regression_case = case.model_copy(
        update={
            "case_id": regression_case_id,
            "split": DataSplit.REGRESSION,
            "version": f"regression-{next_version:03d}",
            "metadata": {
                **case.metadata,
                "regression_origin": {
                    "source_case_id": case.case_id,
                    "source_run_id": run_id,
                    "source_output_hash": output.output_hash,
                    "machine_status": result.status.value,
                    "human_review_id": review.review_id,
                    "human_decision": review.decision.value,
                    "issue_categories": [
                        category.value for category in review.issue_categories
                    ],
                    "reason": reason.strip(),
                    "promoted_at": now.isoformat(),
                },
            },
        }
    )
    updated = [*existing, regression_case]
    snapshot_path = target_dir / f"regression_v{next_version:03d}.jsonl"
    current_path = target_dir / "current.jsonl"
    serialized = _serialize_cases(updated)
    _atomic_text(snapshot_path, serialized)
    _atomic_text(current_path, serialized)

    metadata = {
        "status": "frozen",
        "version": next_version,
        "created_at": now.isoformat(),
        "parent_snapshot": previous_path.name if previous_path else None,
        "snapshot": snapshot_path.name,
        "current_pointer": current_path.name,
        "case_count": len(updated),
        "dataset_hash": dataset_hash(updated),
        "file_sha256": sha256_file(snapshot_path),
        "added_case_id": regression_case_id,
        "source_case_id": case.case_id,
        "source_run_id": run_id,
        "human_review_id": review.review_id,
    }
    metadata_path = target_dir / f"regression_v{next_version:03d}.meta.json"
    _atomic_json(metadata_path, metadata)
    return {
        **metadata,
        "snapshot_path": str(snapshot_path),
        "metadata_path": str(metadata_path),
    }

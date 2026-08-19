from __future__ import annotations

import json
from collections import Counter, defaultdict
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path

from .hashing import sha256_file, sha256_records, sha256_value
from .schemas import DataSplit, EvaluationCase, Language, TaskPack


def load_jsonl(path: str | Path) -> list[EvaluationCase]:
    source = Path(path)
    cases: list[EvaluationCase] = []
    with source.open("r", encoding="utf-8") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                cases.append(EvaluationCase.model_validate_json(line))
            except Exception as error:
                raise ValueError(
                    f"{source.name}:{line_number}: invalid evaluation case"
                ) from error
    ensure_unique_case_ids(cases)
    return cases


def load_many(paths: Iterable[str | Path]) -> list[EvaluationCase]:
    cases: list[EvaluationCase] = []
    for path in paths:
        cases.extend(load_jsonl(path))
    ensure_unique_case_ids(cases)
    return cases


def ensure_unique_case_ids(cases: Iterable[EvaluationCase]) -> None:
    counts = Counter(case.case_id for case in cases)
    duplicates = sorted(case_id for case_id, count in counts.items() if count > 1)
    if duplicates:
        raise ValueError(f"Duplicate case IDs: {', '.join(duplicates)}")


def dataset_hash(cases: Iterable[EvaluationCase]) -> str:
    return sha256_records(sorted(cases, key=lambda case: case.case_id))


def audit_dataset(
    cases: list[EvaluationCase],
    *,
    require_frozen_contract: bool = False,
) -> dict[str, object]:
    ensure_unique_case_ids(cases)
    task_counts = Counter(case.task_pack.value for case in cases)
    split_counts = Counter(case.split.value for case in cases)
    language_counts = Counter(case.language.value for case in cases)
    source_counts = Counter(case.source.type for case in cases)
    errors: list[str] = []

    for case in cases:
        if not case.source.license.strip():
            errors.append(f"{case.case_id}: missing source license")
        if not case.source.reference.strip():
            errors.append(f"{case.case_id}: missing source reference")

    if require_frozen_contract:
        expected_tasks = {pack.value: 10 for pack in TaskPack}
        if dict(task_counts) != expected_tasks:
            errors.append(
                f"task distribution must be {expected_tasks}, got {dict(task_counts)}"
            )
        expected_splits = {
            DataSplit.DEVELOPMENT.value: 32,
            DataSplit.HOLDOUT.value: 8,
        }
        if dict(split_counts) != expected_splits:
            errors.append(
                "split distribution must be "
                f"{expected_splits}, got {dict(split_counts)}"
            )
        expected_languages = {
            Language.CHINESE.value: 36,
            Language.ENGLISH.value: 4,
        }
        if dict(language_counts) != expected_languages:
            errors.append(
                "language distribution must be "
                f"{expected_languages}, got {dict(language_counts)}"
            )
        per_pack_split: dict[str, Counter[str]] = defaultdict(Counter)
        for case in cases:
            per_pack_split[case.task_pack.value][case.split.value] += 1
        for pack in TaskPack:
            counts = per_pack_split[pack.value]
            if counts[DataSplit.DEVELOPMENT.value] != 8:
                errors.append(f"{pack.value}: development count must be 8")
            if counts[DataSplit.HOLDOUT.value] != 2:
                errors.append(f"{pack.value}: holdout count must be 2")

    return {
        "valid": not errors,
        "errors": errors,
        "case_count": len(cases),
        "task_counts": dict(sorted(task_counts.items())),
        "split_counts": dict(sorted(split_counts.items())),
        "language_counts": dict(sorted(language_counts.items())),
        "source_counts": dict(sorted(source_counts.items())),
        "dataset_hash": dataset_hash(cases),
    }


def create_holdout_seal(
    holdout_path: str | Path, output_path: str | Path
) -> dict[str, object]:
    source = Path(holdout_path)
    cases = load_jsonl(source)
    if any(case.split != DataSplit.HOLDOUT for case in cases):
        raise ValueError("Holdout seal can contain only holdout cases")
    payload = {
        "status": "sealed",
        "case_count": len(cases),
        "case_ids_hash": sha256_value(sorted(case.case_id for case in cases)),
        "file_sha256": sha256_file(source),
        "dataset_hash": dataset_hash(cases),
        "sealed_at": datetime.now(UTC).isoformat(),
    }
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(target)
    return payload


def verify_holdout_seal(
    holdout_path: str | Path, seal_path: str | Path
) -> dict[str, object]:
    source = Path(holdout_path)
    seal = json.loads(Path(seal_path).read_text(encoding="utf-8"))
    current_cases = load_jsonl(source)
    checks = {
        "file_sha256": sha256_file(source) == seal.get("file_sha256"),
        "dataset_hash": dataset_hash(current_cases) == seal.get("dataset_hash"),
        "case_count": len(current_cases) == seal.get("case_count"),
        "case_ids_hash": sha256_value(sorted(case.case_id for case in current_cases))
        == seal.get("case_ids_hash"),
    }
    if not all(checks.values()):
        raise ValueError(f"Holdout seal mismatch: {checks}")
    return {"valid": True, "checks": checks, **seal}

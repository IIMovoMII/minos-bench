from __future__ import annotations

import json
import os
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel

from .hashing import sha256_file, sha256_value
from .schemas import TaskPack
from .scientific_schemas import (
    AtomicDecision,
    DataUse,
    JudgeValidationResponse,
    ScientificCase,
    ScientificDatasetManifest,
    ScientificDatasetSeal,
    SourceLedgerEntry,
    SourceType,
)

T = TypeVar("T", bound=BaseModel)

CONTENT_FILES = (
    "source_ledger.jsonl",
    "rule_development.jsonl",
    "technical_probes.jsonl",
    "judge_validation_cases.jsonl",
    "judge_validation_responses.jsonl",
    "target_comparison.jsonl",
    "regression.jsonl",
)
CASE_FILES = (
    "rule_development.jsonl",
    "technical_probes.jsonl",
    "judge_validation_cases.jsonl",
    "target_comparison.jsonl",
    "regression.jsonl",
)


def _load_jsonl(path: Path, model: type[T]) -> list[T]:
    values: list[T] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                values.append(model.model_validate_json(line))
            except Exception as error:
                raise ValueError(
                    f"{path.name}:{line_number}: invalid record"
                ) from error
    return values


def load_scientific_cases(data_dir: str | Path) -> list[ScientificCase]:
    directory = Path(data_dir)
    values: list[ScientificCase] = []
    for name in CASE_FILES:
        values.extend(_load_jsonl(directory / name, ScientificCase))
    return values


def load_target_comparison(data_dir: str | Path) -> list[ScientificCase]:
    return _load_jsonl(Path(data_dir) / "target_comparison.jsonl", ScientificCase)


def load_judge_validation(
    data_dir: str | Path,
) -> tuple[list[ScientificCase], list[JudgeValidationResponse]]:
    directory = Path(data_dir)
    return (
        _load_jsonl(directory / "judge_validation_cases.jsonl", ScientificCase),
        _load_jsonl(
            directory / "judge_validation_responses.jsonl",
            JudgeValidationResponse,
        ),
    )


def ledger_entry_for_case(case: ScientificCase) -> SourceLedgerEntry:
    source = case.source
    return SourceLedgerEntry(
        case_id=case.case_id,
        task_pack=case.task_pack,
        capability=case.capability,
        user_goal=case.user_goal,
        failure_behavior=case.failure_behavior,
        severity=case.severity,
        test_type=case.test_type,
        source_type=source.source_type,
        source_name=source.source_name,
        paper_url=source.paper_url,
        repository_url=source.repository_url,
        original_case_id_or_method=source.original_case_id_or_method,
        license=source.license,
        adaptation_note=source.adaptation_note,
        data_use=case.data_use,
        scenario_family=case.scenario_family,
        version=case.version,
        applicability=case.applicability,
        judgment_authority=case.judgment_authority,
        evidence=case.evidence,
        risk_cell=case.risk_cell,
        difficulty=case.difficulty,
        difficulty_rationale=case.difficulty_rationale,
        checker_boundary=case.checker_boundary,
    )


def _manifest_payload(
    *,
    data_dir: Path,
    source_audit_path: Path,
    created_at: datetime,
    dataset_version: str = "scientific-v1.0",
    source_audit_version: str = "2026-08-02",
    source_audit_record_path: str = (
        "research/PROJECT3_BENCHMARK_SOURCE_AUDIT_20260802.md"
    ),
    source_audit_sha256: str | None = None,
) -> ScientificDatasetManifest:
    cases = load_scientific_cases(data_dir)
    validation_cases, validation_responses = load_judge_validation(data_dir)
    target_cases = [
        case for case in cases if case.data_use == DataUse.TARGET_COMPARISON
    ]
    task_distribution = Counter(case.task_pack.value for case in target_cases)
    data_use_distribution = Counter(case.data_use.value for case in cases)
    is_v2 = dataset_version.startswith("scientific-v2")
    difficulty_distribution = Counter(
        case.difficulty for case in target_cases if case.difficulty is not None
    )
    risk_cell_distribution = Counter(
        case.risk_cell for case in target_cases if case.risk_cell is not None
    )
    return ScientificDatasetManifest(
        schema_version=(
            "scientific-dataset-v2" if is_v2 else "scientific-dataset-v1"
        ),
        dataset_version=dataset_version,
        created_at=created_at,
        source_audit_version=source_audit_version,
        source_audit_path=source_audit_record_path,
        source_audit_sha256=(
            source_audit_sha256 or sha256_file(source_audit_path)
        ),
        schema_module="llm_eval_workbench.scientific_schemas",
        file_sha256={name: sha256_file(data_dir / name) for name in CONTENT_FILES},
        counts={
            "all_questions": len(cases),
            "rule_development": data_use_distribution[DataUse.RULE_DEVELOPMENT.value],
            "technical_probes": data_use_distribution[DataUse.TECHNICAL_PROBES.value],
            "judge_validation_families": len(validation_cases),
            "judge_validation_responses": len(validation_responses),
            "target_comparison": len(target_cases),
            "regression": data_use_distribution[DataUse.REGRESSION.value],
        },
        task_pack_distribution=dict(sorted(task_distribution.items())),
        data_use_distribution=dict(sorted(data_use_distribution.items())),
        excluded_source_types=[SourceType.SYNTHETIC_DRAFT],
        difficulty_distribution=(
            dict(sorted(difficulty_distribution.items())) if is_v2 else None
        ),
        risk_cell_distribution=(
            dict(sorted(risk_cell_distribution.items())) if is_v2 else None
        ),
    )


def _atomic_json(path: Path, value: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, default=str),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def write_manifest_and_seal(
    *,
    data_dir: str | Path,
    source_audit_path: str | Path,
    timestamp: datetime | None = None,
    dataset_version: str = "scientific-v1.0",
    source_audit_version: str = "2026-08-02",
) -> tuple[ScientificDatasetManifest, ScientificDatasetSeal]:
    directory = Path(data_dir)
    created_at = timestamp or datetime.now(UTC)
    manifest = _manifest_payload(
        data_dir=directory,
        source_audit_path=Path(source_audit_path),
        created_at=created_at,
        dataset_version=dataset_version,
        source_audit_version=source_audit_version,
    )
    manifest_path = directory / "manifest.json"
    _atomic_json(manifest_path, manifest.model_dump(mode="json"))
    cases = load_scientific_cases(directory)
    seal = ScientificDatasetSeal(
        seal_version=(
            "scientific-dataset-seal-v2"
            if dataset_version.startswith("scientific-v2")
            else "scientific-dataset-seal-v1"
        ),
        dataset_version=manifest.dataset_version,
        sealed_at=created_at,
        manifest_sha256=sha256_file(manifest_path),
        aggregate_content_sha256=sha256_value(manifest.file_sha256),
        case_ids_sha256=sha256_value(sorted(case.case_id for case in cases)),
        source_audit_sha256=manifest.source_audit_sha256,
    )
    _atomic_json(directory / "seal.json", seal.model_dump(mode="json"))
    return manifest, seal


def _validate_judge_responses(
    cases: list[ScientificCase],
    responses: list[JudgeValidationResponse],
) -> list[str]:
    errors: list[str] = []
    by_id = {case.case_id: case for case in cases}
    grouped: dict[str, list[JudgeValidationResponse]] = defaultdict(list)
    for response in responses:
        grouped[response.case_id].append(response)
        case = by_id.get(response.case_id)
        if case is None:
            errors.append(f"{response.response_id}: unknown Judge-validation case")
            continue
        if response.scenario_family != case.scenario_family:
            errors.append(f"{response.response_id}: scenario family mismatch")
        expected_ids = {item.criterion_id for item in case.semantic_criteria}
        if set(response.expected_criterion_decisions) != expected_ids:
            errors.append(f"{response.response_id}: criterion reference set mismatch")
        decisions = set(response.expected_criterion_decisions.values())
        expected_overall = "FAIL" if AtomicDecision.FAIL in decisions else "PASS"
        if response.expected_decision != expected_overall:
            errors.append(f"{response.response_id}: overall reference mismatch")
    for case in cases:
        family_responses = grouped.get(case.case_id, [])
        labels = Counter(item.expected_decision for item in family_responses)
        if len(family_responses) != 2 or labels != {"PASS": 1, "FAIL": 1}:
            errors.append(f"{case.case_id}: requires one PASS and one FAIL response")
    return errors


def audit_scientific_dataset(
    *,
    data_dir: str | Path,
    source_audit_path: str | Path,
    verify_seal: bool = True,
) -> dict[str, Any]:
    directory = Path(data_dir)
    audit_path = Path(source_audit_path)
    errors: list[str] = []
    for name in CONTENT_FILES:
        if not (directory / name).is_file():
            errors.append(f"missing data file: {name}")
    if errors:
        return {"valid": False, "errors": errors, "provider_requests": 0}

    try:
        cases = load_scientific_cases(directory)
        ledger = _load_jsonl(directory / "source_ledger.jsonl", SourceLedgerEntry)
        validation_cases, validation_responses = load_judge_validation(directory)
    except ValueError as error:
        return {
            "valid": False,
            "errors": [str(error)],
            "provider_requests": 0,
        }

    ids = [case.case_id for case in cases]
    duplicate_ids = sorted(
        case_id for case_id, count in Counter(ids).items() if count > 1
    )
    if duplicate_ids:
        errors.append(f"duplicate case IDs: {duplicate_ids}")
    ledger_ids = [entry.case_id for entry in ledger]
    if len(ledger_ids) != len(set(ledger_ids)):
        errors.append("source ledger contains duplicate case IDs")
    if set(ledger_ids) != set(ids):
        errors.append("source ledger case IDs do not match question files")
    ledger_by_id = {entry.case_id: entry for entry in ledger}
    for case in cases:
        expected = ledger_entry_for_case(case)
        actual = ledger_by_id.get(case.case_id)
        if actual is not None and actual != expected:
            errors.append(f"{case.case_id}: source ledger fields differ from case")
        if case.source.source_type == SourceType.SYNTHETIC_DRAFT:
            errors.append(f"{case.case_id}: synthetic_draft cannot enter scientific_v1")

    target_cases = [
        case for case in cases if case.data_use == DataUse.TARGET_COMPARISON
    ]
    manifest_path = directory / "manifest.json"
    dataset_version = ""
    if manifest_path.is_file():
        try:
            manifest_header = ScientificDatasetManifest.model_validate_json(
                manifest_path.read_text(encoding="utf-8")
            )
            dataset_version = manifest_header.dataset_version
        except (OSError, ValueError):
            pass
    is_v2 = dataset_version.startswith("scientific-v2") or (
        bool(target_cases)
        and all(case.version.startswith("2") for case in target_cases)
    )
    expected_distribution = (
        {
            TaskPack.INSTRUCTION_GENERATION.value: 6,
            TaskPack.GROUNDED_QA.value: 6,
            TaskPack.MULTI_TURN.value: 6,
            TaskPack.STRUCTURED_TOOL.value: 6,
        }
        if is_v2
        else {
            TaskPack.INSTRUCTION_GENERATION.value: 6,
            TaskPack.GROUNDED_QA.value: 7,
            TaskPack.MULTI_TURN.value: 5,
            TaskPack.STRUCTURED_TOOL.value: 7,
        }
    )
    actual_distribution = Counter(case.task_pack.value for case in target_cases)
    expected_target_count = 24 if is_v2 else 25
    if len(target_cases) != expected_target_count:
        errors.append(
            "target comparison count must be "
            f"{expected_target_count}, got {len(target_cases)}"
        )
    if dict(actual_distribution) != expected_distribution:
        errors.append(
            "target comparison distribution must be "
            f"{expected_distribution}, got {dict(actual_distribution)}"
        )
    use_counts = Counter(case.data_use for case in cases)
    required_use_counts = {
        DataUse.RULE_DEVELOPMENT: 3,
        DataUse.TECHNICAL_PROBES: 2,
        DataUse.JUDGE_VALIDATION: 7,
        DataUse.TARGET_COMPARISON: expected_target_count,
        DataUse.REGRESSION: 1,
    }
    if use_counts != Counter(required_use_counts):
        errors.append(
            "data-use distribution mismatch: "
            f"expected {dict(required_use_counts)}, got {dict(use_counts)}"
        )

    family_uses: dict[str, set[DataUse]] = defaultdict(set)
    for case in cases:
        family_uses[case.scenario_family].add(case.data_use)
    leaked = sorted(family for family, uses in family_uses.items() if len(uses) > 1)
    if leaked:
        errors.append(f"scenario families cross data uses: {leaked}")

    if len(validation_cases) != 7:
        errors.append("Judge validation requires exactly 7 families")
    if len(validation_responses) != 14:
        errors.append("Judge validation requires exactly 14 fixed responses")
    errors.extend(_validate_judge_responses(validation_cases, validation_responses))

    if is_v2:
        risk_counts = Counter(case.risk_cell for case in target_cases)
        difficulty_counts = Counter(case.difficulty for case in target_cases)
        if len(risk_counts) != 12 or set(risk_counts.values()) != {2}:
            errors.append(
                "scientific v2 requires 12 risk cells with exactly 2 cases each"
            )
        if difficulty_counts != {"D2": 12, "D3": 12}:
            errors.append(
                "scientific v2 difficulty distribution must be D2=12 and D3=12"
            )
        if len({case.scenario_family for case in target_cases}) != len(target_cases):
            errors.append("scientific v2 comparison scenario families must be unique")
        for case in target_cases:
            if not all(
                [
                    case.risk_cell,
                    case.difficulty,
                    case.difficulty_rationale,
                    case.counterexample,
                    case.checker_boundary,
                ]
            ):
                errors.append(f"{case.case_id}: scientific v2 metadata incomplete")
            if not case.gold_answer and not case.gold_tool_calls:
                errors.append(f"{case.case_id}: scientific v2 gold is missing")

    manifest_valid = False
    seal_valid = False
    source_audit_current_match = False
    if verify_seal:
        try:
            seal_path = directory / "seal.json"
            manifest = ScientificDatasetManifest.model_validate_json(
                manifest_path.read_text(encoding="utf-8")
            )
            seal = ScientificDatasetSeal.model_validate_json(
                seal_path.read_text(encoding="utf-8")
            )
            expected_manifest = _manifest_payload(
                data_dir=directory,
                source_audit_path=audit_path,
                created_at=manifest.created_at,
                dataset_version=manifest.dataset_version,
                source_audit_version=manifest.source_audit_version,
                source_audit_record_path=manifest.source_audit_path,
                source_audit_sha256=manifest.source_audit_sha256,
            )
            manifest_valid = manifest == expected_manifest
            if not manifest_valid:
                errors.append("manifest content or file hashes do not match")
            seal_valid = (
                seal.manifest_sha256 == sha256_file(manifest_path)
                and seal.aggregate_content_sha256 == sha256_value(manifest.file_sha256)
                and seal.case_ids_sha256 == sha256_value(sorted(ids))
                and seal.source_audit_sha256 == manifest.source_audit_sha256
                and seal.dataset_version == manifest.dataset_version
            )
            if not seal_valid:
                errors.append("dataset seal does not match current content")
            source_audit_current_match = (
                manifest.source_audit_sha256 == sha256_file(audit_path)
            )
            if is_v2 and not source_audit_current_match:
                errors.append("active scientific v2 source audit hash is stale")
        except (OSError, ValueError) as error:
            errors.append(f"manifest/seal validation failed: {type(error).__name__}")

    return {
        "valid": not errors,
        "errors": errors,
        "provider_requests": 0,
        "case_count": len(cases),
        "target_comparison_count": len(target_cases),
        "task_pack_distribution": dict(sorted(actual_distribution.items())),
        "data_use_distribution": {
            key.value: value
            for key, value in sorted(use_counts.items(), key=lambda item: item[0].value)
        },
        "judge_validation_responses": len(validation_responses),
        "manifest_valid": manifest_valid,
        "seal_valid": seal_valid,
        "source_audit_current_match": source_audit_current_match,
    }

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

import pytest
from pydantic import ValidationError

from llm_eval_workbench.scientific_data import (
    audit_scientific_dataset,
    load_judge_validation,
    load_scientific_cases,
    load_target_comparison,
)
from llm_eval_workbench.scientific_schemas import (
    DataUse,
    ScientificSource,
    SourceType,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "datasets" / "scientific_v1"
SOURCE_AUDIT = (
    PROJECT_ROOT.parents[1]
    / "research"
    / "PROJECT3_BENCHMARK_SOURCE_AUDIT_20260802.md"
)


def test_scientific_v1_data_contract_is_sealed_and_offline() -> None:
    audit = audit_scientific_dataset(
        data_dir=DATA_DIR,
        source_audit_path=SOURCE_AUDIT,
        verify_seal=True,
    )
    assert audit["valid"] is True
    assert audit["provider_requests"] == 0
    assert audit["case_count"] == 38
    assert audit["target_comparison_count"] == 25
    assert audit["judge_validation_responses"] == 14
    assert audit["task_pack_distribution"] == {
        "grounded_qa": 7,
        "instruction_generation": 6,
        "multi_turn": 5,
        "structured_tool": 7,
    }
    assert audit["manifest_valid"] is True
    assert audit["seal_valid"] is True


def test_data_uses_and_scenario_families_do_not_leak() -> None:
    cases = load_scientific_cases(DATA_DIR)
    counts = Counter(item.data_use for item in cases)
    assert counts == {
        DataUse.RULE_DEVELOPMENT: 3,
        DataUse.TECHNICAL_PROBES: 2,
        DataUse.JUDGE_VALIDATION: 7,
        DataUse.TARGET_COMPARISON: 25,
        DataUse.REGRESSION: 1,
    }
    family_uses: dict[str, set[DataUse]] = defaultdict(set)
    for item in cases:
        family_uses[item.scenario_family].add(item.data_use)
        assert item.source.source_type != SourceType.SYNTHETIC_DRAFT
    assert all(len(values) == 1 for values in family_uses.values())


def test_every_question_has_required_source_and_atomic_fields() -> None:
    cases = load_scientific_cases(DATA_DIR)
    assert len({item.case_id for item in cases}) == len(cases)
    for item in cases:
        assert item.capability
        assert item.user_goal
        assert item.failure_behavior
        assert item.test_type
        assert item.source.paper_url
        assert item.source.repository_url
        assert item.source.original_case_id_or_method
        assert item.source.license
        assert item.source.adaptation_note
        assert item.applicability
        assert item.judgment_authority
        assert item.evidence
        for criterion in item.semantic_criteria:
            assert criterion.pass_condition
            assert criterion.fail_condition
            assert criterion.abstain_condition
            assert criterion.not_applicable_condition
            assert criterion.positive_example
            assert criterion.negative_example


def test_unlicensed_source_cannot_be_directly_adapted() -> None:
    with pytest.raises(ValidationError, match="method_transfer"):
        ScientificSource(
            source_type=SourceType.LICENSED_ADAPTATION,
            source_name="Unlicensed source",
            paper_url="https://example.test/paper",
            repository_url="https://example.test/repo",
            original_case_id_or_method="case-1",
            license="undeclared",
            adaptation_note="invalid direct adaptation",
        )


def test_judge_validation_has_pass_fail_pair_and_candidate_reference() -> None:
    cases, responses = load_judge_validation(DATA_DIR)
    assert len(cases) == 7
    assert len(responses) == 14
    grouped: dict[str, list[str]] = defaultdict(list)
    targets: set[str] = set()
    for item in responses:
        grouped[item.case_id].append(item.expected_decision)
        targets.update(item.validation_targets)
        assert item.reference_authority == "candidate_reference"
        assert item.reference_version == "candidate-reference-v1"
        assert item.reference_status == "candidate_approved_direction"
    assert all(sorted(labels) == ["FAIL", "PASS"] for labels in grouped.values())
    assert {
        "severity_misplacement",
        "false_positive",
        "false_certainty_on_insufficient_evidence",
        "evasive_abstention_with_sufficient_evidence",
        "citation_mismatch",
        "stale_version_use",
        "reference_path_bias",
        "environment_state_mismatch",
    } <= targets


def test_manifest_has_hashes_for_every_scientific_content_file() -> None:
    manifest = json.loads((DATA_DIR / "manifest.json").read_text(encoding="utf-8"))
    assert set(manifest["file_sha256"]) == {
        "source_ledger.jsonl",
        "rule_development.jsonl",
        "technical_probes.jsonl",
        "judge_validation_cases.jsonl",
        "judge_validation_responses.jsonl",
        "target_comparison.jsonl",
        "regression.jsonl",
    }
    assert manifest["source_audit_version"] == "2026-08-02"
    assert manifest["schema_version"] == "scientific-dataset-v1"
    assert len(load_target_comparison(DATA_DIR)) == 25

from __future__ import annotations

from llm_eval_workbench.dataset_service import (
    audit_dataset,
    load_jsonl,
    load_many,
    verify_holdout_seal,
)
from llm_eval_workbench.schemas import DataSplit, Language


def test_frozen_dataset_contract(project_root):
    cases = load_many(
        [
            project_root / "datasets/development/cases.jsonl",
            project_root / "datasets/holdout/cases.jsonl",
        ]
    )
    audit = audit_dataset(cases, require_frozen_contract=True)
    assert audit["valid"] is True
    assert audit["case_count"] == 40
    assert audit["split_counts"] == {"development": 32, "holdout": 8}
    assert audit["language_counts"] == {"en": 4, "zh-CN": 36}
    assert audit["source_counts"] == {"public": 4, "synthetic": 36}


def test_english_cases_are_licensed_public_sources(project_root):
    cases = load_many(
        [
            project_root / "datasets/development/cases.jsonl",
            project_root / "datasets/holdout/cases.jsonl",
        ]
    )
    english = [case for case in cases if case.language == Language.ENGLISH]
    assert len(english) == 4
    assert all(case.source.type == "public" for case in english)
    assert all(case.source.license == "MIT" for case in english)
    assert len({case.task_pack for case in english}) == 4


def test_development_and_holdout_pack_distribution(project_root):
    cases = load_many(
        [
            project_root / "datasets/development/cases.jsonl",
            project_root / "datasets/holdout/cases.jsonl",
        ]
    )
    for pack in {case.task_pack for case in cases}:
        pack_cases = [case for case in cases if case.task_pack == pack]
        assert sum(case.split == DataSplit.DEVELOPMENT for case in pack_cases) == 8
        assert sum(case.split == DataSplit.HOLDOUT for case in pack_cases) == 2


def test_holdout_seal_matches(project_root):
    verification = verify_holdout_seal(
        project_root / "datasets/holdout/cases.jsonl",
        project_root / "datasets/holdout/seal.json",
    )
    assert verification["valid"] is True
    assert verification["case_count"] == 8


def test_development_file_contains_no_holdout(project_root):
    cases = load_jsonl(project_root / "datasets/development/cases.jsonl")
    assert all(case.split == DataSplit.DEVELOPMENT for case in cases)

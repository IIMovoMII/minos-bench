from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from llm_eval_workbench.scientific_checks import run_direct_checks
from llm_eval_workbench.scientific_data import (
    audit_scientific_dataset,
    load_scientific_cases,
    load_target_comparison,
)
from llm_eval_workbench.scientific_gateway import simulate_environment_state
from llm_eval_workbench.scientific_schemas import ScientificOutput

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "datasets" / "scientific_v2"
SOURCE_AUDIT = (
    PROJECT_ROOT.parents[1]
    / "research"
    / "PROJECT3_BENCHMARK_SOURCE_AUDIT_20260802.md"
)


def test_scientific_v2_data_contract_is_sealed_and_offline() -> None:
    audit = audit_scientific_dataset(
        data_dir=DATA_DIR,
        source_audit_path=SOURCE_AUDIT,
        verify_seal=True,
    )
    assert audit["valid"] is True
    assert audit["provider_requests"] == 0
    assert audit["case_count"] == 37
    assert audit["target_comparison_count"] == 24
    assert audit["task_pack_distribution"] == {
        "grounded_qa": 6,
        "instruction_generation": 6,
        "multi_turn": 6,
        "structured_tool": 6,
    }
    assert audit["source_audit_current_match"] is True
    assert audit["manifest_valid"] is True
    assert audit["seal_valid"] is True


def test_v2_risk_cells_and_difficulty_are_balanced_without_repeated_scenarios() -> None:
    cases = load_target_comparison(DATA_DIR)
    assert len({case.case_id for case in cases}) == 24
    assert len({case.scenario_family for case in cases}) == 24
    assert Counter(case.risk_cell for case in cases) == {
        risk: 2
        for risk in sorted({case.risk_cell for case in cases})
    }
    assert Counter(case.difficulty for case in cases) == {"D2": 12, "D3": 12}
    assert len({case.input + json.dumps(case.context, ensure_ascii=False) for case in cases}) == 24


def test_v2_cases_have_complete_gold_counterexample_and_direct_boundaries() -> None:
    cases = load_target_comparison(DATA_DIR)
    for case in cases:
        assert case.risk_cell
        assert case.difficulty_rationale
        assert case.gold_answer or case.gold_tool_calls
        assert case.counterexample
        assert case.checker_boundary
        gold = ScientificOutput(
            case_id=case.case_id,
            content=case.gold_answer or "",
            tool_calls=case.gold_tool_calls,
            environment_state=(
                case.gold_environment_state
                or simulate_environment_state(case, case.gold_tool_calls)
            ),
            output_hash="gold",
        )
        direct_results = run_direct_checks(case, gold)
        assert all(result.passed for result in direct_results), case.case_id


def test_v2_counterexamples_trigger_at_least_one_registered_direct_failure_when_present() -> None:
    for case in load_target_comparison(DATA_DIR):
        if not case.direct_checks:
            continue
        bad = ScientificOutput(
            case_id=case.case_id,
            content=case.counterexample or "",
            tool_calls=case.counterexample_tool_calls,
            environment_state=simulate_environment_state(
                case, case.counterexample_tool_calls
            ),
            output_hash="counterexample",
        )
        results = run_direct_checks(case, bad)
        assert any(not result.passed for result in results), case.case_id


def test_list_item_checker_does_not_count_bold_labels_as_bullets() -> None:
    case = next(
        item
        for item in load_scientific_cases(DATA_DIR)
        if item.case_id == "CMP-IG-25"
    )
    spec = next(item for item in case.direct_checks if item.check_type == "list_item_count")
    output = ScientificOutput(
        case_id=case.case_id,
        content="**场景证据：**\n1. 第一项\n2. 第二项",
        output_hash="fixture",
    )
    result = run_direct_checks(case.model_copy(update={"direct_checks": [spec]}), output)[0]
    assert result.details["actual"] == 2


from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from streamlit.testing.v1 import AppTest

from llm_eval_workbench import cli
from llm_eval_workbench.scientific_store import ScientificExecutionStore

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_scientific_powershell_entrypoint_parses_without_execution() -> None:
    for relative_path in (
        "scripts/run_scientific_v1.ps1",
        "scripts/run_scientific_v2.ps1",
        "scripts/run_scientific_v3.ps1",
        "scripts/run_scientific_offline_acceptance.ps1",
        "scripts/run_scientific_recovery.ps1",
        "scripts/start_ui.ps1",
        "scripts/save_model_profile_from_stdin.ps1",
    ):
        script = PROJECT_ROOT / relative_path
        escaped = str(script).replace("'", "''")
        parser_command = (
            "$tokens=$null; $errors=$null; "
            "[System.Management.Automation.Language.Parser]::ParseFile("
            f"'{escaped}', [ref]$tokens, [ref]$errors) | Out-Null; "
            "if ($errors.Count -gt 0) { exit 1 }"
        )
        completed = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command", parser_command],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        assert completed.returncode == 0


def test_new_entrypoint_uses_only_scientific_v1_commands() -> None:
    source = (PROJECT_ROOT / "scripts" / "run_scientific_v1.ps1").read_text(
        encoding="utf-8"
    )
    assert "run_full_pipeline.ps1" not in source
    assert "scientific-validate" in source
    assert "scientific-plan" in source
    assert "scientific-run" in source
    assert "ExecutionId" in source
    assert "Get-LlmEvalProfile" in source
    assert "Import-LlmEvalProfileToProcess" in source
    assert "Show-ModelProfileSummary" not in source


def test_versioned_entrypoints_select_artifacts_without_quality_retry() -> None:
    source = (PROJECT_ROOT / "scripts" / "run_scientific_v2.ps1").read_text(
        encoding="utf-8"
    )
    v3_source = (PROJECT_ROOT / "scripts" / "run_scientific_v3.ps1").read_text(
        encoding="utf-8"
    )
    assert "LLM_EVAL_SCIENTIFIC_VERSION" in source
    assert "artifacts\\scientific_{0}\\executions" in source
    assert '[string]$ScientificVersion = "v2"' in source
    assert "-ScientificVersion v3" in v3_source
    assert "allow-runtime-recovery" in source
    assert "runtime_error" in source
    assert "run_full_pipeline.ps1" not in source


def test_scientific_status_reports_plan_before_execution(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.setattr(cli, "SCIENTIFIC_EXECUTION_ROOT", tmp_path)
    execution_id = "planned-status-v1"
    store = ScientificExecutionStore(tmp_path, execution_id)
    store.directory.mkdir(parents=True)
    store.plan_path.write_text("{}", encoding="utf-8")
    store.write_node_once(
        "provider-probe-model-a",
        {"status": "completed", "actual_requests": 0},
    )

    assert (
        cli.command_scientific_status(
            argparse.Namespace(execution_id=execution_id)
        )
        == 0
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["state"]["status"] == "planned"
    assert payload["state"]["completed_nodes"] == 1
    assert payload["state"]["requests_used"] == 0


def test_formal_scientific_path_does_not_use_deepeval_or_repeated_judging() -> None:
    sources = "\n".join(
        (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")
        for relative_path in (
            "src/llm_eval_workbench/atomic_judge.py",
            "src/llm_eval_workbench/scientific_executor.py",
            "src/llm_eval_workbench/scientific_gateway.py",
        )
    )
    normalized = sources.casefold()
    assert "deepeval" not in normalized
    assert "GEval(" not in sources
    assert normalized.count('"num_retries": 0') == 2
    assert "second_judge" not in normalized


def test_streamlit_seven_page_app_and_blind_review_page_smoke() -> None:
    app = AppTest.from_file(str(PROJECT_ROOT / "app.py"), default_timeout=30)
    app.run()
    assert not app.exception
    assert len(app.sidebar.radio) == 1
    expected_pages = {
        "模型配置": "模型配置",
        "项目概览": "项目概览",
        "数据与来源": "数据与来源",
        "运行评测": "运行评测",
        "结果与比较": "结果与比较",
        "单题复核": "单题复核",
        "可选人工抽检": "自动评测结果与可选人工抽检",
    }
    assert set(app.sidebar.radio[0].options) == set(expected_pages)
    for page, title in expected_pages.items():
        app.sidebar.radio[0].set_value(page).run()
        assert not app.exception
        assert any(title in value.value for value in app.subheader)

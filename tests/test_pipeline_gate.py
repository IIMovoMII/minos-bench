from pathlib import Path


def test_formal_live_runs_are_guarded_by_candidate_evaluation_model_freeze():
    project_root = Path(__file__).resolve().parents[1]
    source = (project_root / "scripts" / "run_full_pipeline.ps1").read_text(
        encoding="utf-8"
    )

    gate_position = source.index('Set-Stage "evaluation_model_gate"')
    first_live_position = source.index('Set-Stage "live_model_a_prompt_v1"')

    assert gate_position < first_live_position
    assert '"configs\\evaluation_model_freeze.json"' in source
    assert '$state.status = "awaiting_evaluation_model_design"' in source
    assert "$freeze.candidate_confirmed -isnot [bool]" in source
    assert "$freeze.candidate_confirmed -ne $true" in source
    assert "Formal runs are paused at the candidate evaluation-model gate." in source


def test_online_calls_require_a_separate_execution_budget_authorization():
    project_root = Path(__file__).resolve().parents[1]
    source = (project_root / "scripts" / "run_full_pipeline.ps1").read_text(
        encoding="utf-8"
    )

    authorization_gate = source.index('Set-Stage "execution_budget_gate"')
    probe_stage = source.index('Set-Stage "provider_probes"')
    first_live_stage = source.index('Set-Stage "live_model_a_prompt_v1"')

    assert authorization_gate < probe_stage < first_live_stage
    assert '"configs\\evaluation_run_authorization.json"' in source
    assert "$authorization.candidate_confirmed -ne $true" in source
    assert "max_consecutive_runtime_errors" in source
    assert "max_target_requests_per_run" in source
    assert "max_judge_requests_per_run" in source
    assert '$state.status = "awaiting_execution_authorization"' in source
    assert "function Consume-ExecutionAuthorization" in source
    assert "This execution authorization was already consumed." in source


def test_withdrawn_full_matrix_is_hard_stopped_before_any_online_stage():
    project_root = Path(__file__).resolve().parents[1]
    source = (project_root / "scripts" / "run_full_pipeline.ps1").read_text(
        encoding="utf-8"
    )
    launcher = (project_root / "scripts" / "configure_and_run.ps1").read_text(
        encoding="utf-8"
    )

    staged_plan_gate = source.index('Set-Stage "staged_execution_plan_gate"')
    authorization_gate = source.index('Set-Stage "execution_budget_gate"')
    probe_stage = source.index('Set-Stage "provider_probes"')

    assert staged_plan_gate < authorization_gate < probe_stage
    assert '$state.status = "awaiting_staged_pipeline_rewrite"' in source
    assert "The withdrawn full matrix remains disabled." in source
    assert "No online call was made." in source
    assert "Responses probes passed." not in launcher
    assert "awaiting_staged_pipeline_rewrite" in launcher


def test_official_entrypoints_force_the_current_source_tree():
    project_root = Path(__file__).resolve().parents[1]
    for relative_path in ("scripts/run_cli.ps1", "scripts/start_ui.ps1"):
        source = (project_root / relative_path).read_text(encoding="utf-8")
        assert '$env:PYTHONPATH = Join-Path $projectRoot "src"' in source

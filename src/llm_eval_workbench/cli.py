from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from pathlib import Path
from typing import Any

from .config import load_project_config, resolve_path
from .dataset_service import (
    create_holdout_seal,
    load_many,
)
from .model_gateway import (
    _parse_tool_calls,
    _response_completion,
    _response_output_text,
)
from .probe import probe_judge, probe_model
from .regression_service import promote_case_to_regression
from .report_service import export_comparison, export_run_report
from .result_store import ResultStore
from .review_service import holdout_alignment, submit_review
from .run_service import RunService, run_sync
from .schemas import BadCaseCategory, DataSplit, ReviewDecision, RunMode
from .scientific_data import audit_scientific_dataset
from .scientific_executor import (
    ScientificExecutor,
    classify_provider_error,
    execute_scientific_sync,
    resolve_runtime_models,
)
from .scientific_gateway import ScientificTargetGateway
from .scientific_plan import (
    build_execution_plan,
    create_immutable_plan,
    load_and_verify_plan,
    load_scientific_protocol,
)
from .scientific_probe_receipts import import_provider_probe_receipts
from .scientific_recovery import prepare_runtime_recovery
from .scientific_report import (
    build_scientific_report,
    submit_blind_reviews,
    write_machine_final_report,
)
from .scientific_store import ScientificExecutionStore, atomic_write_json
from .secrets import configuration_presence


def _discover_project_root() -> Path:
    candidates = []
    configured = os.environ.get("LLM_EVAL_PROJECT_ROOT")
    if configured:
        candidates.append(Path(configured))
    candidates.extend([Path.cwd(), Path(__file__).resolve().parents[2]])
    for candidate in candidates:
        resolved = candidate.resolve()
        if (resolved / "PROJECT_SPEC.md").exists() and (resolved / "configs").is_dir():
            return resolved
    raise RuntimeError(
        "Cannot locate project root; run from the project directory or set "
        "LLM_EVAL_PROJECT_ROOT"
    )


PROJECT_ROOT = _discover_project_root()
SCIENTIFIC_VERSION = os.environ.get("LLM_EVAL_SCIENTIFIC_VERSION", "v3").casefold()
if SCIENTIFIC_VERSION not in {"v2", "v3"}:
    raise RuntimeError("LLM_EVAL_SCIENTIFIC_VERSION must be v2 or v3")
SCIENTIFIC_DATA_DIR = PROJECT_ROOT / "datasets" / f"scientific_{SCIENTIFIC_VERSION}"
SCIENTIFIC_PROTOCOL_PATH = (
    PROJECT_ROOT / "configs" / f"scientific_{SCIENTIFIC_VERSION}.json"
)
SCIENTIFIC_EXECUTION_ROOT = (
    PROJECT_ROOT / "artifacts" / f"scientific_{SCIENTIFIC_VERSION}" / "executions"
)
SCIENTIFIC_SOURCE_AUDIT = (
    PROJECT_ROOT / "docs" / "SCIENTIFIC_V3_SOURCE_AUDIT_20260820.md"
    if SCIENTIFIC_VERSION == "v3"
    else PROJECT_ROOT.parents[1]
    / "research"
    / "PROJECT3_BENCHMARK_SOURCE_AUDIT_20260802.md"
)


def _config_path(value: str) -> Path:
    path = Path(value)
    return path.resolve() if path.is_absolute() else (PROJECT_ROOT / path).resolve()


def _store_from_config(config_path: Path) -> ResultStore:
    config = load_project_config(config_path)
    return ResultStore(resolve_path(PROJECT_ROOT, config.artifact_dir))


def _print_json(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, default=str))


def command_validate(args: argparse.Namespace) -> int:
    service = RunService(
        project_root=PROJECT_ROOT,
        config_path=_config_path(args.config),
    )
    audit = service.validate(require_frozen_contract=args.frozen)
    _print_json(audit)
    return 0 if audit["valid"] else 1


def command_env_status(args: argparse.Namespace) -> int:
    config = load_project_config(_config_path(args.config))
    _print_json({model.alias: configuration_presence(model) for model in config.models})
    return 0


def command_probe(args: argparse.Namespace) -> int:
    config = load_project_config(_config_path(args.config))
    model = config.model_by_alias(args.model_alias)
    if args.semantic_judge:
        if model.role != "judge":
            raise ValueError("--semantic-judge requires a judge model alias")
        result = probe_judge(model, config.judge)
    else:
        result = probe_model(model)
    _print_json(result)
    return 0 if result["success"] else 2


def command_run(args: argparse.Namespace) -> int:
    service = RunService(
        project_root=PROJECT_ROOT,
        config_path=_config_path(args.config),
    )
    manifest = run_sync(
        service,
        mode=RunMode(args.mode),
        source_run_id=args.source_run,
        outputs_file=args.outputs_file,
        allow_holdout=args.allow_holdout,
        case_ids=set(args.case_id) if args.case_id else None,
        max_consecutive_runtime_errors=args.max_consecutive_runtime_errors,
        max_target_requests=args.max_target_requests,
        max_judge_requests=args.max_judge_requests,
    )
    export_run_report(service.store, manifest.run_id)
    _print_json(manifest.model_dump(mode="json"))
    return 0 if manifest.status.value == "completed" else 2


def command_status(args: argparse.Namespace) -> int:
    store = _store_from_config(_config_path(args.config))
    if args.run_id:
        manifest = store.load_manifest(args.run_id)
        _print_json(
            {
                "manifest": manifest.model_dump(mode="json"),
                "summary": store.summarize(args.run_id).model_dump(mode="json"),
                "integrity": store.verify_integrity(args.run_id),
            }
        )
    else:
        _print_json(
            [manifest.model_dump(mode="json") for manifest in store.list_runs()]
        )
    return 0


def command_verify(args: argparse.Namespace) -> int:
    store = _store_from_config(_config_path(args.config))
    result = store.verify_integrity(args.run_id)
    _print_json(result)
    return 0 if result["valid"] else 2


def command_report(args: argparse.Namespace) -> int:
    store = _store_from_config(_config_path(args.config))
    paths = export_run_report(store, args.run_id)
    _print_json({key: str(path) for key, path in paths.items()})
    return 0


def command_compare(args: argparse.Namespace) -> int:
    store = _store_from_config(_config_path(args.config))
    output = (
        Path(args.output).resolve()
        if args.output
        else PROJECT_ROOT
        / "artifacts"
        / f"compare_{args.baseline}_{args.candidate}.json"
    )
    path = export_comparison(
        store,
        args.baseline,
        args.candidate,
        output,
    )
    _print_json({"comparison": str(path)})
    return 0


def command_seal_holdout(args: argparse.Namespace) -> int:
    holdout_path = resolve_path(PROJECT_ROOT, args.dataset)
    seal_path = resolve_path(PROJECT_ROOT, args.output)
    _print_json(create_holdout_seal(holdout_path, seal_path))
    return 0


def _all_cases(config_path: Path):
    config = load_project_config(config_path)
    paths = [resolve_path(PROJECT_ROOT, path) for path in config.dataset_paths]
    return load_many(paths)


def command_review(args: argparse.Namespace) -> int:
    config_path = _config_path(args.config)
    cases = {case.case_id: case for case in _all_cases(config_path)}
    case = cases.get(args.case_id)
    if case is None:
        raise LookupError(f"Unknown case ID: {args.case_id}")
    store = _store_from_config(config_path)
    review = submit_review(
        store=store,
        run_id=args.run_id,
        case=case,
        reviewer=args.reviewer,
        decision=ReviewDecision(args.decision),
        reason=args.reason,
        issue_categories=[
            BadCaseCategory(category) for category in (args.category or [])
        ],
        root_cause_hypothesis=args.root_cause,
        improvement_suggestion=args.suggestion,
        blind=case.split == DataSplit.HOLDOUT,
    )
    _print_json(review.model_dump(mode="json"))
    return 0


def command_promote_regression(args: argparse.Namespace) -> int:
    config_path = _config_path(args.config)
    cases = {case.case_id: case for case in _all_cases(config_path)}
    case = cases.get(args.case_id)
    if case is None:
        raise LookupError(f"Unknown case ID: {args.case_id}")
    store = _store_from_config(config_path)
    result = promote_case_to_regression(
        regression_dir=PROJECT_ROOT / "datasets" / "regression",
        store=store,
        run_id=args.run_id,
        case=case,
        reason=args.reason,
    )
    _print_json(result)
    return 0


def command_alignment(args: argparse.Namespace) -> int:
    config_path = _config_path(args.config)
    cases = [
        case for case in _all_cases(config_path) if case.split == DataSplit.HOLDOUT
    ]
    store = _store_from_config(config_path)
    _print_json(
        holdout_alignment(
            store=store,
            run_id=args.run_id,
            holdout_cases=cases,
        )
    )
    return 0


def command_scientific_validate(args: argparse.Namespace) -> int:
    del args
    result = audit_scientific_dataset(
        data_dir=SCIENTIFIC_DATA_DIR,
        source_audit_path=SCIENTIFIC_SOURCE_AUDIT,
        verify_seal=True,
    )
    _print_json(result)
    return 0 if result["valid"] else 2


def command_scientific_slot_probe(args: argparse.Namespace) -> int:
    started = time.perf_counter()
    requests_used = 0
    try:
        protocol = load_scientific_protocol(SCIENTIFIC_PROTOCOL_PATH)
        model = resolve_runtime_models(protocol)[args.slot]
        gateway = ScientificTargetGateway(model)
        requests_used = 1
        request_kwargs = gateway.request_kwargs(
            instructions="Reply with any non-empty text.",
            input_items=[{"role": "user", "content": "ping"}],
            max_output_tokens=32,
        )
        request_kwargs.pop("reasoning", None)
        request_kwargs.pop("reasoning_effort", None)
        request_kwargs.pop("thinking", None)
        request_kwargs.pop("output_config", None)
        response = asyncio.run(
            gateway.raw_request(**request_kwargs)
        )
        content = _response_output_text(response)
        tool_calls = _parse_tool_calls(response)
        complete, provider_status, reason = _response_completion(
            response,
            content=content,
            tool_calls=tool_calls,
        )
        response_received = bool(content.strip() or tool_calls)
        result = {
            "logical_slot": args.slot,
            "success": complete and response_received,
            "requests_used": requests_used,
            "response_received": response_received,
            "provider_status": provider_status,
            "incomplete_reason": reason,
            "latency_ms": int((time.perf_counter() - started) * 1000),
            "safe_error": None,
        }
    except Exception as error:
        result = {
            "logical_slot": args.slot,
            "success": False,
            "requests_used": requests_used,
            "response_received": False,
            "provider_status": None,
            "incomplete_reason": None,
            "latency_ms": int((time.perf_counter() - started) * 1000),
            "safe_error": classify_provider_error(error),
        }
    _print_json(result)
    return 0 if result["success"] else 2


def _scientific_store(execution_id: str) -> ScientificExecutionStore:
    return ScientificExecutionStore(SCIENTIFIC_EXECUTION_ROOT, execution_id)


def command_scientific_plan(args: argparse.Namespace) -> int:
    store = _scientific_store(args.execution_id)
    if store.plan_path.exists():
        plan = load_and_verify_plan(
            plan_path=store.plan_path,
            data_dir=SCIENTIFIC_DATA_DIR,
            protocol_path=SCIENTIFIC_PROTOCOL_PATH,
        )
    else:
        plan = build_execution_plan(
            execution_id=args.execution_id,
            data_dir=SCIENTIFIC_DATA_DIR,
            source_audit_path=SCIENTIFIC_SOURCE_AUDIT,
            protocol_path=SCIENTIFIC_PROTOCOL_PATH,
        )
        create_immutable_plan(execution_root=SCIENTIFIC_EXECUTION_ROOT, plan=plan)
    _print_json(
        {
            "execution_id": plan.execution_id,
            "formal_cases": plan.formal_case_count,
            "formal_target_requests": plan.formal_target_requests,
            "formal_judge_requests": plan.formal_judge_requests,
            "judge_validation_requests": plan.judge_validation_requests,
            "provider_probe_requests": plan.provider_probe_requests,
            "technical_probe_requests": plan.technical_probe_requests,
            "transient_retry_cap": plan.transient_retry_cap,
            "planned_base_requests": plan.planned_base_requests,
            "absolute_request_ceiling": plan.absolute_request_ceiling,
            "estimated_token_range": plan.estimated_token_range,
            "plan_path": str(store.plan_path),
        }
    )
    return 0


def command_scientific_import_provider_probes(args: argparse.Namespace) -> int:
    store = _scientific_store(args.execution_id)
    written = import_provider_probe_receipts(
        store=store,
        receipt_path=_config_path(args.receipt),
    )
    _print_json(
        {
            "execution_id": args.execution_id,
            "imported_provider_probe_receipts": len(written),
            "new_provider_requests": 0,
            "successful_probes_repeated": 0,
        }
    )
    return 0


def command_scientific_run(args: argparse.Namespace) -> int:
    protocol = load_scientific_protocol(SCIENTIFIC_PROTOCOL_PATH)
    retry_attempts = int(
        protocol.get("stop_rules", {}).get(
            "empty_or_api_failure_retry_attempts",
            0,
        )
    )
    judge_contract_retries = (
        args.judge_contract_retries
        if args.judge_contract_retries is not None
        else (
            1
            if protocol.get("judge", {}).get("contract_error_policy")
            == "retry_once_then_record_runtime_error"
            else 0
        )
    )
    executor = ScientificExecutor(
        project_root=PROJECT_ROOT,
        data_dir=SCIENTIFIC_DATA_DIR,
        source_audit_path=SCIENTIFIC_SOURCE_AUDIT,
        protocol_path=SCIENTIFIC_PROTOCOL_PATH,
        execution_root=SCIENTIFIC_EXECUTION_ROOT,
        execution_id=args.execution_id,
        allow_runtime_recovery=(args.allow_runtime_recovery or retry_attempts > 0),
        runtime_retry_attempts=retry_attempts,
        judge_contract_retry_attempts=judge_contract_retries,
    )
    state = execute_scientific_sync(executor)
    _print_json(
        {
            "execution_id": state.get("execution_id"),
            "status": state.get("status"),
            "completed_nodes": state.get("completed_nodes"),
            "requests_used": state.get("requests_used"),
            "transient_retries_used": state.get("transient_retries_used"),
            "stop_reason": state.get("stop_reason"),
            "safe_error": state.get("safe_error"),
            "blind_review_ready": (
                _scientific_store(args.execution_id).directory
                / "candidate_blind_review_package.json"
            ).exists(),
        }
    )
    return 0 if state.get("status") == "completed" else 2


def command_scientific_prepare_recovery(args: argparse.Namespace) -> int:
    manifest = prepare_runtime_recovery(
        execution_root=SCIENTIFIC_EXECUTION_ROOT,
        source_execution_id=args.source_execution_id,
        recovery_execution_id=args.execution_id,
        data_dir=SCIENTIFIC_DATA_DIR,
        source_audit_path=SCIENTIFIC_SOURCE_AUDIT,
        protocol_path=SCIENTIFIC_PROTOCOL_PATH,
    )
    _print_json(manifest)
    return 0


def command_scientific_status(args: argparse.Namespace) -> int:
    store = _scientific_store(args.execution_id)
    state = store.load_state()
    if state is None:
        if not store.plan_path.exists():
            raise LookupError("scientific execution plan does not exist")
        node_artifacts = store.all_node_artifacts()
        state = {
            "execution_id": args.execution_id,
            "status": "planned",
            "completed_nodes": len(node_artifacts),
            "requests_used": sum(
                int(item.get("actual_requests", 0)) for item in node_artifacts
            ),
            "transient_retries_used": 0,
            "stop_reason": None,
        }
    _print_json(
        {
            "state": state,
            "plan_exists": store.plan_path.exists(),
            "machine_report_ready": (
                store.directory / "machine_preliminary_report.json"
            ).exists(),
            "blind_review_ready": (
                store.directory / "candidate_blind_review_package.json"
            ).exists(),
            "candidate_review_records_exist": (
                store.directory / "candidate_reviews.jsonl"
            ).exists(),
            "candidate_confirmed_report_ready": (
                store.directory / "candidate_confirmed_report.json"
            ).exists(),
            "machine_final_report_ready": (
                store.directory / "machine_final_report.json"
            ).exists(),
        }
    )
    return 0


def command_scientific_review_submit(args: argparse.Namespace) -> int:
    store = _scientific_store(args.execution_id)
    reviews = submit_blind_reviews(store=store, submission_path=args.submission)
    _print_json({"execution_id": args.execution_id, "appended_reviews": len(reviews)})
    return 0


def command_scientific_confirmed_report(args: argparse.Namespace) -> int:
    store = _scientific_store(args.execution_id)
    report = build_scientific_report(
        store=store,
        data_dir=SCIENTIFIC_DATA_DIR,
        confirmed=True,
    )
    path = store.directory / "candidate_confirmed_report.json"
    atomic_write_json(path, report)
    _print_json({"execution_id": args.execution_id, "report_path": str(path)})
    return 0


def command_scientific_machine_final_report(args: argparse.Namespace) -> int:
    store = _scientific_store(args.execution_id)
    protocol = load_scientific_protocol(SCIENTIFIC_PROTOCOL_PATH)
    matrix = protocol.get("matrix", {})
    path = write_machine_final_report(
        store=store,
        data_dir=SCIENTIFIC_DATA_DIR,
        require_judge_validation=bool(matrix.get("run_judge_validation", True)),
        judge_validation_reference=matrix.get("reused_prior_engine_acceptance"),
    )
    _print_json({"execution_id": args.execution_id, "report_path": str(path)})
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="llm-eval",
        description="Minos Bench：本地优先的大模型质量评测工作台",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser("validate")
    validate.add_argument("--config", default="configs/sample_project.yaml")
    validate.add_argument("--frozen", action="store_true")
    validate.set_defaults(handler=command_validate)

    env_status = subparsers.add_parser("env-status")
    env_status.add_argument("--config", default="configs/sample_project.yaml")
    env_status.set_defaults(handler=command_env_status)

    probe = subparsers.add_parser("probe")
    probe.add_argument("--config", default="configs/sample_project.yaml")
    probe.add_argument("--model-alias", required=True)
    probe.add_argument("--semantic-judge", action="store_true")
    probe.set_defaults(handler=command_probe)

    run = subparsers.add_parser("run")
    run.add_argument("--config", default="configs/sample_project.yaml")
    run.add_argument(
        "--mode",
        choices=[mode.value for mode in RunMode],
        required=True,
    )
    run.add_argument("--source-run")
    run.add_argument("--outputs-file")
    run.add_argument("--allow-holdout", action="store_true")
    run.add_argument("--case-id", action="append")
    run.add_argument("--max-consecutive-runtime-errors", type=int, default=3)
    run.add_argument("--max-target-requests", type=int)
    run.add_argument("--max-judge-requests", type=int)
    run.set_defaults(handler=command_run)

    status = subparsers.add_parser("status")
    status.add_argument("--config", default="configs/sample_project.yaml")
    status.add_argument("--run-id")
    status.set_defaults(handler=command_status)

    verify = subparsers.add_parser("verify")
    verify.add_argument("--config", default="configs/sample_project.yaml")
    verify.add_argument("--run-id", required=True)
    verify.set_defaults(handler=command_verify)

    report = subparsers.add_parser("report")
    report.add_argument("--config", default="configs/sample_project.yaml")
    report.add_argument("--run-id", required=True)
    report.set_defaults(handler=command_report)

    compare = subparsers.add_parser("compare")
    compare.add_argument("--config", default="configs/sample_project.yaml")
    compare.add_argument("--baseline", required=True)
    compare.add_argument("--candidate", required=True)
    compare.add_argument("--output")
    compare.set_defaults(handler=command_compare)

    seal = subparsers.add_parser("seal-holdout")
    seal.add_argument("--dataset", default="datasets/holdout/cases.jsonl")
    seal.add_argument("--output", default="datasets/holdout/seal.json")
    seal.set_defaults(handler=command_seal_holdout)

    review = subparsers.add_parser("review")
    review.add_argument("--config", default="configs/run_model_a_prompt_v1.yaml")
    review.add_argument("--run-id", required=True)
    review.add_argument("--case-id", required=True)
    review.add_argument(
        "--decision",
        choices=[decision.value for decision in ReviewDecision],
        required=True,
    )
    review.add_argument("--reason", required=True)
    review.add_argument(
        "--category",
        action="append",
        choices=[category.value for category in BadCaseCategory],
    )
    review.add_argument("--root-cause")
    review.add_argument("--suggestion")
    review.add_argument("--reviewer", default="candidate")
    review.set_defaults(handler=command_review)

    promote = subparsers.add_parser("promote-regression")
    promote.add_argument("--config", default="configs/sample_project.yaml")
    promote.add_argument("--run-id", required=True)
    promote.add_argument("--case-id", required=True)
    promote.add_argument("--reason", required=True)
    promote.set_defaults(handler=command_promote_regression)

    alignment = subparsers.add_parser("alignment")
    alignment.add_argument("--config", default="configs/run_model_a_prompt_v1.yaml")
    alignment.add_argument("--run-id", required=True)
    alignment.set_defaults(handler=command_alignment)

    scientific_validate = subparsers.add_parser("scientific-validate")
    scientific_validate.set_defaults(handler=command_scientific_validate)

    scientific_probe = subparsers.add_parser("scientific-slot-probe")
    scientific_probe.add_argument(
        "--slot",
        required=True,
        choices=["model_a", "model_b", "weak_model", "judge"],
    )
    scientific_probe.set_defaults(handler=command_scientific_slot_probe)

    scientific_plan = subparsers.add_parser("scientific-plan")
    scientific_plan.add_argument("--execution-id", required=True)
    scientific_plan.set_defaults(handler=command_scientific_plan)

    scientific_import_probes = subparsers.add_parser(
        "scientific-import-provider-probes"
    )
    scientific_import_probes.add_argument("--execution-id", required=True)
    scientific_import_probes.add_argument("--receipt", required=True)
    scientific_import_probes.set_defaults(
        handler=command_scientific_import_provider_probes
    )

    scientific_run = subparsers.add_parser("scientific-run")
    scientific_run.add_argument("--execution-id", required=True)
    scientific_run.add_argument("--allow-runtime-recovery", action="store_true")
    scientific_run.add_argument("--judge-contract-retries", type=int)
    scientific_run.set_defaults(handler=command_scientific_run)

    scientific_recovery = subparsers.add_parser("scientific-prepare-recovery")
    scientific_recovery.add_argument("--source-execution-id", required=True)
    scientific_recovery.add_argument("--execution-id", required=True)
    scientific_recovery.set_defaults(handler=command_scientific_prepare_recovery)

    scientific_status = subparsers.add_parser("scientific-status")
    scientific_status.add_argument("--execution-id", required=True)
    scientific_status.set_defaults(handler=command_scientific_status)

    scientific_review = subparsers.add_parser("scientific-review-submit")
    scientific_review.add_argument("--execution-id", required=True)
    scientific_review.add_argument("--submission", required=True)
    scientific_review.set_defaults(handler=command_scientific_review_submit)

    scientific_confirmed = subparsers.add_parser("scientific-confirmed-report")
    scientific_confirmed.add_argument("--execution-id", required=True)
    scientific_confirmed.set_defaults(handler=command_scientific_confirmed_report)

    scientific_machine_final = subparsers.add_parser(
        "scientific-machine-final-report"
    )
    scientific_machine_final.add_argument("--execution-id", required=True)
    scientific_machine_final.set_defaults(
        handler=command_scientific_machine_final_report
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    raise SystemExit(args.handler(args))


if __name__ == "__main__":
    main()

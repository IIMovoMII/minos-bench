from __future__ import annotations

import asyncio
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path

from .config import load_project_config, load_yaml, resolve_path, safe_config_hash
from .dataset_service import (
    audit_dataset,
    dataset_hash,
    load_many,
    verify_holdout_seal,
)
from .evaluator import JudgeProtocol, evaluate_case
from .hashing import code_snapshot_hash, sha256_text, sha256_value
from .metrics.deepeval_metrics import (
    JUDGE_BLIND_POLICY_VERSION,
    DeepEvalJudge,
)
from .model_gateway import TargetModelGateway
from .result_store import ResultStore, make_run_id
from .schemas import (
    CaseResult,
    CaseStatus,
    DataSplit,
    EvaluationCase,
    GeneratedOutput,
    ImportedOutput,
    ProjectConfig,
    RunManifest,
    RunMode,
    RunStatus,
    RunStopReason,
    RuntimeIssue,
)
from .secrets import ResolvedModel, resolve_model, safe_exception_details


def _load_imported_outputs(path: Path) -> list[ImportedOutput]:
    outputs: list[ImportedOutput] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                outputs.append(ImportedOutput.model_validate_json(line))
            except Exception as error:
                raise ValueError(
                    f"{path.name}:{line_number}: invalid imported output"
                ) from error
    case_ids = [output.case_id for output in outputs]
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("Imported outputs contain duplicate case IDs")
    return outputs


def _base_url_fingerprint(model: ResolvedModel) -> str | None:
    if not model.base_url:
        return None
    return sha256_text(model.base_url.get_secret_value())[:16]


def _generation_config_hash(
    *,
    model: ResolvedModel,
    prompt: object,
) -> str:
    return sha256_value(
        {
            "alias": model.alias,
            "model_name": model.model_name,
            "api_mode": model.api_mode,
            "streaming": False,
            "store": False,
            "base_url_fingerprint": _base_url_fingerprint(model),
            "params": model.params,
            "prompt": prompt,
        }
    )


def _metric_config_hash(
    *,
    config: ProjectConfig,
    cases: Iterable[EvaluationCase],
    judge_model: ResolvedModel | None,
    metric_profile: dict[str, object],
) -> str:
    return sha256_value(
        {
            "judge": config.judge,
            "judge_model_name": (judge_model.model_name if judge_model else None),
            "judge_api_mode": (judge_model.api_mode if judge_model else None),
            "judge_streaming": False,
            "judge_store": False,
            "judge_target_identity_blinded": judge_model is not None,
            "judge_blind_policy_version": (
                JUDGE_BLIND_POLICY_VERSION if judge_model else None
            ),
            "judge_reasoning_effort": (
                judge_model.reasoning_effort if judge_model else None
            ),
            "judge_params": (judge_model.params if judge_model else None),
            "judge_base_url_fingerprint": (
                _base_url_fingerprint(judge_model) if judge_model else None
            ),
            "metric_profile": metric_profile,
            "case_metrics": [
                {
                    "case_id": case.case_id,
                    "rubric_id": case.rubric_id,
                    "rubric": case.rubric,
                    "deterministic_checks": case.deterministic_checks,
                }
                for case in sorted(cases, key=lambda item: item.case_id)
            ],
        }
    )


def _runtime_error_result(
    *,
    run_id: str,
    case: EvaluationCase,
    mode: RunMode,
    stage: str,
    error: BaseException,
) -> CaseResult:
    error_type, message = safe_exception_details(error)
    return CaseResult(
        run_id=run_id,
        case_id=case.case_id,
        task_pack=case.task_pack,
        status=CaseStatus.RUNTIME_ERROR,
        evaluation_scope=mode,
        coverage_complete=False,
        runtime_issues=[
            RuntimeIssue(
                stage=stage,
                error_type=error_type,
                message=message,
                retryable=stage in {"target_generation", "judge_evaluation"},
            )
        ],
    )


class RunService:
    def __init__(
        self,
        *,
        project_root: str | Path,
        config_path: str | Path,
        target_gateway: TargetModelGateway | None = None,
        judge: JudgeProtocol | None = None,
    ) -> None:
        self.project_root = Path(project_root).resolve()
        self.config_path = Path(config_path).resolve()
        self.config = load_project_config(self.config_path)
        self.metric_profile = load_yaml(
            resolve_path(self.project_root, self.config.metric_profile_path)
        )
        artifact_dir = resolve_path(self.project_root, self.config.artifact_dir)
        self.store = ResultStore(artifact_dir)
        self._target_gateway = target_gateway
        self._judge = judge

    def _load_cases(self) -> list[EvaluationCase]:
        paths = [
            resolve_path(self.project_root, path) for path in self.config.dataset_paths
        ]
        return load_many(paths)

    def validate(self, *, require_frozen_contract: bool = False) -> dict[str, object]:
        cases = self._load_cases()
        return audit_dataset(
            cases,
            require_frozen_contract=require_frozen_contract,
        )

    async def execute(
        self,
        *,
        mode: RunMode,
        source_run_id: str | None = None,
        outputs_file: str | Path | None = None,
        allow_holdout: bool = False,
        case_ids: set[str] | None = None,
        max_consecutive_runtime_errors: int = 3,
        max_target_requests: int | None = None,
        max_judge_requests: int | None = None,
    ) -> RunManifest:
        if max_consecutive_runtime_errors < 1:
            raise ValueError("max_consecutive_runtime_errors must be positive")
        if max_target_requests is not None and max_target_requests < 1:
            raise ValueError("max_target_requests must be positive")
        if max_judge_requests is not None and max_judge_requests < 1:
            raise ValueError("max_judge_requests must be positive")

        all_cases = self._load_cases()
        full_dataset_hash = dataset_hash(all_cases)
        known_case_ids = {case.case_id for case in all_cases}
        unknown_case_ids = (case_ids or set()) - known_case_ids
        if unknown_case_ids:
            unknown = ", ".join(sorted(unknown_case_ids))
            raise ValueError(f"Unknown evaluation case IDs: {unknown}")
        selected_cases = (
            [case for case in all_cases if case.case_id in case_ids]
            if case_ids
            else all_cases
        )
        if not selected_cases:
            raise ValueError("No evaluation cases selected")

        effective_max_target_requests = max_target_requests
        if effective_max_target_requests is None and mode == RunMode.LIVE:
            effective_max_target_requests = max(
                1,
                (len(selected_cases) * 3 + 1) // 2,
            )
        effective_max_judge_requests = max_judge_requests
        if effective_max_judge_requests is None and mode != RunMode.DETERMINISTIC_ONLY:
            effective_max_judge_requests = max(
                1,
                len(selected_cases) * self.config.judge.repetitions * 3,
            )

        holdout_selected = any(
            case.split == DataSplit.HOLDOUT for case in selected_cases
        )
        if holdout_selected:
            if not allow_holdout:
                raise RuntimeError("Holdout data requires explicit --allow-holdout")
            holdout_paths = [
                resolve_path(self.project_root, path)
                for path in self.config.dataset_paths
                if "holdout" in Path(path).parts
            ]
            if len(holdout_paths) != 1:
                raise RuntimeError("Exactly one holdout dataset path is required")
            verify_holdout_seal(
                holdout_paths[0],
                holdout_paths[0].parent / "seal.json",
            )

        prompt = self.config.prompt_by_id(self.config.prompt_id)
        source_manifest: RunManifest | None = None
        source_outputs: dict[str, GeneratedOutput] = {}
        imported_fixture = False
        imported_artifact_hash: str | None = None
        target_model: ResolvedModel | None = None
        judge_model: ResolvedModel | None = None
        target_api_mode: str | None = None
        target_reasoning_effort: str | None = None

        if mode == RunMode.LIVE:
            target_config = self.config.model_by_alias(self.config.target_model_alias)
            target_model = (
                self._target_gateway.model
                if self._target_gateway is not None
                else resolve_model(target_config)
            )
            target_gateway = self._target_gateway or TargetModelGateway(target_model)
            generation_hash = _generation_config_hash(
                model=target_model,
                prompt=prompt,
            )
            target_model_name = target_model.model_name
            target_api_mode = target_model.api_mode
            target_reasoning_effort = target_model.reasoning_effort
        else:
            if source_run_id and outputs_file:
                raise ValueError("Use either --source-run or --outputs-file, not both")
            if not source_run_id and not outputs_file:
                raise ValueError(
                    f"{mode.value} requires --source-run or --outputs-file"
                )
            if source_run_id:
                source_manifest = self.store.load_manifest(source_run_id)
                if source_manifest.dataset_hash != full_dataset_hash:
                    raise ValueError(
                        "Replay source dataset hash does not match current dataset"
                    )
                if (
                    source_manifest.target_model_alias != self.config.target_model_alias
                    or source_manifest.prompt_id != prompt.prompt_id
                    or source_manifest.prompt_version != prompt.version
                ):
                    raise ValueError(
                        "Replay source generation identity does not match config"
                    )
                source_outputs = self.store.output_by_case(source_run_id)
                generation_hash = source_manifest.generation_config_hash
                target_model_name = source_manifest.target_model_name
                target_api_mode = source_manifest.target_api_mode or "responses"
                target_reasoning_effort = source_manifest.target_reasoning_effort
            else:
                imported_path = resolve_path(self.project_root, str(outputs_file))
                imported = _load_imported_outputs(imported_path)
                if not imported:
                    raise ValueError("Imported output file is empty")
                aliases = {item.model_alias for item in imported}
                names = {item.model_name for item in imported}
                prompt_ids = {item.prompt_id for item in imported}
                prompt_versions = {item.prompt_version for item in imported}
                if aliases != {self.config.target_model_alias}:
                    raise ValueError(
                        "Imported output model alias does not match config"
                    )
                if prompt_ids != {prompt.prompt_id} or prompt_versions != {
                    prompt.version
                }:
                    raise ValueError(
                        "Imported output prompt identity does not match config"
                    )
                if len(names) != 1:
                    raise ValueError("Imported outputs contain multiple model names")
                imported_artifact_hash = sha256_text(
                    imported_path.read_text(encoding="utf-8")
                )
                imported_fixture = any(item.fixture for item in imported)
                source_outputs = {
                    item.case_id: GeneratedOutput(
                        run_id="imported-output",
                        source_artifact_hash=imported_artifact_hash,
                        case_id=item.case_id,
                        model_alias=item.model_alias,
                        model_name=item.model_name,
                        prompt_id=item.prompt_id,
                        prompt_version=item.prompt_version,
                        content=item.content,
                        tool_calls=item.tool_calls,
                        usage=item.usage,
                        latency_ms=item.latency_ms,
                        attempts=item.attempts,
                        request_count=item.request_count,
                        generation_complete=item.generation_complete,
                        provider_response_status=item.provider_response_status,
                        provider_incomplete_reason=item.provider_incomplete_reason,
                        output_hash=item.output_hash
                        or sha256_text(item.content + sha256_value(item.tool_calls)),
                    )
                    for item in imported
                }
                target_model_name = next(iter(names))
                generation_hash = sha256_value(
                    {
                        "imported_output_hash": imported_artifact_hash,
                        "model_alias": self.config.target_model_alias,
                        "model_name": target_model_name,
                        "prompt_id": prompt.prompt_id,
                        "prompt_version": prompt.version,
                    }
                )
            target_gateway = None

        if mode != RunMode.DETERMINISTIC_ONLY:
            judge_config = self.config.model_by_alias(self.config.judge.model_alias)
            if self._judge is None:
                judge_model = resolve_model(judge_config)
                judge: JudgeProtocol | None = DeepEvalJudge(
                    judge_model, self.config.judge
                )
            else:
                judge = self._judge
                judge_model = getattr(self._judge, "model", None)
        else:
            judge = None

        metric_hash = _metric_config_hash(
            config=self.config,
            cases=all_cases,
            judge_model=judge_model,
            metric_profile=self.metric_profile,
        )
        config_hash = safe_config_hash(self.config)
        run_id = make_run_id(config_hash, full_dataset_hash)
        while self.store.run_dir(run_id).exists():
            run_id = make_run_id(
                sha256_text(config_hash + run_id),
                full_dataset_hash,
            )

        manifest = RunManifest(
            run_id=run_id,
            project_id=self.config.project_id,
            project_version=self.config.version,
            mode=mode,
            status=RunStatus.RUNNING,
            target_model_alias=self.config.target_model_alias,
            target_model_name=target_model_name,
            target_api_mode=target_api_mode,
            target_streaming=False,
            target_reasoning_effort=target_reasoning_effort,
            judge_model_alias=(
                self.config.judge.model_alias
                if mode != RunMode.DETERMINISTIC_ONLY
                else None
            ),
            judge_model_name=(judge_model.model_name if judge_model else None),
            judge_api_mode=(judge_model.api_mode if judge_model else None),
            judge_streaming=False,
            judge_reasoning_effort=(
                judge_model.reasoning_effort if judge_model else None
            ),
            judge_target_identity_blinded=(True if judge_model else None),
            judge_blind_policy_version=(
                JUDGE_BLIND_POLICY_VERSION if judge_model else None
            ),
            provider_storage_enabled=False,
            prompt_id=prompt.prompt_id,
            prompt_version=prompt.version,
            dataset_hash=full_dataset_hash,
            config_hash=config_hash,
            generation_config_hash=generation_hash,
            metric_config_hash=metric_hash,
            code_hash=code_snapshot_hash(self.project_root),
            replay_source_run_id=source_run_id,
            case_count=len(selected_cases),
            max_consecutive_runtime_errors=max_consecutive_runtime_errors,
            max_target_requests=effective_max_target_requests,
            max_judge_requests=effective_max_judge_requests,
            notes=(
                (["holdout explicitly unlocked"] if holdout_selected else [])
                + (
                    ["synthetic fixture outputs; not a real model run"]
                    if imported_fixture
                    else []
                )
                + (
                    [f"imported output artifact {imported_artifact_hash}"]
                    if imported_artifact_hash
                    else []
                )
            ),
        )
        self.store.create_run(manifest)

        interrupted = False
        consecutive_runtime_errors = 0
        target_requests_used = 0
        judge_requests_used = 0
        stop_reason: RunStopReason | None = None

        def stop_after_result(
            result: CaseResult,
            *,
            has_remaining_cases: bool,
        ) -> RunStopReason | None:
            nonlocal consecutive_runtime_errors, judge_requests_used
            judge_requests_used += result.judge_request_count
            if result.status == CaseStatus.RUNTIME_ERROR:
                consecutive_runtime_errors += 1
            else:
                consecutive_runtime_errors = 0
            if not has_remaining_cases:
                return None
            if consecutive_runtime_errors >= max_consecutive_runtime_errors:
                return RunStopReason.CONSECUTIVE_RUNTIME_ERRORS
            if (
                effective_max_target_requests is not None
                and target_requests_used >= effective_max_target_requests
            ):
                return RunStopReason.TARGET_REQUEST_BUDGET
            if (
                effective_max_judge_requests is not None
                and judge_requests_used >= effective_max_judge_requests
            ):
                return RunStopReason.JUDGE_REQUEST_BUDGET
            return None

        try:
            for case_index, case in enumerate(selected_cases):
                has_remaining_cases = case_index + 1 < len(selected_cases)
                if mode == RunMode.LIVE:
                    try:
                        output = await target_gateway.generate(
                            run_id=run_id,
                            case=case,
                            prompt=prompt,
                        )
                        self.store.append_output(output)
                        target_requests_used += output.request_count
                    except Exception as error:
                        result = _runtime_error_result(
                            run_id=run_id,
                            case=case,
                            mode=mode,
                            stage="target_generation",
                            error=error,
                        )
                        self.store.append_result(result)
                        stop_reason = stop_after_result(
                            result,
                            has_remaining_cases=has_remaining_cases,
                        )
                        if stop_reason is not None:
                            break
                        continue
                else:
                    source_output = source_outputs.get(case.case_id)
                    if source_output is None:
                        result = _runtime_error_result(
                            run_id=run_id,
                            case=case,
                            mode=mode,
                            stage="persistence",
                            error=LookupError("Replay output is missing"),
                        )
                        self.store.append_result(result)
                        stop_reason = stop_after_result(
                            result,
                            has_remaining_cases=has_remaining_cases,
                        )
                        if stop_reason is not None:
                            break
                        continue
                    output = source_output.model_copy(
                        update={
                            "run_id": run_id,
                            "source_run_id": source_run_id,
                            "source_artifact_hash": (
                                imported_artifact_hash
                                or source_output.source_artifact_hash
                            ),
                            "created_at": datetime.now(UTC),
                        }
                    )
                    self.store.append_output(output)

                result = evaluate_case(
                    run_id=run_id,
                    case=case,
                    output=output,
                    mode=mode,
                    judge_config=self.config.judge,
                    judge=judge,
                )
                self.store.append_result(result)
                stop_reason = stop_after_result(
                    result,
                    has_remaining_cases=has_remaining_cases,
                )
                if stop_reason is not None:
                    break
        except KeyboardInterrupt:
            interrupted = True
        finally:
            if stop_reason is not None:
                current_manifest = self.store.load_manifest(run_id)
                self.store.write_manifest(
                    current_manifest.model_copy(update={"stop_reason": stop_reason})
                )
            manifest = self.store.finalize(
                run_id,
                expected_case_count=len(selected_cases),
                fatal_error=interrupted,
            )
        return manifest


def run_sync(
    service: RunService,
    *,
    mode: RunMode,
    source_run_id: str | None = None,
    outputs_file: str | Path | None = None,
    allow_holdout: bool = False,
    case_ids: set[str] | None = None,
    max_consecutive_runtime_errors: int = 3,
    max_target_requests: int | None = None,
    max_judge_requests: int | None = None,
) -> RunManifest:
    return asyncio.run(
        service.execute(
            mode=mode,
            source_run_id=source_run_id,
            outputs_file=outputs_file,
            allow_holdout=allow_holdout,
            case_ids=case_ids,
            max_consecutive_runtime_errors=max_consecutive_runtime_errors,
            max_target_requests=max_target_requests,
            max_judge_requests=max_judge_requests,
        )
    )

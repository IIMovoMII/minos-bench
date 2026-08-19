from __future__ import annotations

import json
import os
import re
from collections import Counter, defaultdict
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel

from .hashing import sha256_file, sha256_text
from .schemas import (
    CaseResult,
    GeneratedOutput,
    HumanReview,
    RunManifest,
    RunStatus,
    RunSummary,
)

T = TypeVar("T", bound=BaseModel)


def make_run_id(config_hash: str, dataset_hash: str) -> str:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    suffix = sha256_text(f"{timestamp}:{config_hash}:{dataset_hash}")[:10]
    return f"{timestamp}-{suffix}"


def _safe_run_id(run_id: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{4,100}", run_id):
        raise ValueError("Invalid run_id")
    return run_id


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _append_model(path: Path, value: BaseModel) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = value.model_dump_json(exclude_none=False)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(payload + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def _load_models(path: Path, model: type[T]) -> list[T]:
    if not path.exists():
        return []
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
                    f"{path.name}:{line_number}: invalid stored record"
                ) from error
    return values


class ResultStore:
    def __init__(self, artifact_root: str | Path) -> None:
        self.artifact_root = Path(artifact_root).resolve()
        self.artifact_root.mkdir(parents=True, exist_ok=True)

    def run_dir(self, run_id: str) -> Path:
        safe_id = _safe_run_id(run_id)
        candidate = (self.artifact_root / safe_id).resolve()
        if self.artifact_root not in candidate.parents:
            raise ValueError("Run path escapes artifact root")
        return candidate

    def create_run(self, manifest: RunManifest) -> Path:
        directory = self.run_dir(manifest.run_id)
        if directory.exists():
            raise FileExistsError(f"Run already exists: {manifest.run_id}")
        directory.mkdir(parents=True)
        self.write_manifest(manifest)
        return directory

    def write_manifest(self, manifest: RunManifest) -> None:
        if manifest.sensitive_fields_persisted:
            raise ValueError("Manifest cannot persist sensitive fields")
        _atomic_json(
            self.run_dir(manifest.run_id) / "manifest.json",
            manifest.model_dump(mode="json", exclude_none=False),
        )

    def load_manifest(self, run_id: str) -> RunManifest:
        path = self.run_dir(run_id) / "manifest.json"
        return RunManifest.model_validate_json(path.read_text(encoding="utf-8"))

    def append_output(self, output: GeneratedOutput) -> None:
        _append_model(
            self.run_dir(output.run_id) / "outputs.jsonl",
            output,
        )

    def append_result(self, result: CaseResult) -> None:
        _append_model(
            self.run_dir(result.run_id) / "results.jsonl",
            result,
        )

    def append_review(self, review: HumanReview) -> None:
        _append_model(
            self.run_dir(review.run_id) / "reviews.jsonl",
            review,
        )

    def load_outputs(self, run_id: str) -> list[GeneratedOutput]:
        return _load_models(
            self.run_dir(run_id) / "outputs.jsonl",
            GeneratedOutput,
        )

    def load_results(self, run_id: str) -> list[CaseResult]:
        return _load_models(
            self.run_dir(run_id) / "results.jsonl",
            CaseResult,
        )

    def load_reviews(self, run_id: str) -> list[HumanReview]:
        return _load_models(
            self.run_dir(run_id) / "reviews.jsonl",
            HumanReview,
        )

    def output_by_case(self, run_id: str) -> dict[str, GeneratedOutput]:
        values: dict[str, GeneratedOutput] = {}
        for output in self.load_outputs(run_id):
            if output.case_id in values:
                raise ValueError(f"Duplicate output for {output.case_id} in {run_id}")
            values[output.case_id] = output
        return values

    def result_by_case(self, run_id: str) -> dict[str, CaseResult]:
        values: dict[str, CaseResult] = {}
        for result in self.load_results(run_id):
            if result.case_id in values:
                raise ValueError(f"Duplicate result for {result.case_id} in {run_id}")
            values[result.case_id] = result
        return values

    def summarize(self, run_id: str) -> RunSummary:
        results = self.load_results(run_id)
        outputs = self.load_outputs(run_id)
        reviews = self.load_reviews(run_id)
        status_counts = Counter(result.status.value for result in results)
        per_pack: dict[str, Counter[str]] = defaultdict(Counter)
        scores: list[float] = []
        for result in results:
            per_pack[result.task_pack.value][result.status.value] += 1
            if result.judge_score_mean is not None:
                scores.append(result.judge_score_mean)

        def optional_sum(values: Iterable[int | float | None]):
            collected = [value for value in values if value is not None]
            return sum(collected) if collected else None

        return RunSummary(
            run_id=run_id,
            case_count=len(results),
            status_counts=dict(sorted(status_counts.items())),
            task_pack_counts={
                key: dict(sorted(value.items()))
                for key, value in sorted(per_pack.items())
            },
            mean_judge_score=(sum(scores) / len(scores) if scores else None),
            runtime_error_count=status_counts.get("RUNTIME_ERROR", 0),
            human_review_count=len(reviews),
            target_request_count=sum(output.request_count for output in outputs),
            target_prompt_tokens=optional_sum(
                output.usage.prompt_tokens for output in outputs
            ),
            target_completion_tokens=optional_sum(
                output.usage.completion_tokens for output in outputs
            ),
            target_cost=optional_sum(output.usage.cost for output in outputs),
            judge_request_count=sum(result.judge_request_count for result in results),
            judge_prompt_tokens=optional_sum(
                result.judge_usage.prompt_tokens for result in results
            ),
            judge_completion_tokens=optional_sum(
                result.judge_usage.completion_tokens for result in results
            ),
            judge_cost=optional_sum(result.judge_usage.cost for result in results),
        )

    def finalize(
        self,
        run_id: str,
        *,
        expected_case_count: int,
        fatal_error: bool = False,
    ) -> RunManifest:
        manifest = self.load_manifest(run_id)
        results = self.load_results(run_id)
        completed_count = len(results)
        if fatal_error and completed_count == 0:
            status = RunStatus.FAILED
        elif completed_count < expected_case_count:
            status = RunStatus.PARTIAL
        else:
            status = RunStatus.COMPLETED
        manifest = manifest.model_copy(
            update={
                "status": status,
                "completed_count": completed_count,
                "finished_at": datetime.now(UTC),
            }
        )
        self.write_manifest(manifest)
        summary = self.summarize(run_id)
        _atomic_json(
            self.run_dir(run_id) / "summary.json",
            summary.model_dump(mode="json", exclude_none=False),
        )
        self.write_integrity(run_id)
        return manifest

    def write_integrity(self, run_id: str) -> dict[str, Any]:
        directory = self.run_dir(run_id)
        records = []
        for path in sorted(directory.iterdir()):
            if (
                path.is_file()
                and path.name not in {"integrity.json"}
                and not path.name.endswith(".tmp")
            ):
                records.append(
                    {
                        "path": path.name,
                        "sha256": sha256_file(path),
                        "bytes": path.stat().st_size,
                    }
                )
        payload = {
            "run_id": run_id,
            "files": records,
            "generated_at": datetime.now(UTC).isoformat(),
        }
        _atomic_json(directory / "integrity.json", payload)
        return payload

    def verify_integrity(self, run_id: str) -> dict[str, Any]:
        directory = self.run_dir(run_id)
        integrity_path = directory / "integrity.json"
        if not integrity_path.exists():
            return {
                "valid": False,
                "run_id": run_id,
                "error": "integrity_manifest_missing",
                "missing": [],
                "unexpected": [],
                "mismatched": [],
            }
        payload = json.loads(integrity_path.read_text(encoding="utf-8"))
        if payload.get("run_id") != run_id:
            return {
                "valid": False,
                "run_id": run_id,
                "error": "integrity_run_id_mismatch",
                "missing": [],
                "unexpected": [],
                "mismatched": [],
            }
        expected = {
            str(record["path"]): record
            for record in payload.get("files", [])
            if isinstance(record, dict) and "path" in record
        }
        actual_paths = {
            path.name
            for path in directory.iterdir()
            if path.is_file()
            and path.name != "integrity.json"
            and not path.name.endswith(".tmp")
        }
        missing = sorted(set(expected) - actual_paths)
        unexpected = sorted(actual_paths - set(expected))
        mismatched = []
        for name in sorted(set(expected) & actual_paths):
            path = directory / name
            record = expected[name]
            actual_hash = sha256_file(path)
            actual_bytes = path.stat().st_size
            if actual_hash != record.get("sha256") or actual_bytes != record.get(
                "bytes"
            ):
                mismatched.append(
                    {
                        "path": name,
                        "expected_sha256": record.get("sha256"),
                        "actual_sha256": actual_hash,
                        "expected_bytes": record.get("bytes"),
                        "actual_bytes": actual_bytes,
                    }
                )
        return {
            "valid": not missing and not unexpected and not mismatched,
            "run_id": run_id,
            "error": None,
            "missing": missing,
            "unexpected": unexpected,
            "mismatched": mismatched,
            "checked_file_count": len(actual_paths),
        }

    def list_runs(self) -> list[RunManifest]:
        manifests: list[RunManifest] = []
        if not self.artifact_root.exists():
            return manifests
        for directory in sorted(self.artifact_root.iterdir(), reverse=True):
            manifest_path = directory / "manifest.json"
            if directory.is_dir() and manifest_path.exists():
                try:
                    manifests.append(
                        RunManifest.model_validate_json(
                            manifest_path.read_text(encoding="utf-8")
                        )
                    )
                except Exception:
                    continue
        return manifests

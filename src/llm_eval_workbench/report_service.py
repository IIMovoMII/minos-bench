from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from .analysis import compare_runs
from .result_store import ResultStore
from .review_service import latest_reviews
from .schemas import ReviewDecision


def _write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def export_run_report(store: ResultStore, run_id: str) -> dict[str, Path]:
    directory = store.run_dir(run_id)
    manifest = store.load_manifest(run_id)
    summary = store.summarize(run_id)
    results = store.load_results(run_id)
    outputs = store.output_by_case(run_id)
    reviews = store.load_reviews(run_id)
    latest = latest_reviews(store, run_id)

    summary_path = directory / "report.json"
    _write_json(
        summary_path,
        {
            "manifest": manifest.model_dump(mode="json"),
            "summary": summary.model_dump(mode="json"),
            "cases": [result.model_dump(mode="json") for result in results],
            "human_reviews": [review.model_dump(mode="json") for review in reviews],
        },
    )

    csv_path = directory / "results.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "case_id",
                "task_pack",
                "status",
                "evaluation_scope",
                "coverage_complete",
                "judge_score_mean",
                "judge_score_min",
                "judge_score_max",
                "judge_score_band",
                "judge_unstable",
                "generation_complete",
                "provider_response_status",
                "provider_incomplete_reason",
                "output_hash",
                "output",
                "human_decision",
                "issue_categories",
                "human_reason",
            ],
        )
        writer.writeheader()
        for result in results:
            output = outputs.get(result.case_id)
            review = latest.get(result.case_id)
            writer.writerow(
                {
                    "case_id": result.case_id,
                    "task_pack": result.task_pack.value,
                    "status": result.status.value,
                    "evaluation_scope": result.evaluation_scope.value,
                    "coverage_complete": result.coverage_complete,
                    "judge_score_mean": result.judge_score_mean,
                    "judge_score_min": result.judge_score_min,
                    "judge_score_max": result.judge_score_max,
                    "judge_score_band": (
                        result.judge_score_band.value if result.judge_score_band else ""
                    ),
                    "judge_unstable": result.judge_unstable,
                    "generation_complete": (
                        output.generation_complete if output else ""
                    ),
                    "provider_response_status": (
                        output.provider_response_status if output else ""
                    ),
                    "provider_incomplete_reason": (
                        output.provider_incomplete_reason if output else ""
                    ),
                    "output_hash": result.generated_output_hash,
                    "output": output.content if output else "",
                    "human_decision": review.decision.value if review else "",
                    "issue_categories": (
                        "|".join(category.value for category in review.issue_categories)
                        if review
                        else ""
                    ),
                    "human_reason": review.reason if review else "",
                }
            )

    markdown_path = directory / "report.md"
    lines = [
        f"# Evaluation Run {run_id}",
        "",
        f"- Status: `{manifest.status.value}`",
        f"- Mode: `{manifest.mode.value}`",
        f"- Target: `{manifest.target_model_alias}` / `{manifest.target_model_name}`",
        f"- Prompt: `{manifest.prompt_id}` / `{manifest.prompt_version}`",
        f"- Dataset hash: `{manifest.dataset_hash}`",
        f"- Generation config hash: `{manifest.generation_config_hash}`",
        f"- Metric config hash: `{manifest.metric_config_hash}`",
        f"- Cases: {summary.case_count}",
        f"- Stop reason: {manifest.stop_reason}",
        (
            "- Safety limits (consecutive errors / target requests / "
            "Judge requests): "
            f"{manifest.max_consecutive_runtime_errors} / "
            f"{manifest.max_target_requests} / {manifest.max_judge_requests}"
        ),
        f"- Mean Judge score: {summary.mean_judge_score}",
        (
            f"- Target calls/tokens/cost: {summary.target_request_count} / "
            f"{summary.target_prompt_tokens}+{summary.target_completion_tokens} / "
            f"{summary.target_cost}"
        ),
        (
            f"- Judge calls/tokens/cost: {summary.judge_request_count} / "
            f"{summary.judge_prompt_tokens}+{summary.judge_completion_tokens} / "
            f"{summary.judge_cost}"
        ),
        "",
        "## Status counts",
        "",
    ]
    for status, count in summary.status_counts.items():
        lines.append(f"- {status}: {count}")
    lines.extend(["", "## Task packs", ""])
    for task_pack, counts in summary.task_pack_counts.items():
        rendered = ", ".join(f"{status}={count}" for status, count in counts.items())
        lines.append(f"- {task_pack}: {rendered}")
    confirmed_bad_cases = [
        review for review in latest.values() if review.decision == ReviewDecision.FAIL
    ]
    lines.extend(["", "## Human-confirmed Bad Cases", ""])
    if confirmed_bad_cases:
        for review in sorted(confirmed_bad_cases, key=lambda item: item.case_id):
            categories = ", ".join(
                category.value for category in review.issue_categories
            )
            suffix = f" ({categories})" if categories else ""
            lines.append(f"- {review.case_id}{suffix}: {review.reason}")
    else:
        lines.append("- None recorded.")
    lines.extend(
        [
            "",
            "## Interpretation boundary",
            "",
            "- Runtime errors are not model-quality failures.",
            "- Incomplete or empty provider outputs are retained but routed to "
            "runtime error before quality scoring.",
            "- A semantic Judge alone cannot create a hard FAIL.",
            "- Replay results describe stored outputs, not a new generation.",
            "- Human holdout alignment is reported only after all required reviews.",
            "",
        ]
    )
    markdown_path.write_text("\n".join(lines), encoding="utf-8")
    store.write_integrity(run_id)
    return {
        "json": summary_path,
        "csv": csv_path,
        "markdown": markdown_path,
    }


def export_comparison(
    store: ResultStore,
    baseline_run_id: str,
    candidate_run_id: str,
    output_path: str | Path,
) -> Path:
    comparison = compare_runs(store, baseline_run_id, candidate_run_id)
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    _write_json(target, comparison)
    return target

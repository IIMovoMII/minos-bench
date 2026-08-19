from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any

from jsonschema import Draft202012Validator

from ..schemas import (
    DeterministicCheckSpec,
    EvaluationCase,
    GeneratedOutput,
    MetricResult,
)


def _result(
    spec: DeterministicCheckSpec,
    passed: bool,
    reason: str,
    *,
    details: dict[str, Any] | None = None,
) -> MetricResult:
    return MetricResult(
        metric_id=spec.check_id,
        kind="deterministic",
        passed=passed,
        score=1.0 if passed else 0.0,
        threshold=1.0,
        reason=reason,
        hard_failure=spec.hard and not passed,
        details=details or {},
    )


def _terms(
    spec: DeterministicCheckSpec,
    content: str,
    *,
    forbidden: bool,
) -> MetricResult:
    terms = [str(term) for term in spec.params.get("terms", [])]
    case_sensitive = bool(spec.params.get("case_sensitive", False))
    mode = str(spec.params.get("mode", "all"))
    haystack = content if case_sensitive else content.casefold()
    normalized = terms if case_sensitive else [term.casefold() for term in terms]
    matches = [term in haystack for term in normalized]
    if forbidden:
        passed = not any(matches)
        found = [term for term, matched in zip(terms, matches, strict=True) if matched]
        reason = "未出现禁止项" if passed else f"出现禁止项：{found}"
        return _result(spec, passed, reason, details={"found": found})
    passed = all(matches) if mode == "all" else any(matches)
    missing = [
        term for term, matched in zip(terms, matches, strict=True) if not matched
    ]
    reason = "必需项满足" if passed else f"缺少必需项：{missing}"
    return _result(spec, passed, reason, details={"missing": missing})


def _length(
    spec: DeterministicCheckSpec, content: str, *, maximum: bool
) -> MetricResult:
    limit = int(spec.params["value"])
    actual = len(content.strip())
    passed = actual <= limit if maximum else actual >= limit
    comparison = "不超过" if maximum else "不少于"
    return _result(
        spec,
        passed,
        f"长度 {actual}，要求{comparison} {limit}",
        details={"actual": actual, "limit": limit},
    )


def _list_item_count(spec: DeterministicCheckSpec, content: str) -> MetricResult:
    pattern = spec.params.get("pattern", r"(?m)^\s*(?:[-*]|\d+[.)、])\s+\S+")
    count = len(re.findall(str(pattern), content))
    exact = spec.params.get("exact")
    minimum = spec.params.get("min")
    maximum = spec.params.get("max")
    passed = True
    if exact is not None:
        passed = count == int(exact)
    if minimum is not None:
        passed = passed and count >= int(minimum)
    if maximum is not None:
        passed = passed and count <= int(maximum)
    return _result(
        spec,
        passed,
        f"识别到 {count} 个列表项",
        details={"actual": count, "exact": exact, "min": minimum, "max": maximum},
    )


def extract_json(content: str) -> Any:
    text = content.strip()
    fenced = re.fullmatch(
        r"```(?:json)?\s*(.*?)\s*```", text, flags=re.DOTALL | re.IGNORECASE
    )
    if fenced:
        text = fenced.group(1)
    return json.loads(text)


def _json_schema(spec: DeterministicCheckSpec, content: str) -> MetricResult:
    schema = spec.params.get("schema")
    if not isinstance(schema, dict):
        return _result(spec, False, "评测配置缺少 JSON Schema")
    try:
        value = extract_json(content)
    except (json.JSONDecodeError, TypeError) as error:
        return _result(
            spec,
            False,
            "输出不是有效 JSON",
            details={"error_type": type(error).__name__},
        )
    errors = sorted(
        Draft202012Validator(schema).iter_errors(value),
        key=lambda error: list(error.absolute_path),
    )
    messages = [
        f"{'.'.join(map(str, error.absolute_path)) or '$'}: {error.message}"
        for error in errors
    ]
    return _result(
        spec,
        not errors,
        "JSON Schema 通过" if not errors else "；".join(messages),
        details={"errors": messages},
    )


def _get_path(value: Any, path: str) -> Any:
    current = value
    for segment in path.split("."):
        if isinstance(current, dict) and segment in current:
            current = current[segment]
        else:
            raise KeyError(path)
    return current


def _json_field_values(spec: DeterministicCheckSpec, content: str) -> MetricResult:
    expected = spec.params.get("expected", {})
    try:
        value = extract_json(content)
    except (json.JSONDecodeError, TypeError) as error:
        return _result(
            spec,
            False,
            "输出不是有效 JSON",
            details={"error_type": type(error).__name__},
        )
    mismatches: dict[str, Any] = {}
    for path, expected_value in expected.items():
        try:
            actual_value = _get_path(value, str(path))
        except KeyError:
            mismatches[str(path)] = {"expected": expected_value, "actual": None}
            continue
        if actual_value != expected_value:
            mismatches[str(path)] = {
                "expected": expected_value,
                "actual": actual_value,
            }
    return _result(
        spec,
        not mismatches,
        "字段值符合预期" if not mismatches else f"字段不匹配：{list(mismatches)}",
        details={"mismatches": mismatches},
    )


def _tool_calls(
    spec: DeterministicCheckSpec,
    case: EvaluationCase,
    output: GeneratedOutput,
) -> MetricResult:
    expected_calls = sorted(case.expected_tools, key=lambda call: call.order)
    actual_calls = sorted(output.tool_calls, key=lambda call: call.order)
    errors: list[str] = []
    if len(actual_calls) != len(expected_calls):
        errors.append(f"调用数量应为 {len(expected_calls)}，实际 {len(actual_calls)}")
    for index, expected in enumerate(expected_calls):
        if index >= len(actual_calls):
            break
        actual = actual_calls[index]
        if actual.name != expected.name:
            errors.append(
                f"第 {index + 1} 个工具应为 {expected.name}，实际 {actual.name}"
            )
            continue
        for key, expected_value in expected.arguments.items():
            if actual.arguments.get(key) != expected_value:
                errors.append(
                    f"{actual.name}.{key} 参数应为 {expected_value!r}，"
                    f"实际 {actual.arguments.get(key)!r}"
                )
        if not expected.allow_extra_arguments:
            extras = sorted(set(actual.arguments) - set(expected.arguments))
            if extras:
                errors.append(f"{actual.name} 出现额外参数：{extras}")
    return _result(
        spec,
        not errors,
        "工具调用符合预期" if not errors else "；".join(errors),
        details={"errors": errors},
    )


def _language(spec: DeterministicCheckSpec, content: str) -> MetricResult:
    expected = str(spec.params.get("value", "zh-CN"))
    chinese_count = len(re.findall(r"[\u4e00-\u9fff]", content))
    latin_count = len(re.findall(r"[A-Za-z]", content))
    if expected == "zh-CN":
        passed = chinese_count > 0 and chinese_count >= latin_count / 2
    else:
        passed = latin_count > 0 and chinese_count <= latin_count / 4
    return _result(
        spec,
        passed,
        f"字符统计：中文 {chinese_count}，拉丁字母 {latin_count}",
        details={
            "expected": expected,
            "chinese_count": chinese_count,
            "latin_count": latin_count,
        },
    )


def evaluate_check(
    spec: DeterministicCheckSpec,
    case: EvaluationCase,
    output: GeneratedOutput,
) -> MetricResult:
    handlers: dict[str, Callable[[DeterministicCheckSpec, str], MetricResult]] = {
        "required_terms": lambda item, content: _terms(item, content, forbidden=False),
        "forbidden_terms": lambda item, content: _terms(item, content, forbidden=True),
        "max_length": lambda item, content: _length(item, content, maximum=True),
        "min_length": lambda item, content: _length(item, content, maximum=False),
        "list_item_count": _list_item_count,
        "json_schema": _json_schema,
        "json_field_values": _json_field_values,
        "language": _language,
    }
    if spec.type == "tool_calls":
        return _tool_calls(spec, case, output)
    handler = handlers[spec.type]
    return handler(spec, output.content)


def run_deterministic_checks(
    case: EvaluationCase, output: GeneratedOutput
) -> list[MetricResult]:
    return [evaluate_check(spec, case, output) for spec in case.deterministic_checks]

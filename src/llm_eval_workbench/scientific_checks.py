from __future__ import annotations

import json
import re
import unicodedata
from itertools import pairwise
from typing import Any

from jsonschema import Draft202012Validator

from .scientific_schemas import (
    DirectCheckResult,
    DirectCheckSpec,
    ScientificCase,
    ScientificOutput,
)


def _result(
    spec: DirectCheckSpec,
    passed: bool,
    reason: str,
    **details: Any,
) -> DirectCheckResult:
    return DirectCheckResult(
        criterion_id=spec.criterion_id,
        authority=spec.authority,
        severity=spec.severity,
        passed=passed,
        reason=reason,
        details=details,
    )


def _nonempty_lines(content: str) -> list[str]:
    return [line.strip() for line in content.splitlines() if line.strip()]


def _extract_json(content: str) -> Any:
    text = content.strip()
    fenced = re.fullmatch(
        r"```(?:json)?\s*(.*?)\s*```",
        text,
        flags=re.DOTALL | re.IGNORECASE,
    )
    if fenced:
        text = fenced.group(1)
    return json.loads(text)


def _normalize_numeric_grouping(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    return re.sub(r"(?<=\d),(?=\d{3}(?:\D|$))", "", normalized)


def _normalize_prose_equivalent(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return re.sub(r"[。.!！?？;；]+$", "", normalized).strip()


def _normalize_text(value: str, normalizers: list[str]) -> str:
    normalized = value
    for normalizer in normalizers:
        if normalizer == "numeric_grouping":
            normalized = _normalize_numeric_grouping(normalized)
        else:
            raise ValueError(f"unsupported direct-check normalizer: {normalizer}")
    return normalized


def _values_match(actual: Any, expected: Any, comparison: str) -> bool:
    if comparison == "exact":
        return actual == expected
    if comparison == "prose_equivalent":
        return (
            isinstance(actual, str)
            and isinstance(expected, str)
            and _normalize_prose_equivalent(actual)
            == _normalize_prose_equivalent(expected)
        )
    raise ValueError(f"unsupported direct-check comparison: {comparison}")


def _exact_line_count(
    spec: DirectCheckSpec, output: ScientificOutput
) -> DirectCheckResult:
    expected = int(spec.params["value"])
    actual = len(_nonempty_lines(output.content))
    return _result(
        spec,
        actual == expected,
        f"non-empty line count={actual}, expected={expected}",
        actual=actual,
        expected=expected,
    )


def _line_prefixes(
    spec: DirectCheckSpec, output: ScientificOutput
) -> DirectCheckResult:
    prefixes = [str(value) for value in spec.params["prefixes"]]
    lines = _nonempty_lines(output.content)
    passed = len(lines) == len(prefixes) and all(
        line.startswith(prefix) for line, prefix in zip(lines, prefixes, strict=True)
    )
    return _result(
        spec,
        passed,
        "line prefixes match" if passed else "line prefixes or count differ",
        expected_prefixes=prefixes,
        actual_lines=lines,
    )


def _list_item_count(
    spec: DirectCheckSpec, output: ScientificOutput
) -> DirectCheckResult:
    pattern = str(
        spec.params.get(
            "pattern",
            r"(?m)^\s*(?:-|\*(?!\*)|\d+[.)、])\s+\S+",
        )
    )
    actual = len(re.findall(pattern, output.content))
    exact = spec.params.get("exact")
    minimum = spec.params.get("min")
    maximum = spec.params.get("max")
    passed = True
    if exact is not None:
        passed = passed and actual == int(exact)
    if minimum is not None:
        passed = passed and actual >= int(minimum)
    if maximum is not None:
        passed = passed and actual <= int(maximum)
    return _result(
        spec,
        passed,
        f"list item count={actual}",
        actual=actual,
        exact=exact,
        minimum=minimum,
        maximum=maximum,
    )


def _item_max_length(
    spec: DirectCheckSpec, output: ScientificOutput
) -> DirectCheckResult:
    maximum = int(spec.params["value"])
    pattern = re.compile(
        str(
            spec.params.get(
                "pattern",
                r"^\s*(?:\d+[.)、]|-|\*(?!\*))\s+(.*)$",
            )
        )
    )
    lengths: list[int] = []
    for line in _nonempty_lines(output.content):
        match = pattern.match(line)
        if match:
            lengths.append(len(match.group(1).strip()))
    passed = bool(lengths) and all(length <= maximum for length in lengths)
    return _result(
        spec,
        passed,
        f"item lengths={lengths}, max={maximum}",
        lengths=lengths,
        maximum=maximum,
    )


def _placeholder_count(
    spec: DirectCheckSpec, output: ScientificOutput
) -> DirectCheckResult:
    pattern = str(spec.params.get("pattern", r"\[[^\[\]\r\n]+\]"))
    actual = len(re.findall(pattern, output.content))
    minimum = spec.params.get("min")
    exact = spec.params.get("exact")
    passed = actual >= int(minimum) if minimum is not None else True
    if exact is not None:
        passed = passed and actual == int(exact)
    return _result(
        spec,
        passed,
        f"placeholder count={actual}",
        actual=actual,
        minimum=minimum,
        exact=exact,
    )


def _required_literals(
    spec: DirectCheckSpec, output: ScientificOutput
) -> DirectCheckResult:
    values = [str(value) for value in spec.params.get("values", [])]
    normalizers = [str(value) for value in spec.params.get("normalizers", [])]
    normalized_content = _normalize_text(output.content, normalizers)
    normalized_values = {
        value: _normalize_text(value, normalizers) for value in values
    }
    missing = [
        value
        for value, normalized_value in normalized_values.items()
        if normalized_value not in normalized_content
    ]
    exact_counts = {
        str(key): int(value)
        for key, value in spec.params.get("exact_counts", {}).items()
    }
    count_mismatches = {
        value: {
            "expected": count,
            "actual": normalized_content.count(
                _normalize_text(value, normalizers)
            ),
        }
        for value, count in exact_counts.items()
        if normalized_content.count(_normalize_text(value, normalizers)) != count
    }
    passed = not missing and not count_mismatches
    return _result(
        spec,
        passed,
        "required literals match" if passed else "required literals differ",
        missing=missing,
        count_mismatches=count_mismatches,
        normalizers=normalizers,
    )


def _forbidden_literals(
    spec: DirectCheckSpec, output: ScientificOutput
) -> DirectCheckResult:
    values = [str(value) for value in spec.params.get("values", [])]
    found = [value for value in values if value in output.content]
    return _result(
        spec,
        not found,
        "no forbidden literal found" if not found else "forbidden literal found",
        found=found,
    )


def _headings_exact(
    spec: DirectCheckSpec, output: ScientificOutput
) -> DirectCheckResult:
    expected = [str(value) for value in spec.params["values"]]
    actual = [
        line.strip()
        for line in output.content.splitlines()
        if line.strip().startswith("#")
    ]
    return _result(
        spec,
        actual == expected,
        "heading sequence matches"
        if actual == expected
        else "heading sequence differs",
        expected=expected,
        actual=actual,
    )


def _max_length(spec: DirectCheckSpec, output: ScientificOutput) -> DirectCheckResult:
    maximum = int(spec.params["value"])
    actual = len(output.content.strip())
    return _result(
        spec,
        actual <= maximum,
        f"length={actual}, max={maximum}",
        actual=actual,
        maximum=maximum,
    )


def _min_length_without_whitespace(
    spec: DirectCheckSpec,
    output: ScientificOutput,
) -> DirectCheckResult:
    minimum = int(spec.params["value"])
    actual = len(re.sub(r"\s+", "", output.content))
    return _result(
        spec,
        actual >= minimum,
        f"non-whitespace length={actual}, min={minimum}",
        actual=actual,
        minimum=minimum,
    )


def _json_schema(spec: DirectCheckSpec, output: ScientificOutput) -> DirectCheckResult:
    schema = spec.params["schema"]
    try:
        value = _extract_json(output.content)
    except (json.JSONDecodeError, TypeError) as error:
        return _result(
            spec,
            False,
            "output is not valid JSON",
            error_type=type(error).__name__,
        )
    errors = sorted(
        Draft202012Validator(schema).iter_errors(value),
        key=lambda item: list(item.absolute_path),
    )
    messages = [
        f"{'.'.join(map(str, item.absolute_path)) or '$'}: {item.message}"
        for item in errors
    ]
    return _result(
        spec,
        not errors,
        "JSON schema matches" if not errors else "JSON schema mismatch",
        errors=messages,
    )


def _tool_call_matches(
    actual: Any,
    expected: dict[str, Any],
    argument_comparisons: dict[str, str],
) -> bool:
    if actual.name != expected["name"]:
        return False
    arguments = expected.get("arguments", {})
    if any(
        not _values_match(
            actual.arguments.get(key),
            value,
            argument_comparisons.get(key, "exact"),
        )
        for key, value in arguments.items()
    ):
        return False
    if not expected.get("allow_extra_arguments", False):
        if set(actual.arguments) != set(arguments):
            return False
    return True


def _tool_calls_exact(
    spec: DirectCheckSpec, output: ScientificOutput
) -> DirectCheckResult:
    variants = spec.params.get("variants", [])
    argument_comparisons = {
        str(key): str(value)
        for key, value in spec.params.get("argument_comparisons", {}).items()
    }
    matched_variant: int | None = None
    for variant_index, variant in enumerate(variants):
        if len(output.tool_calls) != len(variant):
            continue
        if all(
            _tool_call_matches(actual, expected, argument_comparisons)
            for actual, expected in zip(output.tool_calls, variant, strict=True)
        ):
            matched_variant = variant_index
            break
    return _result(
        spec,
        matched_variant is not None,
        "tool call contract matches"
        if matched_variant is not None
        else "tool call contract differs",
        matched_variant=matched_variant,
        actual=[call.model_dump(mode="json") for call in output.tool_calls],
        argument_comparisons=argument_comparisons,
    )


def _tool_observation_sequence(
    spec: DirectCheckSpec, output: ScientificOutput
) -> DirectCheckResult:
    expected_names = [str(value) for value in spec.params.get("names", [])]
    require_success = bool(spec.params.get("require_success", True))
    actual_names = [
        str(step.get("call", {}).get("name")) for step in output.tool_trace
    ]
    turns = [int(step.get("model_turn", 0)) for step in output.tool_trace]
    success = [step.get("result", {}).get("ok") is True for step in output.tool_trace]
    names_match = actual_names == expected_names
    observed_between_calls = all(
        current > previous for previous, current in pairwise(turns)
    )
    success_matches = all(success) if require_success else True
    passed = names_match and observed_between_calls and success_matches
    return _result(
        spec,
        passed,
        "tool results observed between actions"
        if passed
        else "tool observation sequence differs",
        expected_names=expected_names,
        actual_names=actual_names,
        model_turns=turns,
        result_success=success,
        require_success=require_success,
    )


def _no_tool_call(spec: DirectCheckSpec, output: ScientificOutput) -> DirectCheckResult:
    return _result(
        spec,
        not output.tool_calls,
        "no tool call" if not output.tool_calls else "unexpected tool call",
        actual=[call.model_dump(mode="json") for call in output.tool_calls],
    )


def _final_state_any_path(
    spec: DirectCheckSpec, output: ScientificOutput
) -> DirectCheckResult:
    expected = spec.params.get("expected", {})
    value_comparisons = {
        str(key): str(value)
        for key, value in spec.params.get("value_comparisons", {}).items()
    }
    mismatches = {
        key: {"expected": value, "actual": output.environment_state.get(key)}
        for key, value in expected.items()
        if not _values_match(
            output.environment_state.get(key),
            value,
            value_comparisons.get(key, "exact"),
        )
    }
    return _result(
        spec,
        not mismatches,
        "final state matches" if not mismatches else "final state differs",
        mismatches=mismatches,
        value_comparisons=value_comparisons,
    )


def evaluate_direct_check(
    spec: DirectCheckSpec,
    case: ScientificCase,
    output: ScientificOutput,
) -> DirectCheckResult:
    del case
    handlers = {
        "exact_line_count": _exact_line_count,
        "line_prefixes": _line_prefixes,
        "list_item_count": _list_item_count,
        "item_max_length": _item_max_length,
        "placeholder_count": _placeholder_count,
        "required_literals": _required_literals,
        "forbidden_literals": _forbidden_literals,
        "headings_exact": _headings_exact,
        "max_length": _max_length,
        "min_length_without_whitespace": _min_length_without_whitespace,
        "json_schema": _json_schema,
        "tool_calls_exact": _tool_calls_exact,
        "tool_observation_sequence": _tool_observation_sequence,
        "no_tool_call": _no_tool_call,
        "final_state_any_path": _final_state_any_path,
    }
    return handlers[spec.check_type](spec, output)


def run_direct_checks(
    case: ScientificCase,
    output: ScientificOutput,
) -> list[DirectCheckResult]:
    return [evaluate_direct_check(spec, case, output) for spec in case.direct_checks]

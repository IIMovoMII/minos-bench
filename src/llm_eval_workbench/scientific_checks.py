from __future__ import annotations

import json
import re
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
    missing = [value for value in values if value not in output.content]
    exact_counts = {
        str(key): int(value)
        for key, value in spec.params.get("exact_counts", {}).items()
    }
    count_mismatches = {
        value: {"expected": count, "actual": output.content.count(value)}
        for value, count in exact_counts.items()
        if output.content.count(value) != count
    }
    passed = not missing and not count_mismatches
    return _result(
        spec,
        passed,
        "required literals match" if passed else "required literals differ",
        missing=missing,
        count_mismatches=count_mismatches,
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


def _tool_call_matches(actual: Any, expected: dict[str, Any]) -> bool:
    if actual.name != expected["name"]:
        return False
    arguments = expected.get("arguments", {})
    if any(actual.arguments.get(key) != value for key, value in arguments.items()):
        return False
    if not expected.get("allow_extra_arguments", False):
        if set(actual.arguments) != set(arguments):
            return False
    return True


def _tool_calls_exact(
    spec: DirectCheckSpec, output: ScientificOutput
) -> DirectCheckResult:
    variants = spec.params.get("variants", [])
    matched_variant: int | None = None
    for variant_index, variant in enumerate(variants):
        if len(output.tool_calls) != len(variant):
            continue
        if all(
            _tool_call_matches(actual, expected)
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
    mismatches = {
        key: {"expected": value, "actual": output.environment_state.get(key)}
        for key, value in expected.items()
        if output.environment_state.get(key) != value
    }
    return _result(
        spec,
        not mismatches,
        "final state matches" if not mismatches else "final state differs",
        mismatches=mismatches,
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
        "no_tool_call": _no_tool_call,
        "final_state_any_path": _final_state_any_path,
    }
    return handlers[spec.check_type](spec, output)


def run_direct_checks(
    case: ScientificCase,
    output: ScientificOutput,
) -> list[DirectCheckResult]:
    return [evaluate_direct_check(spec, case, output) for spec in case.direct_checks]

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel


def _jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json", exclude_none=False)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Path):
        return value.as_posix()
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def canonical_json(value: Any) -> str:
    return json.dumps(
        _jsonable(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def sha256_value(value: Any) -> str:
    return sha256_text(canonical_json(value))


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_records(records: Iterable[Any]) -> str:
    normalized = sorted(
        (_jsonable(record) for record in records),
        key=lambda item: canonical_json(item),
    )
    return sha256_value(normalized)


def code_snapshot_hash(project_root: str | Path) -> str:
    root = Path(project_root).resolve()
    included_roots = [
        root / "src",
        root / "app.py",
        root / "pyproject.toml",
    ]
    records: list[dict[str, str]] = []
    for included in included_roots:
        if included.is_file():
            records.append(
                {
                    "path": included.relative_to(root).as_posix(),
                    "sha256": sha256_file(included),
                }
            )
            continue
        if not included.exists():
            continue
        for path in sorted(included.rglob("*")):
            if path.is_file() and "__pycache__" not in path.parts:
                records.append(
                    {
                        "path": path.relative_to(root).as_posix(),
                        "sha256": sha256_file(path),
                    }
                )
    return sha256_value(records)

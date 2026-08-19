from __future__ import annotations

import json
import os
import re
import time
import uuid
from pathlib import Path
from typing import Any


def _safe_identifier(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{4,180}", value):
        raise ValueError("invalid artifact identifier")
    return value


def atomic_write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(
        f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
    )
    try:
        temporary.write_text(
            json.dumps(
                value,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
                default=str,
            ),
            encoding="utf-8",
        )
        for attempt in range(8):
            try:
                os.replace(temporary, path)
                break
            except PermissionError:
                if attempt == 7:
                    raise
                time.sleep(0.025 * (attempt + 1))
    finally:
        temporary.unlink(missing_ok=True)


def append_jsonl(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str))
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())


class ScientificExecutionStore:
    def __init__(self, execution_root: str | Path, execution_id: str) -> None:
        root = Path(execution_root).resolve()
        directory = (root / _safe_identifier(execution_id)).resolve()
        if root not in directory.parents:
            raise ValueError("execution directory escapes artifact root")
        self.root = root
        self.directory = directory
        self.nodes_dir = directory / "nodes"

    @property
    def plan_path(self) -> Path:
        return self.directory / "execution_plan.json"

    @property
    def state_path(self) -> Path:
        return self.directory / "state.json"

    @property
    def events_path(self) -> Path:
        return self.directory / "events.jsonl"

    def node_path(self, node_id: str) -> Path:
        return self.nodes_dir / f"{_safe_identifier(node_id)}.json"

    def has_node(self, node_id: str) -> bool:
        return self.node_path(node_id).is_file()

    def load_node(self, node_id: str) -> dict[str, Any]:
        value = json.loads(self.node_path(node_id).read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError(f"invalid node artifact: {node_id}")
        return value

    def write_node_once(self, node_id: str, value: dict[str, Any]) -> Path:
        path = self.node_path(node_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(
            value,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            default=str,
        )
        try:
            with path.open("x", encoding="utf-8", newline="\n") as handle:
                handle.write(payload + "\n")
        except FileExistsError:
            existing = json.loads(path.read_text(encoding="utf-8"))
            if existing != value:
                raise FileExistsError(
                    f"immutable node already differs: {node_id}"
                ) from None
        return path

    def load_state(self) -> dict[str, Any] | None:
        if not self.state_path.exists():
            return None
        value = json.loads(self.state_path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("invalid execution state")
        return value

    def write_state(self, value: dict[str, Any]) -> None:
        atomic_write_json(self.state_path, value)

    def append_event(self, value: dict[str, Any]) -> None:
        append_jsonl(self.events_path, value)

    def all_node_artifacts(self) -> list[dict[str, Any]]:
        if not self.nodes_dir.exists():
            return []
        values: list[dict[str, Any]] = []
        for path in sorted(self.nodes_dir.glob("*.json")):
            value = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(value, dict):
                values.append(value)
        return values

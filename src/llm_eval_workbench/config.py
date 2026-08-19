from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .hashing import sha256_value
from .schemas import ProjectConfig


def load_yaml(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as handle:
        value = yaml.safe_load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"Expected a mapping in {Path(path).name}")
    return value


def load_project_config(path: str | Path) -> ProjectConfig:
    return ProjectConfig.model_validate(load_yaml(path))


def safe_config_hash(config: ProjectConfig) -> str:
    # Configs contain environment variable names, never their resolved values.
    return sha256_value(config)


def resolve_path(project_root: str | Path, configured_path: str) -> Path:
    root = Path(project_root).resolve()
    path = Path(configured_path)
    candidate = path.resolve() if path.is_absolute() else (root / path).resolve()
    if candidate != root and root not in candidate.parents:
        raise ValueError(f"Configured path escapes project root: {configured_path}")
    return candidate

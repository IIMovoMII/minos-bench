from __future__ import annotations

import json
import os
import re
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

SLOT_ENV_PREFIXES = {
    "model_a": "MODEL_A",
    "model_b": "MODEL_B",
    "weak_model": "WEAK_MODEL",
    "judge": "JUDGE_MODEL",
}
SLOT_KEYS = tuple(SLOT_ENV_PREFIXES)
_SINGLE_PROVIDER_VALUE = re.compile(r"^[A-Za-z0-9_.-]+$")


class ProfileBridgeError(RuntimeError):
    """A safe, user-facing local profile error."""


@dataclass(frozen=True, repr=False)
class ProfileSlotInput:
    adapter: str
    model_id: str
    reasoning_effort: str = "default"
    api_key: str = field(default="", repr=False)
    base_url: str = field(default="", repr=False)
    clear_base_url: bool = False

    def __post_init__(self) -> None:
        adapter = self.adapter.strip()
        model_id = self.model_id.strip()
        reasoning_effort = self.reasoning_effort.strip() or "default"
        api_key = self.api_key.strip()
        base_url = self.base_url.strip()
        if not _SINGLE_PROVIDER_VALUE.fullmatch(adapter):
            raise ProfileBridgeError(
                "LiteLLM adapter 只能包含字母、数字、点、下划线或连字符。"
            )
        if not model_id:
            raise ProfileBridgeError("实际模型 ID 不能为空。")
        if not _SINGLE_PROVIDER_VALUE.fullmatch(reasoning_effort):
            raise ProfileBridgeError("思考强度必须是单个 provider 参数值。")
        if base_url:
            parsed = urlparse(base_url)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ProfileBridgeError("接口地址必须是完整的 HTTP(S) Base URL。")
            normalized_path = parsed.path.rstrip("/").casefold()
            if normalized_path.endswith(("/responses", "/chat/completions")):
                raise ProfileBridgeError(
                    "接口地址应填写 Base URL，不能包含 /responses 或 "
                    "/chat/completions。"
                )
        object.__setattr__(self, "adapter", adapter)
        object.__setattr__(self, "model_id", model_id)
        object.__setattr__(self, "reasoning_effort", reasoning_effort)
        object.__setattr__(self, "api_key", api_key)
        object.__setattr__(self, "base_url", base_url)

    @property
    def runtime_model_name(self) -> str:
        prefix = f"{self.adapter}/"
        if self.model_id.casefold().startswith(prefix.casefold()):
            return self.model_id
        return f"{self.adapter}/{self.model_id}"

    def __repr__(self) -> str:
        return (
            "ProfileSlotInput("
            f"adapter={self.adapter!r}, model_id={self.model_id!r}, "
            f"reasoning_effort={self.reasoning_effort!r}, "
            f"api_key={'configured' if self.api_key else 'unchanged'}, "
            f"base_url={'configured' if self.base_url else 'unchanged'}, "
            f"clear_base_url={self.clear_base_url!r})"
        )


@dataclass(frozen=True)
class RuntimeSlotDefaults:
    adapter: str
    model_id: str
    reasoning_effort: str
    api_key_configured: bool
    base_url_configured: bool


@dataclass(frozen=True)
class ProfileSaveResult:
    persisted: bool
    restart_required: bool
    safe_summary: tuple[dict[str, object], ...]


def runtime_slot_defaults(
    slot_key: str,
    environ: Mapping[str, str] | None = None,
) -> RuntimeSlotDefaults:
    prefix = _slot_prefix(slot_key)
    values = os.environ if environ is None else environ
    runtime_name = values.get(f"{prefix}_NAME", "").strip()
    adapter, separator, model_id = runtime_name.partition("/")
    if not separator:
        adapter = "openai"
        model_id = runtime_name
    return RuntimeSlotDefaults(
        adapter=adapter or "openai",
        model_id=model_id,
        reasoning_effort=(
            values.get(f"{prefix}_REASONING_EFFORT", "").strip() or "default"
        ),
        api_key_configured=bool(values.get(f"{prefix}_API_KEY")),
        base_url_configured=bool(values.get(f"{prefix}_BASE_URL")),
    )


def apply_slots_to_environ(
    slots: Mapping[str, ProfileSlotInput],
    environ: dict[str, str] | None = None,
) -> bool:
    """Apply submitted values to this process without exposing them.

    Returns True when an existing encrypted value was retained by the profile
    helper but was not already loaded into this process. In that case the user
    should restart through the one-click launcher before making online calls.
    """

    _validate_slot_set(slots)
    values = os.environ if environ is None else environ
    restart_required = False
    for slot_key, slot in slots.items():
        prefix = _slot_prefix(slot_key)
        values[f"{prefix}_NAME"] = slot.runtime_model_name
        values[f"{prefix}_API_MODE"] = "responses"
        values[f"{prefix}_REASONING_EFFORT"] = slot.reasoning_effort
        if slot.api_key:
            values[f"{prefix}_API_KEY"] = slot.api_key
        elif not values.get(f"{prefix}_API_KEY"):
            restart_required = True
        if slot.clear_base_url:
            values.pop(f"{prefix}_BASE_URL", None)
        elif slot.base_url:
            values[f"{prefix}_BASE_URL"] = slot.base_url
    return restart_required


def save_model_profile(
    project_root: Path,
    slots: Mapping[str, ProfileSlotInput],
    *,
    persist: bool = True,
    environ: dict[str, str] | None = None,
) -> ProfileSaveResult:
    """Persist a Windows DPAPI profile and load submitted values for this run."""

    _validate_slot_set(slots)
    safe_summary: tuple[dict[str, object], ...] = ()
    if persist:
        if os.name != "nt":
            raise ProfileBridgeError(
                "加密持久化当前只支持 Windows；本系统可使用会话级配置。"
            )
        script = project_root / "scripts" / "save_model_profile_from_stdin.ps1"
        module = project_root / "scripts" / "ModelProfile.psm1"
        if not script.is_file() or not module.is_file():
            raise ProfileBridgeError("本地模型配置组件不完整。")
        payload = {
            "slots": {
                slot_key: {
                    "adapter": slot.adapter,
                    "api_mode": "responses",
                    "model_id": slot.model_id,
                    "reasoning_effort": slot.reasoning_effort,
                    "api_key": slot.api_key,
                    "base_url": slot.base_url,
                    "clear_base_url": slot.clear_base_url,
                }
                for slot_key, slot in slots.items()
            }
        }
        source_env = os.environ if environ is None else environ
        child_env = {
            key: value
            for key, value in source_env.items()
            if key.casefold() != "psmodulepath"
        }
        completed = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(script),
                "-ModulePath",
                str(module),
            ],
            cwd=project_root,
            env=child_env,
            input=json.dumps(payload, ensure_ascii=False),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=30,
        )
        if completed.returncode != 0:
            raise ProfileBridgeError(_safe_helper_error(completed.stderr))
        try:
            response = json.loads(completed.stdout)
            safe_summary = tuple(response.get("safe_summary", ()))
        except (TypeError, ValueError, json.JSONDecodeError) as error:
            raise ProfileBridgeError("本地配置已执行，但安全摘要无法解析。") from error

    restart_required = apply_slots_to_environ(slots, environ=environ)
    return ProfileSaveResult(
        persisted=persist,
        restart_required=restart_required,
        safe_summary=safe_summary,
    )


def _validate_slot_set(slots: Mapping[str, ProfileSlotInput]) -> None:
    if set(slots) != set(SLOT_KEYS):
        raise ProfileBridgeError("模型配置必须包含四个固定逻辑槽位。")
    if not all(isinstance(slots[key], ProfileSlotInput) for key in SLOT_KEYS):
        raise ProfileBridgeError("模型槽位配置格式无效。")


def _slot_prefix(slot_key: str) -> str:
    try:
        return SLOT_ENV_PREFIXES[slot_key]
    except KeyError as error:
        raise ProfileBridgeError(f"未知逻辑槽位：{slot_key}") from error


def _safe_helper_error(stderr: str) -> str:
    message = next(
        (line.strip() for line in reversed(stderr.splitlines()) if line.strip()),
        "",
    )
    lowered = message.casefold()
    if not message or "categoryinfo" in lowered or "fullyqualifiederrorid" in lowered:
        return "本地加密配置保存失败，请检查输入后重试。"
    message = re.sub(r"https?://\S+", "[已隐藏地址]", message)
    message = re.sub(r"(?i)\b(?:sk|key|token)-[A-Za-z0-9_.-]+", "[已隐藏凭据]", message)
    return message[:300]

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

from pydantic import SecretStr

from .schemas import GenerationParams, ModelConfig


def uses_anthropic_wire_protocol(model_name: str) -> bool:
    """Use Anthropic fields only when the configured LiteLLM adapter is Anthropic."""
    provider, _, _ = model_name.partition("/")
    return provider.casefold() == "anthropic"


def _reasoning_transport(
    *, model_name: str, reasoning_effort: str
) -> dict[str, object]:
    """Return family-correct reasoning fields for LiteLLM Responses calls.

    The configured provider adapter defines the wire protocol; the underlying
    model family does not. Anthropic adapters use LiteLLM's native
    ``reasoning_effort`` mapping, which becomes adaptive thinking plus
    ``output_config.effort`` on ``/v1/messages``. OpenAI-compatible relays use
    the Responses ``reasoning`` object even when the routed model happens to be
    Claude.
    """
    if uses_anthropic_wire_protocol(model_name):
        return {"reasoning_effort": reasoning_effort}
    return {"reasoning": {"effort": reasoning_effort}}


@dataclass(frozen=True, repr=False)
class ResolvedModel:
    alias: str
    role: str
    model_name: str
    api_key: SecretStr
    base_url: SecretStr | None
    api_mode: str
    reasoning_effort: str | None
    params: GenerationParams

    def __repr__(self) -> str:
        return (
            f"ResolvedModel(alias={self.alias!r}, role={self.role!r}, "
            f"model_name={self.model_name!r}, api_key=SecretStr('**********'), "
            f"base_url={'configured' if self.base_url else 'unset'}, "
            f"api_mode={self.api_mode!r}, "
            f"reasoning_effort={self.reasoning_effort!r})"
        )


def configuration_presence(
    config: ModelConfig, environ: Mapping[str, str] | None = None
) -> dict[str, bool]:
    values = os.environ if environ is None else environ
    return {
        "model_name": bool(values.get(config.model_env)),
        "api_key": bool(values.get(config.api_key_env)),
        "base_url": bool(config.base_url_env and values.get(config.base_url_env)),
        "api_mode": bool(config.api_mode_env and values.get(config.api_mode_env)),
        "reasoning_effort": bool(
            config.reasoning_effort_env and values.get(config.reasoning_effort_env)
        ),
    }


def resolve_model(
    config: ModelConfig,
    environ: Mapping[str, str] | None = None,
    *,
    require_key: bool = True,
) -> ResolvedModel:
    values = os.environ if environ is None else environ
    model_name = values.get(config.model_env, "").strip()
    api_key = values.get(config.api_key_env, "")
    base_url = (
        values.get(config.base_url_env, "").strip() if config.base_url_env else ""
    )
    raw_api_mode = (
        values.get(config.api_mode_env, "").strip() if config.api_mode_env else ""
    )
    api_mode = (raw_api_mode or "responses").removeprefix("/").casefold()
    if api_mode != "responses":
        setting_name = config.api_mode_env or "api_mode"
        raise RuntimeError(
            f"{setting_name} must be responses; Chat Completions is disabled"
        )
    reasoning_effort = (
        values.get(config.reasoning_effort_env, "").strip()
        if config.reasoning_effort_env
        else ""
    ).casefold()
    missing = []
    if not model_name:
        missing.append(config.model_env)
    if require_key and not api_key:
        missing.append(config.api_key_env)
    if missing:
        raise RuntimeError(
            "Missing required runtime configuration: " + ", ".join(missing)
        )
    provider, separator, provider_model = model_name.partition("/")
    if not separator or not provider.strip() or not provider_model.strip():
        raise RuntimeError(f"{config.model_env} must use LiteLLM provider/model format")
    params = config.params
    if reasoning_effort and reasoning_effort != "default":
        extra = dict(params.extra)
        extra.pop("reasoning", None)
        extra.pop("reasoning_effort", None)
        transport = _reasoning_transport(
            model_name=model_name,
            reasoning_effort=reasoning_effort,
        )
        extra.update(transport)
        params = params.model_copy(update={"extra": extra})
    return ResolvedModel(
        alias=config.alias,
        role=config.role,
        model_name=model_name,
        api_key=SecretStr(api_key),
        base_url=SecretStr(base_url) if base_url else None,
        api_mode=api_mode,
        reasoning_effort=reasoning_effort or None,
        params=params,
    )


def safe_exception_details(error: BaseException) -> tuple[str, str]:
    error_type = type(error).__name__
    status = getattr(error, "status_code", None)
    if status is None:
        response = getattr(error, "response", None)
        status = getattr(response, "status_code", None)
    message = f"upstream_http_status={status}" if status else error_type
    return error_type, message

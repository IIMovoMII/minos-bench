from __future__ import annotations

import pytest

from llm_eval_workbench.schemas import GenerationParams, ModelConfig
from llm_eval_workbench.secrets import (
    configuration_presence,
    resolve_model,
    safe_exception_details,
)


def model_config():
    return ModelConfig(
        alias="test",
        role="target",
        model_env="TEST_MODEL",
        api_key_env="TEST_KEY",
        base_url_env="TEST_BASE",
        api_mode_env="TEST_API_MODE",
        reasoning_effort_env="TEST_REASONING",
        params=GenerationParams(),
    )


def test_resolved_model_repr_masks_credentials():
    secret = "super-secret-key"
    endpoint = "https://example.invalid/v1?token=hidden"
    resolved = resolve_model(
        model_config(),
        {
            "TEST_MODEL": "provider/model",
            "TEST_KEY": secret,
            "TEST_BASE": endpoint,
            "TEST_API_MODE": "responses",
        },
    )
    rendered = repr(resolved)
    assert secret not in rendered
    assert endpoint not in rendered
    assert "configured" in rendered


def test_presence_returns_booleans_only():
    presence = configuration_presence(
        model_config(),
        {
            "TEST_MODEL": "provider/model",
            "TEST_KEY": "secret",
            "TEST_BASE": "https://example.invalid",
        },
    )
    assert presence == {
        "model_name": True,
        "api_key": True,
        "base_url": True,
        "api_mode": False,
        "reasoning_effort": False,
    }
    assert "secret" not in str(presence)


def test_safe_exception_does_not_return_raw_message():
    error_type, message = safe_exception_details(RuntimeError("raw-secret-in-error"))
    assert error_type == "RuntimeError"
    assert message == "RuntimeError"
    assert "raw-secret" not in message


def test_resolve_model_rejects_ambiguous_bare_model_name():
    with pytest.raises(
        RuntimeError,
        match="TEST_MODEL must use LiteLLM provider/model format",
    ):
        resolve_model(
            model_config(),
            {
                "TEST_MODEL": "bare-model-id",
                "TEST_KEY": "secret",
                "TEST_BASE": "https://example.invalid",
            },
        )


def test_reasoning_effort_is_resolved_into_generation_params():
    resolved = resolve_model(
        model_config(),
        {
            "TEST_MODEL": "openai/custom-model",
            "TEST_KEY": "secret",
            "TEST_API_MODE": "responses",
            "TEST_REASONING": "max",
        },
    )
    assert resolved.reasoning_effort == "max"
    assert resolved.api_mode == "responses"
    assert resolved.params.extra["reasoning"] == {"effort": "max"}
    assert "reasoning_effort" not in resolved.params.extra


def test_openai_compatible_claude_keeps_openai_reasoning_and_relay_base():
    relay_base = "https://relay.example.invalid/v1"
    resolved = resolve_model(
        model_config(),
        {
            "TEST_MODEL": "openai/claude-fable-5",
            "TEST_KEY": "secret",
            "TEST_BASE": relay_base,
            "TEST_API_MODE": "responses",
            "TEST_REASONING": "MAX",
        },
    )
    assert resolved.reasoning_effort == "max"
    assert resolved.base_url is not None
    assert resolved.base_url.get_secret_value() == relay_base
    assert resolved.params.extra == {"reasoning": {"effort": "max"}}
    assert "extra_body" not in resolved.params.extra


def test_anthropic_adapter_uses_litellm_native_reasoning_mapping():
    resolved = resolve_model(
        model_config(),
        {
            "TEST_MODEL": "anthropic/claude-fable-5",
            "TEST_KEY": "secret",
            "TEST_API_MODE": "responses",
            "TEST_REASONING": "max",
        },
    )
    assert resolved.params.extra == {"reasoning_effort": "max"}
    assert "reasoning" not in resolved.params.extra


def test_chat_completions_api_mode_is_rejected():
    with pytest.raises(
        RuntimeError,
        match="Chat Completions is disabled",
    ):
        resolve_model(
            model_config(),
            {
                "TEST_MODEL": "openai/custom-model",
                "TEST_KEY": "secret",
                "TEST_API_MODE": "chat",
            },
        )

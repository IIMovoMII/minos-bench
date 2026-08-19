from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from llm_eval_workbench.profile_bridge import (
    ProfileBridgeError,
    ProfileSlotInput,
    apply_slots_to_environ,
    runtime_slot_defaults,
    save_model_profile,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _complete_slots(*, include_secrets: bool = True):
    slots = {}
    for index, slot_key in enumerate(
        ("model_a", "model_b", "weak_model", "judge"),
        start=1,
    ):
        slots[slot_key] = ProfileSlotInput(
            adapter="anthropic" if slot_key == "judge" else "openai",
            model_id=f"test-model-{index}",
            reasoning_effort="max",
            api_key=f"unit-secret-{index}" if include_secrets else "",
            base_url=(
                f"https://slot-{index}.example.invalid/v1"
                if include_secrets
                else ""
            ),
        )
    return slots


def test_profile_slot_repr_and_runtime_defaults_do_not_expose_secrets() -> None:
    slot = ProfileSlotInput(
        adapter="openai",
        model_id="test-model",
        api_key="unit-secret-value",
        base_url="https://private.example.invalid/v1",
    )
    representation = repr(slot)
    assert "unit-secret-value" not in representation
    assert "private.example.invalid" not in representation
    assert slot.runtime_model_name == "openai/test-model"

    defaults = runtime_slot_defaults(
        "model_a",
        {
            "MODEL_A_NAME": "anthropic/test-model",
            "MODEL_A_API_KEY": "unit-secret-value",
            "MODEL_A_BASE_URL": "https://private.example.invalid",
            "MODEL_A_REASONING_EFFORT": "high",
        },
    )
    assert defaults.adapter == "anthropic"
    assert defaults.model_id == "test-model"
    assert defaults.api_key_configured is True
    assert defaults.base_url_configured is True


@pytest.mark.parametrize(
    "base_url",
    [
        "not-a-url",
        "https://example.invalid/v1/responses",
        "https://example.invalid/v1/chat/completions",
    ],
)
def test_profile_slot_rejects_non_prefix_base_urls(base_url: str) -> None:
    with pytest.raises(ProfileBridgeError):
        ProfileSlotInput(
            adapter="openai",
            model_id="test-model",
            api_key="unit-secret",
            base_url=base_url,
        )


def test_apply_slots_uses_responses_and_retains_blank_existing_values() -> None:
    environ = {
        "MODEL_A_API_KEY": "existing-secret",
        "MODEL_A_BASE_URL": "https://existing.example.invalid/v1",
    }
    slots = _complete_slots(include_secrets=False)
    for slot_key in ("model_b", "weak_model", "judge"):
        prefix = {
            "model_b": "MODEL_B",
            "weak_model": "WEAK_MODEL",
            "judge": "JUDGE_MODEL",
        }[slot_key]
        environ[f"{prefix}_API_KEY"] = "existing-secret"
    restart_required = apply_slots_to_environ(slots, environ)
    assert restart_required is False
    assert environ["MODEL_A_API_KEY"] == "existing-secret"
    assert environ["MODEL_A_BASE_URL"] == "https://existing.example.invalid/v1"
    assert environ["MODEL_A_API_MODE"] == "responses"
    assert environ["JUDGE_MODEL_NAME"] == "anthropic/test-model-4"


@pytest.mark.skipif(os.name != "nt", reason="Windows DPAPI profile")
def test_streamlit_profile_helper_roundtrip_uses_stdin_and_dpapi(
    tmp_path: Path,
) -> None:
    environ = dict(os.environ)
    environ["LLM_EVAL_PROFILE_DIR"] = str(tmp_path)
    slots = _complete_slots()
    result = save_model_profile(
        PROJECT_ROOT,
        slots,
        persist=True,
        environ=environ,
    )
    profile_path = tmp_path / "default-profile.json"
    assert result.persisted is True
    assert result.restart_required is False
    assert len(result.safe_summary) == 4
    raw_profile = profile_path.read_text(encoding="utf-8")
    assert "unit-secret-" not in raw_profile
    assert "example.invalid" not in raw_profile
    assert "unit-secret-" not in json.dumps(result.safe_summary)
    assert "example.invalid" not in json.dumps(result.safe_summary)

    edited_slots = _complete_slots(include_secrets=False)
    edited_slots["model_a"] = ProfileSlotInput(
        adapter="openai",
        model_id="edited-model",
        reasoning_effort="high",
    )
    save_model_profile(
        PROJECT_ROOT,
        edited_slots,
        persist=True,
        environ=environ,
    )
    assert (tmp_path / "default-profile.json.bak").is_file()
    edited_profile = profile_path.read_text(encoding="utf-8")
    assert "edited-model" in edited_profile
    assert "unit-secret-" not in edited_profile
    assert "example.invalid" not in edited_profile

from __future__ import annotations

from llm_eval_workbench.metrics.deepeval_metrics import JudgeRun
from llm_eval_workbench.probe import probe_judge, probe_model
from llm_eval_workbench.schemas import (
    GenerationParams,
    JudgeConfig,
    ModelConfig,
    UsageInfo,
)


def config():
    return ModelConfig(
        alias="target",
        role="target",
        model_env="TARGET_MODEL",
        api_key_env="TARGET_KEY",
        base_url_env="TARGET_BASE",
        api_mode_env="TARGET_API_MODE",
        reasoning_effort_env="TARGET_REASONING",
        params=GenerationParams(),
    )


def test_probe_reports_usage_without_credentials(monkeypatch):
    monkeypatch.setenv("TARGET_MODEL", "openai/test-model")
    monkeypatch.setenv("TARGET_KEY", "probe-secret")
    monkeypatch.setenv("TARGET_BASE", "https://example.invalid/token")
    monkeypatch.setenv("TARGET_API_MODE", "responses")
    monkeypatch.setenv("TARGET_REASONING", "max")

    def fake_responses(**kwargs):
        assert kwargs["api_key"] == "probe-secret"
        assert kwargs["input"] == "Reply with OK."
        assert kwargs["store"] is False
        assert kwargs["stream"] is False
        assert kwargs["reasoning"] == {"effort": "max"}
        assert "reasoning_effort" not in kwargs
        return {
            "output": [
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": "OK"}],
                }
            ],
            "usage": {
                "input_tokens": 4,
                "output_tokens": 1,
                "total_tokens": 5,
            },
            "_hidden_params": {"response_cost": 0.0001},
        }

    monkeypatch.setattr("litellm.responses", fake_responses)
    result = probe_model(config())
    assert result["success"] is True
    assert result["api_mode"] == "responses"
    assert result["total_tokens"] == 5
    assert "probe-secret" not in str(result)
    assert "example.invalid" not in str(result)


def test_probe_sanitizes_provider_exception(monkeypatch):
    monkeypatch.setenv("TARGET_MODEL", "test/model")
    monkeypatch.setenv("TARGET_KEY", "probe-secret")
    monkeypatch.setenv("TARGET_API_MODE", "responses")

    def fake_responses(**kwargs):
        raise RuntimeError("provider echoed probe-secret")

    monkeypatch.setattr("litellm.responses", fake_responses)
    result = probe_model(config())
    assert result["success"] is False
    assert result["error"] == "RuntimeError"
    assert "probe-secret" not in str(result)


def test_semantic_judge_probe_uses_real_judge_contract_without_leaking_secret(
    monkeypatch,
):
    judge_model = ModelConfig(
        alias="judge",
        role="judge",
        model_env="JUDGE_MODEL",
        api_key_env="JUDGE_KEY",
        base_url_env="JUDGE_BASE",
        api_mode_env="JUDGE_API_MODE",
        params=GenerationParams(),
    )
    monkeypatch.setenv("JUDGE_MODEL", "openai/test-judge")
    monkeypatch.setenv("JUDGE_KEY", "judge-probe-secret")
    monkeypatch.setenv("JUDGE_BASE", "https://example.invalid/judge")
    monkeypatch.setenv("JUDGE_API_MODE", "responses")

    def fake_evaluate(self, case, output):
        assert self.model.api_key.get_secret_value() == "judge-probe-secret"
        assert self.model.api_mode == "responses"
        assert case.case_id == "PB-001"
        assert output.content == "OK"
        return JudgeRun(
            metrics=[],
            scores=[0.9],
            request_count=2,
            usage=UsageInfo(
                prompt_tokens=20,
                completion_tokens=10,
                total_tokens=30,
                cost=0.004,
            ),
        )

    monkeypatch.setattr(
        "llm_eval_workbench.metrics.deepeval_metrics.DeepEvalJudge.evaluate",
        fake_evaluate,
    )
    result = probe_judge(
        judge_model,
        JudgeConfig(model_alias="judge"),
    )
    assert result["success"] is True
    assert result["probe_type"] == "deepeval_judge_contract"
    assert result["request_count"] == 2
    assert result["total_tokens"] == 30
    assert result["cost"] == 0.004
    assert "judge-probe-secret" not in str(result)
    assert "example.invalid" not in str(result)

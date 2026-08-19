from __future__ import annotations

import asyncio
import inspect
import json
import os
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from types import SimpleNamespace

from llm_eval_workbench.metrics.deepeval_metrics import DeepEvalJudge
from llm_eval_workbench.schemas import GenerationParams, JudgeConfig, ModelConfig
from llm_eval_workbench.scientific_gateway import ScientificTargetGateway
from llm_eval_workbench.secrets import resolve_model


def test_deepeval_4_api_contract():
    import litellm
    from deepeval.metrics import GEval
    from deepeval.models import LiteLLMModel
    from deepeval.test_case import LLMTestCase, SingleTurnParams

    geval_parameters = inspect.signature(GEval).parameters
    model_parameters = inspect.signature(LiteLLMModel).parameters
    case_parameters = inspect.signature(LLMTestCase).parameters
    responses_parameters = inspect.signature(litellm.responses).parameters
    assert {"criteria", "model", "threshold", "async_mode"} <= set(geval_parameters)
    assert {"model", "api_key", "base_url", "temperature"} <= set(model_parameters)
    assert {"input", "actual_output", "expected_output", "context"} <= set(
        case_parameters
    )
    assert {
        "input",
        "model",
        "reasoning",
        "store",
        "stream",
        "text_format",
    } <= set(responses_parameters)
    assert SingleTurnParams.ACTUAL_OUTPUT.value == "actual_output"


def test_litellm_posts_to_responses_and_preserves_native_max_reasoning():
    import litellm

    captured: dict[str, object] = {}

    class FakeResponsesProvider(BaseHTTPRequestHandler):
        def do_POST(self):
            body_length = int(self.headers.get("content-length", "0"))
            captured["path"] = self.path
            captured["body"] = json.loads(self.rfile.read(body_length))
            payload = json.dumps(
                {
                    "id": "resp_unit_test",
                    "object": "response",
                    "created_at": 1,
                    "status": "completed",
                    "model": "test-model",
                    "output": [
                        {
                            "id": "msg_unit_test",
                            "type": "message",
                            "status": "completed",
                            "role": "assistant",
                            "content": [
                                {
                                    "type": "output_text",
                                    "text": "OK",
                                    "annotations": [],
                                }
                            ],
                        }
                    ],
                    "usage": {
                        "input_tokens": 1,
                        "output_tokens": 1,
                        "total_tokens": 2,
                    },
                    "parallel_tool_calls": True,
                    "tool_choice": "auto",
                    "tools": [],
                    "store": False,
                }
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, format, *args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeResponsesProvider)
    server_thread = Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    try:
        response = litellm.responses(
            model="openai/test-model",
            api_key="unit-test-key",
            api_base=f"http://127.0.0.1:{server.server_port}/v1",
            input="Reply with OK.",
            reasoning={"effort": "max"},
            store=False,
            stream=False,
            num_retries=0,
        )
    finally:
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=2)

    assert captured["path"] == "/v1/responses"
    request_body = captured["body"]
    assert isinstance(request_body, dict)
    assert request_body["reasoning"] == {"effort": "max"}
    assert request_body["store"] is False
    assert request_body["stream"] is False
    assert response.output_text == "OK"


def test_litellm_merges_claude_output_config_into_responses_body():
    import litellm

    captured: dict[str, object] = {}

    class FakeResponsesProvider(BaseHTTPRequestHandler):
        def do_POST(self):
            body_length = int(self.headers.get("content-length", "0"))
            captured["path"] = self.path
            captured["body"] = json.loads(self.rfile.read(body_length))
            payload = json.dumps(
                {
                    "id": "resp_claude_transport_test",
                    "object": "response",
                    "created_at": 1,
                    "status": "completed",
                    "model": "relay-model",
                    "output": [
                        {
                            "id": "msg_claude_transport_test",
                            "type": "message",
                            "status": "completed",
                            "role": "assistant",
                            "content": [
                                {
                                    "type": "output_text",
                                    "text": "OK",
                                    "annotations": [],
                                }
                            ],
                        }
                    ],
                    "usage": {
                        "input_tokens": 1,
                        "output_tokens": 1,
                        "total_tokens": 2,
                    },
                    "parallel_tool_calls": True,
                    "tool_choice": "auto",
                    "tools": [],
                    "store": False,
                }
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, format, *args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeResponsesProvider)
    server_thread = Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    try:
        response = litellm.responses(
            model="openai/relay-model",
            api_key="unit-test-key",
            api_base=f"http://127.0.0.1:{server.server_port}/v1",
            input="Reply with OK.",
            extra_body={"output_config": {"effort": "max"}},
            store=False,
            stream=False,
            num_retries=0,
        )
    finally:
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=2)

    assert captured["path"] == "/v1/responses"
    request_body = captured["body"]
    assert isinstance(request_body, dict)
    assert request_body["output_config"] == {"effort": "max"}
    assert "reasoning" not in request_body
    assert response.output_text == "OK"


def test_anthropic_relay_uses_messages_bearer_and_native_effort():
    captured: dict[str, object] = {}

    class FakeAnthropicProvider(BaseHTTPRequestHandler):
        def do_POST(self):
            body_length = int(self.headers.get("content-length", "0"))
            body = json.loads(self.rfile.read(body_length))
            captured["path"] = self.path
            captured["bearer"] = self.headers.get(
                "authorization", ""
            ).startswith("Bearer ")
            captured["x_api_key"] = "x-api-key" in {
                key.casefold() for key in self.headers.keys()
            }
            captured["body"] = body
            payload = json.dumps(
                {
                    "id": "msg_native_relay_test",
                    "type": "message",
                    "role": "assistant",
                    "model": "relay-model",
                    "content": [{"type": "text", "text": "OK"}],
                    "stop_reason": "end_turn",
                    "stop_sequence": None,
                    "usage": {"input_tokens": 1, "output_tokens": 1},
                }
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, format, *args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeAnthropicProvider)
    server_thread = Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    before_auth = os.environ.get("ANTHROPIC_AUTH_TOKEN")
    before_key = os.environ.get("ANTHROPIC_API_KEY")
    try:
        config = ModelConfig(
            alias="native-relay",
            role="target",
            model_env="NATIVE_RELAY_MODEL",
            api_key_env="NATIVE_RELAY_KEY",
            base_url_env="NATIVE_RELAY_BASE",
            api_mode_env="NATIVE_RELAY_MODE",
            reasoning_effort_env="NATIVE_RELAY_REASONING",
            params=GenerationParams(max_tokens=4096),
        )
        model = resolve_model(
            config,
            {
                "NATIVE_RELAY_MODEL": "anthropic/claude-fable-5",
                "NATIVE_RELAY_KEY": "dummy-relay-token",
                "NATIVE_RELAY_BASE": (
                    f"http://127.0.0.1:{server.server_port}"
                ),
                "NATIVE_RELAY_MODE": "responses",
                "NATIVE_RELAY_REASONING": "max",
            },
        )
        gateway = ScientificTargetGateway(model)
        request_kwargs = gateway.request_kwargs(
            instructions="Return a minimal response.",
            input_items=[{"role": "user", "content": "Reply with OK."}],
            max_output_tokens=4096,
        )
        response = asyncio.run(
            gateway.raw_request(**request_kwargs)
        )
    finally:
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=2)

    assert captured["path"] == "/v1/messages"
    assert captured["bearer"] is True
    assert captured["x_api_key"] is False
    body = captured["body"]
    assert isinstance(body, dict)
    assert body["thinking"] == {"type": "adaptive"}
    assert body["output_config"] == {"effort": "max"}
    assert "extra_body" not in body
    assert response.output_text == "OK"
    assert os.environ.get("ANTHROPIC_AUTH_TOKEN") == before_auth
    assert os.environ.get("ANTHROPIC_API_KEY") == before_key


def test_deepeval_judge_uses_litellm_and_tracks_usage(
    monkeypatch, sample_case, sample_output, resolved_judge
):
    captured_judge_prompts: list[str] = []
    captured_judge_requests: list[dict[str, object]] = []

    def fake_responses(**kwargs):
        assert kwargs["reasoning"] == {"effort": "max"}
        assert "reasoning_effort" not in kwargs
        assert kwargs["store"] is False
        assert kwargs["stream"] is False
        assert isinstance(kwargs["input"], str)
        assert "messages" not in kwargs
        captured_judge_prompts.append(kwargs["input"])
        captured_judge_requests.append(
            {key: value for key, value in kwargs.items() if key != "api_key"}
        )
        schema = kwargs.get("text_format")
        if schema is not None and "steps" in schema.model_fields:
            payload = {"steps": ["Check whether requirements are satisfied."]}
        else:
            payload = {"score": 9, "reason": "Requirements are satisfied."}
        return SimpleNamespace(
            output_text=json.dumps(payload),
            output=[],
            usage=SimpleNamespace(
                input_tokens=10,
                output_tokens=5,
                total_tokens=15,
                cost=0.002,
            ),
            _hidden_params={},
        )

    def reject_chat_completions(**kwargs):
        raise AssertionError("Chat Completions must not be called")

    monkeypatch.setattr("litellm.responses", fake_responses)
    monkeypatch.setattr("litellm.completion", reject_chat_completions)
    judge_model = replace(
        resolved_judge,
        model_name="openai/gpt-4o-mini",
        reasoning_effort="max",
        params=resolved_judge.params.model_copy(
            update={
                "extra": {
                    "reasoning": {"effort": "max"},
                }
            }
        ),
    )
    judge = DeepEvalJudge(
        judge_model,
        JudgeConfig(
            model_alias="judge",
            threshold=0.75,
            review_floor=0.45,
            repetitions=1,
            instability_delta=0.2,
        ),
    )
    blinded_output = sample_output.model_copy(
        update={
            "model_alias": "SENTINEL-TARGET-ALIAS",
            "model_name": "provider/SENTINEL-TARGET-MODEL",
            "prompt_id": "SENTINEL-TARGET-PROMPT",
            "prompt_version": "SENTINEL-TARGET-PROMPT-VERSION",
        }
    )
    result = judge.evaluate(sample_case, blinded_output)
    assert result.scores == [0.9]
    assert result.request_count == 2
    assert result.usage.prompt_tokens == 20
    assert result.usage.completion_tokens == 10
    assert result.usage.total_tokens == 30
    assert result.usage.cost == 0.004
    joined_prompts = "\n".join(captured_judge_prompts)
    serialized_requests = json.dumps(
        captured_judge_requests,
        ensure_ascii=False,
        default=str,
    )
    for hidden_identity in (
        blinded_output.model_alias,
        blinded_output.model_name,
        blinded_output.prompt_id,
        blinded_output.prompt_version,
    ):
        assert hidden_identity not in joined_prompts
        assert hidden_identity not in serialized_requests
    assert blinded_output.content in joined_prompts
    details = result.metrics[0].details
    assert details["target_identity_blinded"] is True
    assert details["blind_policy_version"] == "target-identity-blind-v1"

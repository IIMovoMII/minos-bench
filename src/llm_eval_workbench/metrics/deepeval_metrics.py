from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

from ..schemas import (
    EvaluationCase,
    GeneratedOutput,
    JudgeConfig,
    MetricResult,
    UsageInfo,
)
from ..secrets import ResolvedModel

JUDGE_BLIND_POLICY_VERSION = "target-identity-blind-v1"


@dataclass(frozen=True)
class JudgeRun:
    metrics: list[MetricResult]
    scores: list[float]
    total_cost: float | None = None
    request_count: int = 0
    usage: UsageInfo = field(default_factory=UsageInfo)


def _judge_input(case: EvaluationCase) -> str:
    if not case.turns:
        return case.input
    transcript = "\n".join(f"{turn.role}: {turn.content}" for turn in case.turns)
    return f"对话历史：\n{transcript}\n\n当前任务：\n{case.input}"


def _actual_output(output: GeneratedOutput) -> str:
    if not output.tool_calls:
        return output.content
    calls = [
        {
            "name": call.name,
            "arguments": call.arguments,
            "order": call.order,
        }
        for call in output.tool_calls
    ]
    return (
        f"最终文本：\n{output.content}\n\n"
        f"工具调用：\n{json.dumps(calls, ensure_ascii=False, sort_keys=True)}"
    )


def _expected_output(case: EvaluationCase) -> str | None:
    parts: list[str] = []
    if case.expected_output:
        parts.append(f"参考输出：{case.expected_output}")
    if case.expected_facts:
        parts.append("必须保留的事实：" + "；".join(case.expected_facts))
    if case.forbidden_facts:
        parts.append("不得出现的事实或臆测：" + "；".join(case.forbidden_facts))
    if case.expected_tools:
        parts.append(
            "预期工具调用："
            + json.dumps(
                [item.model_dump(mode="json") for item in case.expected_tools],
                ensure_ascii=False,
                sort_keys=True,
            )
        )
    if case.expected_final_behavior:
        parts.append(f"预期最终行为：{case.expected_final_behavior}")
    return "\n".join(parts) or None


def _criteria(case: EvaluationCase) -> str:
    return (
        "你在评估一个 LLM 应用输出，而不是回答用户问题。"
        "只依据本测试用例给出的输入、上下文、预期要点和 Rubric 评分；"
        "不得用外部常识补全缺失证据。"
        "客观格式、JSON Schema、工具名称和参数由外部确定性程序裁决，"
        "这里评估语义质量、完整性、相关性和有依据性。"
        "0 分表示完全不满足，1 分表示完整满足。"
        "若信息不足或标准存在歧义，应在理由中指出，不要假装确定。\n\n"
        f"任务包：{case.task_pack.value}\n"
        f"用例 Rubric：{case.rubric}"
    )


class DeepEvalJudge:
    def __init__(
        self,
        model: ResolvedModel,
        config: JudgeConfig,
    ) -> None:
        self.model = model
        self.config = config

    def evaluate(self, case: EvaluationCase, output: GeneratedOutput) -> JudgeRun:
        if self.model.api_mode != "responses":
            raise ValueError("DeepEvalJudge requires Responses API mode")
        os.environ.setdefault("DEEPEVAL_TELEMETRY_OPT_OUT", "YES")
        import litellm
        from deepeval.metrics import GEval
        from deepeval.models import LiteLLMModel
        from deepeval.models.utils import EvaluationCost
        from deepeval.test_case import LLMTestCase, SingleTurnParams

        litellm.suppress_debug_info = True

        expected_output = _expected_output(case)
        params = [
            SingleTurnParams.INPUT,
            SingleTurnParams.ACTUAL_OUTPUT,
        ]
        if expected_output is not None:
            params.append(SingleTurnParams.EXPECTED_OUTPUT)
        if case.context:
            params.append(SingleTurnParams.CONTEXT)

        generation_kwargs = {
            "max_output_tokens": self.model.params.max_tokens,
            "store": False,
            "stream": False,
            "timeout": 300,
            "num_retries": 0,
            **self.model.params.extra,
        }
        if self.model.params.seed is not None:
            generation_kwargs["seed"] = self.model.params.seed

        class TrackingResponsesLiteLLMModel(LiteLLMModel):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.request_count = 0
                self.prompt_tokens = 0
                self.completion_tokens = 0
                self.total_tokens = 0
                self.usage_known = False
                self.tracked_cost = 0.0
                self.cost_known = False

            def _responses_params(self, prompt, schema=None):
                params = {
                    "model": self.name,
                    "input": prompt,
                    "temperature": self.temperature,
                }
                if self.api_key:
                    params["api_key"] = self.api_key.get_secret_value()
                if self.base_url:
                    params["api_base"] = self.base_url
                params.update(self.kwargs)
                params.update(self.generation_kwargs)
                if schema is not None:
                    params["text_format"] = schema
                return params

            def _response_cost(self, response):
                usage = getattr(response, "usage", None)
                input_tokens = getattr(usage, "input_tokens", None)
                output_tokens = getattr(usage, "output_tokens", None)
                calculated = self.calculate_cost(
                    input_tokens,
                    output_tokens,
                    response=response,
                )
                if calculated is not None:
                    return calculated
                hidden = getattr(response, "_hidden_params", None)
                hidden_cost = (
                    hidden.get("response_cost") if isinstance(hidden, dict) else None
                )
                if hidden_cost is None:
                    return None
                return EvaluationCost(
                    float(hidden_cost),
                    input_tokens,
                    output_tokens,
                )

            @staticmethod
            def _output_text(response):
                content = getattr(response, "output_text", None)
                if isinstance(content, str):
                    return content
                parts = []
                for item in getattr(response, "output", []) or []:
                    if getattr(item, "type", None) != "message":
                        continue
                    for part in getattr(item, "content", []) or []:
                        if getattr(part, "type", None) == "output_text":
                            parts.append(str(getattr(part, "text", "")))
                return "".join(parts)

            def _parse_responses_response(self, response, schema):
                content = self._output_text(response)
                cost = self._response_cost(response)
                if schema is not None:
                    return schema.model_validate_json(content), cost
                return content, cost

            def _track_response(self, response, cost):
                usage = getattr(response, "usage", None)
                if usage is not None:
                    self.usage_known = True
                    self.prompt_tokens += int(getattr(usage, "input_tokens", 0) or 0)
                    self.completion_tokens += int(
                        getattr(usage, "output_tokens", 0) or 0
                    )
                    self.total_tokens += int(getattr(usage, "total_tokens", 0) or 0)
                self.request_count += 1
                reported_cost = cost
                if reported_cost is None:
                    hidden = getattr(response, "_hidden_params", None)
                    candidates = (
                        getattr(usage, "cost", None),
                        getattr(response, "cost", None),
                        hidden.get("response_cost")
                        if isinstance(hidden, dict)
                        else None,
                    )
                    for candidate in candidates:
                        if candidate is not None:
                            try:
                                reported_cost = float(candidate)
                            except (TypeError, ValueError):
                                continue
                            break
                if reported_cost is not None:
                    self.cost_known = True
                    self.tracked_cost += float(reported_cost)

            def _generate(self, prompt, schema=None):
                from litellm import responses

                response = responses(**self._responses_params(prompt, schema))
                value, cost = self._parse_responses_response(response, schema)
                self._track_response(response, cost)
                return value, cost

            async def _a_generate(self, prompt, schema=None):
                from litellm import aresponses

                response = await aresponses(**self._responses_params(prompt, schema))
                value, cost = self._parse_responses_response(response, schema)
                self._track_response(response, cost)
                return value, cost

            def generate_raw_response(self, prompt, top_logprobs=5):
                raise AttributeError(
                    "Responses Judge uses structured output, not Chat logprobs"
                )

            async def a_generate_raw_response(self, prompt, top_logprobs=5):
                raise AttributeError(
                    "Responses Judge uses structured output, not Chat logprobs"
                )

        judge_model = TrackingResponsesLiteLLMModel(
            model=self.model.model_name,
            api_key=self.model.api_key.get_secret_value(),
            base_url=(
                self.model.base_url.get_secret_value() if self.model.base_url else None
            ),
            temperature=0.0,
            generation_kwargs=generation_kwargs,
        )
        test_case = LLMTestCase(
            input=_judge_input(case),
            actual_output=_actual_output(output),
            expected_output=expected_output,
            context=case.context or None,
            retrieval_context=case.context or None,
            metadata={
                "case_id": case.case_id,
                "rubric_id": case.rubric_id,
                "target_identity_blinded": True,
                "blind_policy_version": JUDGE_BLIND_POLICY_VERSION,
            },
        )

        metric_results: list[MetricResult] = []
        scores: list[float] = []
        total_cost = 0.0
        cost_known = False
        for repetition in range(self.config.repetitions):
            before = {
                "requests": judge_model.request_count,
                "prompt_tokens": judge_model.prompt_tokens,
                "completion_tokens": judge_model.completion_tokens,
                "total_tokens": judge_model.total_tokens,
                "cost": judge_model.tracked_cost,
            }
            metric = GEval(
                name=f"{case.task_pack.value}_quality",
                evaluation_params=params,
                criteria=_criteria(case),
                model=judge_model,
                threshold=self.config.threshold,
                async_mode=False,
                strict_mode=False,
                verbose_mode=False,
            )
            metric.measure(test_case)
            score = float(metric.score)
            scores.append(score)
            evaluation_cost = getattr(metric, "evaluation_cost", None)
            if evaluation_cost is not None:
                total_cost += float(evaluation_cost)
                cost_known = True
            metric_results.append(
                MetricResult(
                    metric_id=(f"judge.{case.task_pack.value}.r{repetition + 1}"),
                    kind="judge",
                    passed=score >= self.config.threshold,
                    score=score,
                    threshold=self.config.threshold,
                    reason=str(metric.reason or ""),
                    hard_failure=False,
                    details={
                        "rubric_id": case.rubric_id,
                        "judge_model": self.model.model_name,
                        "judge_api_mode": self.model.api_mode,
                        "target_identity_blinded": True,
                        "blind_policy_version": JUDGE_BLIND_POLICY_VERSION,
                        "streaming": False,
                        "repetition": repetition + 1,
                        "judge_requests": (
                            judge_model.request_count - before["requests"]
                        ),
                        "judge_prompt_tokens": (
                            judge_model.prompt_tokens - before["prompt_tokens"]
                        ),
                        "judge_completion_tokens": (
                            judge_model.completion_tokens - before["completion_tokens"]
                        ),
                        "judge_total_tokens": (
                            judge_model.total_tokens - before["total_tokens"]
                        ),
                        "judge_cost": (
                            judge_model.tracked_cost - before["cost"]
                            if judge_model.cost_known
                            else None
                        ),
                    },
                )
            )
        return JudgeRun(
            metrics=metric_results,
            scores=scores,
            total_cost=(
                judge_model.tracked_cost
                if judge_model.cost_known
                else total_cost
                if cost_known
                else None
            ),
            request_count=judge_model.request_count,
            usage=UsageInfo(
                prompt_tokens=(
                    judge_model.prompt_tokens if judge_model.usage_known else None
                ),
                completion_tokens=(
                    judge_model.completion_tokens if judge_model.usage_known else None
                ),
                total_tokens=(
                    judge_model.total_tokens if judge_model.usage_known else None
                ),
                cost=(judge_model.tracked_cost if judge_model.cost_known else None),
            ),
        )

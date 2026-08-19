from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import SecretStr

from llm_eval_workbench.hashing import sha256_text
from llm_eval_workbench.schemas import (
    DataSplit,
    DeterministicCheckSpec,
    EvaluationCase,
    GeneratedOutput,
    GenerationParams,
    Language,
    SourceInfo,
    TaskPack,
)
from llm_eval_workbench.secrets import ResolvedModel

PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def project_root() -> Path:
    return PROJECT_ROOT


@pytest.fixture
def sample_case() -> EvaluationCase:
    return EvaluationCase(
        case_id="IG-900",
        task_pack=TaskPack.INSTRUCTION_GENERATION,
        task_type="instruction_following",
        language=Language.CHINESE,
        title="test case",
        input="请输出三条建议",
        expected_output="三条建议",
        rubric_id="RUBRIC-TEST",
        rubric="完整遵守要求",
        deterministic_checks=[
            DeterministicCheckSpec(
                check_id="count",
                type="list_item_count",
                description="three items",
                params={"exact": 3},
            )
        ],
        source=SourceInfo(
            type="synthetic",
            name="tests",
            reference="test:IG-900",
            license="CC0-1.0",
            design_reason="unit test",
        ),
        split=DataSplit.DEVELOPMENT,
        version="1.0",
    )


@pytest.fixture
def sample_output(sample_case: EvaluationCase) -> GeneratedOutput:
    content = "1. 第一条\n2. 第二条\n3. 第三条"
    return GeneratedOutput(
        run_id="20260730T000000Z-test1",
        case_id=sample_case.case_id,
        model_alias="model_a",
        model_name="test/model",
        prompt_id="prompt_v1",
        prompt_version="1.0",
        content=content,
        output_hash=sha256_text(content),
    )


@pytest.fixture
def resolved_target() -> ResolvedModel:
    return ResolvedModel(
        alias="model_a",
        role="target",
        model_name="test/model-a",
        api_key=SecretStr("unit-test-secret"),
        base_url=SecretStr("https://example.invalid/v1"),
        api_mode="responses",
        reasoning_effort=None,
        params=GenerationParams(temperature=0, max_tokens=200),
    )


@pytest.fixture
def resolved_judge() -> ResolvedModel:
    return ResolvedModel(
        alias="judge",
        role="judge",
        model_name="test/judge",
        api_key=SecretStr("unit-test-judge-secret"),
        base_url=SecretStr("https://judge.invalid/v1"),
        api_mode="responses",
        reasoning_effort=None,
        params=GenerationParams(temperature=0, max_tokens=200),
    )

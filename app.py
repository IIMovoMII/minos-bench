from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from llm_eval_workbench.analysis import compare_runs
from llm_eval_workbench.config import load_project_config, resolve_path
from llm_eval_workbench.dataset_service import load_many
from llm_eval_workbench.probe import probe_judge, probe_model
from llm_eval_workbench.profile_bridge import (
    ProfileBridgeError,
    ProfileSlotInput,
    runtime_slot_defaults,
    save_model_profile,
)
from llm_eval_workbench.regression_service import promote_case_to_regression
from llm_eval_workbench.report_service import export_run_report
from llm_eval_workbench.result_store import ResultStore
from llm_eval_workbench.review_service import (
    blind_case_view,
    holdout_alignment,
    latest_reviews,
    submit_review,
)
from llm_eval_workbench.run_service import RunService, run_sync
from llm_eval_workbench.schemas import (
    BadCaseCategory,
    DataSplit,
    ReviewDecision,
    RunMode,
)
from llm_eval_workbench.scientific_report import append_blind_review_item
from llm_eval_workbench.scientific_schemas import (
    HumanCriterionDecision,
    HumanCriterionReview,
)
from llm_eval_workbench.scientific_store import ScientificExecutionStore
from llm_eval_workbench.secrets import configuration_presence

st.set_page_config(
    page_title="Minos Bench｜大模型质量评测工作台",
    page_icon=":material/fact_check:",
    layout="wide",
)


CONFIG_LABELS = {
    "sample_project.yaml": "开发数据集",
    "run_model_a_prompt_v1.yaml": "候选模型一 · 提示词版本 1",
    "run_model_b_prompt_v1.yaml": "候选模型二 · 提示词版本 1",
    "run_weak_prompt_v2.yaml": "弱基线模型 · 提示词版本 2",
    "judge_stability_model_a.yaml": "评分稳定性复放",
    "regression.yaml": "回归数据集",
}

TASK_PACK_LABELS = {
    "instruction_generation": "指令生成",
    "grounded_qa": "资料问答",
    "multi_turn": "多轮对话",
    "structured_tool": "结构化与工具调用",
}

VALUE_LABELS = {
    **TASK_PACK_LABELS,
    "zh-CN": "中文",
    "en": "英文",
    "development": "开发集",
    "holdout": "密封盲测集",
    "regression": "回归集",
    "live": "真实在线评测",
    "replay": "复放已有输出",
    "deterministic-only": "仅运行确定性检查",
    "pending": "等待运行",
    "running": "运行中",
    "completed": "已完成",
    "partial": "部分完成",
    "failed": "运行失败",
    "PASS": "通过",
    "REVIEW": "需要复核",
    "FAIL": "不通过",
    "RUNTIME_ERROR": "运行错误",
    "NEEDS_MORE_EVIDENCE": "证据不足",
    "NOT_APPLICABLE": "不适用",
    "target": "目标模型",
    "judge": "评分模型",
    "public": "公开资料",
    "synthetic": "合成数据",
    "critical": "严重",
    "major": "主要",
    "minor": "轻微",
    "DIRECT_VERIFIER": "确定性核验",
    "SIGNAL_ONLY": "仅作提示",
    "SEMANTIC_REVIEW": "语义初审",
    "HUMAN_REQUIRED": "必须人工判断",
    "APPLICABLE": "适用",
    "SUFFICIENT": "证据充分",
    "INSUFFICIENT": "证据不足",
    "PASS_CANDIDATE": "达到候选通过线",
    "BORDERLINE_REVIEW": "临界，等待复核",
    "LOW_SCORE_REVIEW": "低分，等待复核",
    "constraint_omission": "遗漏约束",
    "factual_error_or_hallucination": "事实错误或编造",
    "context_inconsistency": "上下文不一致",
    "incomplete_or_redundant": "不完整或冗余",
    "json_or_format_error": "格式错误",
    "multi_turn_context_loss": "多轮信息丢失",
    "role_drift": "角色偏移",
    "wrong_tool": "工具选择错误",
    "wrong_tool_arguments_or_order": "工具参数或顺序错误",
    "tool_result_misuse": "工具结果使用错误",
    "unreasonable_refusal_or_safety": "不合理拒绝或安全问题",
    "runtime_or_evaluator_error": "运行或评分器错误",
    "other": "其他",
    "system": "系统",
    "user": "用户",
    "assistant": "模型",
    "tool": "工具",
    "true": "是",
    "false": "否",
    "1.0-dev": "1.0（开发版）",
    "prompt_v1": "提示词版本 1",
    "prompt_v2": "提示词版本 2",
}

MODEL_ALIAS_LABELS = {
    "model_a": "候选模型一",
    "model_b": "候选模型二",
    "weak_model": "弱基线模型",
    "judge": "评分模型",
}

PROTOCOL_OPTIONS = {
    "OpenAI-compatible Responses": "openai",
    "Anthropic Messages（经 LiteLLM）": "anthropic",
    "其他 LiteLLM provider": "__custom__",
}

PROFILE_SLOT_LABELS = {
    "model_a": "候选模型一",
    "model_b": "候选模型二",
    "weak_model": "弱基线模型",
    "judge": "评分模型",
}

SCIENTIFIC_CONFIG_LABELS = {
    "model_a_prompt_v1": "候选模型一 · 提示词版本 1",
    "model_b_prompt_v1": "候选模型二 · 提示词版本 1",
    "weak_prompt_v1": "弱基线模型 · 提示词版本 1",
    "weak_prompt_v2": "弱基线模型 · 提示词版本 2",
}

KEY_LABELS = {
    "alias": "逻辑槽位",
    "role": "用途",
    "model_name": "模型名称",
    "api_key": "访问凭据",
    "base_url": "接口地址",
    "run_id": "运行编号",
    "mode": "运行方式",
    "status": "运行状态",
    "model": "目标模型",
    "prompt": "提示词版本",
    "cases": "用例数",
    "completed": "已完成",
    "started_at": "开始时间",
    "case_id": "用例编号",
    "task_pack": "任务类型",
    "task_type": "任务细分",
    "language": "语言",
    "split": "数据分组",
    "source_type": "来源类型",
    "source_name": "来源名称",
    "license": "许可证",
    "tags": "标签",
    "content": "回答正文",
    "tool_calls": "工具调用",
    "environment_state": "环境状态",
    "name": "名称",
    "arguments": "参数",
    "description": "说明",
    "criterion_id": "判断点编号",
    "applicability": "适用条件",
    "authority": "判断权限",
    "severity": "严重程度",
    "behavior": "需要判断的行为",
    "evidence": "可用证据",
    "pass_condition": "通过条件",
    "fail_condition": "不通过条件",
    "abstain_condition": "证据不足条件",
    "not_applicable_condition": "不适用条件",
    "positive_example": "正面示例",
    "negative_example": "反面示例",
}

RUN_MODE_DESCRIPTIONS = {
    "live": "调用已配置的真实模型，并把每题结果立即写入本地工件。",
    "replay": "复用已有模型输出，只重新执行评测与报告链路。",
    "deterministic-only": "不调用评分模型，只执行本地确定性规则。",
}


def ui_label(value: Any) -> str:
    if value is None:
        return "—"
    raw = getattr(value, "value", value)
    if isinstance(raw, bool):
        return "是" if raw else "否"
    text = str(raw)
    return MODEL_ALIAS_LABELS.get(text, VALUE_LABELS.get(text, text))


def translated_payload(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    if isinstance(value, dict):
        return {
            KEY_LABELS.get(str(key), str(key)): translated_payload(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [translated_payload(item) for item in value]
    return ui_label(value)


def config_label(file_name: str) -> str:
    return CONFIG_LABELS.get(file_name, file_name.removesuffix(".yaml"))


def scientific_config_label(config_id: str) -> str:
    return SCIENTIFIC_CONFIG_LABELS.get(config_id, config_id)


def page_intro(title: str, description: str, icon: str) -> None:
    st.subheader(f":material/{icon}: {title}")
    st.caption(description)


def render_text_list(values: list[Any], empty_text: str = "无") -> None:
    if not values:
        st.caption(empty_text)
        return
    for value in values:
        st.markdown(f"- {value}")


def render_turns(turns: list[dict[str, Any]]) -> None:
    if not turns:
        return
    st.markdown("**对话记录**")
    for turn in turns:
        with st.container(border=True):
            st.caption(ui_label(turn.get("role")))
            st.write(turn.get("content", ""))


def render_anonymous_answer(answer: dict[str, Any]) -> None:
    with st.container(border=True):
        st.markdown("**回答正文**")
        content = answer.get("content")
        st.write(content if content else "本题没有文本回答。")
        tool_calls = answer.get("tool_calls") or []
        if tool_calls:
            st.markdown("**工具调用**")
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "工具名称": call.get("name", ""),
                            "调用参数": json.dumps(
                                call.get("arguments", {}), ensure_ascii=False
                            ),
                        }
                        for call in tool_calls
                    ]
                ),
                hide_index=True,
            )
        environment_state = answer.get("environment_state") or {}
        if environment_state:
            with st.expander("查看模拟环境状态", icon=":material/settings:"):
                st.json(translated_payload(environment_state))


def run_display_label(manifest: Any) -> str:
    started = getattr(manifest, "started_at", None)
    started_text = started.strftime("%m-%d %H:%M") if started else "时间未知"
    return (
        f"{started_text}｜{ui_label(manifest.mode)}｜"
        f"{ui_label(manifest.status)}"
    )


def show_safe_error(error: BaseException) -> None:
    if isinstance(error, (ValueError, RuntimeError, LookupError)):
        st.error(str(error))
    else:
        st.error(f"操作失败：{type(error).__name__}")


def load_cases(config_path: str):
    config = load_project_config(config_path)
    paths = [resolve_path(PROJECT_ROOT, path) for path in config.dataset_paths]
    return load_many(paths)


def store_for_config(config_path: Path) -> ResultStore:
    config = load_project_config(config_path)
    return ResultStore(resolve_path(PROJECT_ROOT, config.artifact_dir))


def _profile_slot_fields(slot_key: str, nonce: int) -> dict[str, Any]:
    defaults = runtime_slot_defaults(slot_key)
    protocol_name = next(
        (
            label
            for label, adapter in PROTOCOL_OPTIONS.items()
            if adapter == defaults.adapter
        ),
        "其他 LiteLLM provider",
    )
    protocol_names = list(PROTOCOL_OPTIONS)
    reasoning_options = ["default", "low", "medium", "high", "max"]
    if defaults.reasoning_effort not in reasoning_options:
        reasoning_options.append(defaults.reasoning_effort)
    key_prefix = f"profile_{slot_key}_{nonce}"

    with st.container(border=True):
        st.markdown(f"**{PROFILE_SLOT_LABELS[slot_key]}**")
        st.caption(
            "当前访问凭据："
            + ("已配置" if defaults.api_key_configured else "未配置")
            + "；自定义接口地址："
            + ("已配置" if defaults.base_url_configured else "未配置")
        )
        protocol = st.selectbox(
            "接口协议",
            protocol_names,
            index=protocol_names.index(protocol_name),
            key=f"{key_prefix}_protocol",
            help=(
                "OpenAI-compatible 使用 /v1/responses；Anthropic 由 LiteLLM "
                "转成 /v1/messages。项目不支持 Chat Completions。"
            ),
        )
        custom_adapter = st.text_input(
            "自定义 LiteLLM provider 前缀",
            value=(
                defaults.adapter
                if protocol == "其他 LiteLLM provider"
                else ""
            ),
            key=f"{key_prefix}_custom_adapter",
            help="例如 azure、openrouter；只在选择“其他”时使用。",
        )
        model_id = st.text_input(
            "实际模型 ID",
            value=defaults.model_id,
            key=f"{key_prefix}_model_id",
            placeholder="例如 provider 控制台中的实际模型名",
        )
        reasoning_effort = st.selectbox(
            "思考强度",
            reasoning_options,
            index=reasoning_options.index(defaults.reasoning_effort),
            key=f"{key_prefix}_reasoning",
            help="provider 不支持时可选 default；是否生效仍以接口返回为准。",
        )
        base_url = st.text_input(
            "Base URL",
            value="",
            type="password",
            key=f"{key_prefix}_base_url",
            placeholder="留空保留已保存值；首次可留空使用 provider 默认地址",
            help="填写 API 前缀，不要包含 /responses 或 /chat/completions。",
        )
        clear_base_url = st.checkbox(
            "清除已保存的自定义 Base URL",
            key=f"{key_prefix}_clear_base_url",
        )
        api_key = st.text_input(
            "API Key",
            value="",
            type="password",
            key=f"{key_prefix}_api_key",
            placeholder="留空保留已保存值；首次配置必须填写",
        )
    adapter = PROTOCOL_OPTIONS[protocol]
    if adapter == "__custom__":
        adapter = custom_adapter
    return {
        "adapter": adapter,
        "model_id": model_id,
        "reasoning_effort": reasoning_effort,
        "api_key": api_key,
        "base_url": base_url,
        "clear_base_url": clear_base_url,
    }


def _submitted_slot(values: dict[str, Any]) -> ProfileSlotInput:
    return ProfileSlotInput(
        adapter=str(values["adapter"]),
        model_id=str(values["model_id"]),
        reasoning_effort=str(values["reasoning_effort"]),
        api_key=str(values["api_key"]),
        base_url=str(values["base_url"]),
        clear_base_url=bool(values["clear_base_url"]),
    )


def render_model_configuration_page() -> None:
    page_intro(
        "模型配置",
        "先配置调用方式，再决定是否发送真实请求；保存配置本身不会联网。",
        "tune",
    )
    saved_message = st.session_state.pop("profile_save_message", None)
    if saved_message:
        st.success(saved_message, icon=":material/check_circle:")

    if os.name == "nt":
        st.caption(
            "API Key 与完整 Base URL 使用 Windows 当前用户 DPAPI 加密，"
            "保存在仓库外；页面只显示是否已配置。"
        )
    else:
        st.warning(
            "当前系统仅支持本次工作台进程内使用，关闭后需要重新配置；"
            "Windows 版支持 DPAPI 加密持久化。",
            icon=":material/info:",
        )

    setup_mode = st.segmented_control(
        "配置方式",
        ["快速体验", "完整四槽"],
        default="快速体验",
        key="profile_setup_mode",
        help="快速体验只验证工作流；正式比较必须使用完整四槽。",
    )
    nonce = int(st.session_state.setdefault("profile_form_nonce", 0))

    if setup_mode == "快速体验":
        st.info(
            "只填写一个被测模型和一个评分模型。被测模型会复制到三个目标槽位，"
            "可以跑通流程，但三个槽位相同，不能据此做模型优劣比较。",
            icon=":material/science:",
        )
        with st.form(f"quick_profile_{nonce}"):
            target_values = _profile_slot_fields("model_a", nonce)
            judge_values = _profile_slot_fields("judge", nonce)
            submitted = st.form_submit_button(
                "保存并载入配置",
                type="primary",
                icon=":material/save:",
            )
        if submitted:
            try:
                target = _submitted_slot(target_values)
                judge = _submitted_slot(judge_values)
                result = save_model_profile(
                    PROJECT_ROOT,
                    {
                        "model_a": target,
                        "model_b": target,
                        "weak_model": target,
                        "judge": judge,
                    },
                    persist=os.name == "nt",
                )
                message = "模型配置已保存并载入当前工作台。"
                if result.restart_required:
                    message += " 请关闭后从一键启动入口重新打开，再发送请求。"
                st.session_state["profile_save_message"] = message
                st.session_state["profile_form_nonce"] = nonce + 1
                st.rerun()
            except ProfileBridgeError as error:
                st.error(str(error), icon=":material/error:")
    else:
        st.caption(
            "完整模式分别配置候选模型一、候选模型二、弱基线和评分模型，"
            "用于可解释的四配置比较。"
        )
        with st.form(f"full_profile_{nonce}"):
            values_by_slot = {
                slot_key: _profile_slot_fields(slot_key, nonce)
                for slot_key in PROFILE_SLOT_LABELS
            }
            submitted = st.form_submit_button(
                "保存并载入四槽配置",
                type="primary",
                icon=":material/save:",
            )
        if submitted:
            try:
                slots = {
                    slot_key: _submitted_slot(values)
                    for slot_key, values in values_by_slot.items()
                }
                result = save_model_profile(
                    PROJECT_ROOT,
                    slots,
                    persist=os.name == "nt",
                )
                message = "四个逻辑槽位已保存并载入当前工作台。"
                if result.restart_required:
                    message += " 请关闭后从一键启动入口重新打开，再发送请求。"
                st.session_state["profile_save_message"] = message
                st.session_state["profile_form_nonce"] = nonce + 1
                st.rerun()
            except ProfileBridgeError as error:
                st.error(str(error), icon=":material/error:")


st.title("Minos Bench｜大模型质量评测工作台")
st.caption("从测试数据、自动核验到人工复核，把模型质量结论做成可追溯证据。")

config_files = sorted((PROJECT_ROOT / "configs").glob("*.yaml"))
run_configs = [
    path
    for path in config_files
    if path.name not in {"metrics.yaml", "models.example.yaml"}
]
with st.sidebar:
    st.markdown("### 评测工作区")
    selected_name = st.selectbox(
        "项目配置",
        [path.name for path in run_configs],
        index=(
            [path.name for path in run_configs].index("sample_project.yaml")
            if "sample_project.yaml" in [path.name for path in run_configs]
            else 0
        ),
        format_func=config_label,
    )
config_path = PROJECT_ROOT / "configs" / selected_name

try:
    config = load_project_config(config_path)
    cases = load_cases(str(config_path))
    store = store_for_config(config_path)
except Exception as error:
    show_safe_error(error)
    st.stop()

with st.sidebar:
    required_models_configured = all(
        configuration_presence(model)["model_name"]
        and configuration_presence(model)["api_key"]
        for model in config.models
    )
    navigation_options = [
        "模型配置",
        "项目概览",
        "数据与来源",
        "运行评测",
        "结果与比较",
        "单题复核",
        "可选人工抽检",
    ]
    page = st.radio(
        "功能导航",
        navigation_options,
        index=1 if required_models_configured else 0,
    )
    st.caption("所有数据与复核记录默认保存在本机。")


if page == "模型配置":
    render_model_configuration_page()


elif page == "项目概览":
    page_intro(
        "项目概览",
        "查看当前配置、数据规模、历史运行与模型连接状态。",
        "dashboard",
    )
    with st.container(horizontal=True):
        st.metric("项目版本", ui_label(config.version), border=True)
        st.metric("配置用例", len(cases), border=True)
        st.metric("历史运行", len(store.list_runs()), border=True)

    st.markdown("#### 模型连接状态")
    presence_rows = []
    for model in config.models:
        presence = configuration_presence(model)
        presence_rows.append(
            {
                "逻辑槽位": ui_label(model.alias),
                "用途": ui_label(model.role),
                "模型名称": "已配置" if presence["model_name"] else "未配置",
                "访问凭据": "已配置" if presence["api_key"] else "未配置",
                "接口地址": "已配置" if presence["base_url"] else "未配置",
            }
        )
    st.dataframe(pd.DataFrame(presence_rows), hide_index=True)
    st.caption("这里只显示是否已配置，不读取或回显任何凭据内容。")

    with st.expander("高级操作：连接测试", icon=":material/cable:"):
        st.caption("连接测试会产生一次真实请求；只有排查接口时才需要使用。")
        probe_alias = st.selectbox(
            "选择逻辑槽位",
            [model.alias for model in config.models],
            format_func=ui_label,
        )
        selected_probe_model = config.model_by_alias(probe_alias)
        probe_confirmed = st.checkbox(
            "我确认向评分模型发送一条固定合成评分请求"
            if selected_probe_model.role == "judge"
            else "我确认向目标模型发送一条最小文本请求"
        )
        if st.button(
            "发送连接测试",
            icon=":material/send:",
            disabled=not probe_confirmed,
        ):
            try:
                result = (
                    probe_judge(selected_probe_model, config.judge)
                    if selected_probe_model.role == "judge"
                    else probe_model(selected_probe_model)
                )
                st.success("连接测试已完成。", icon=":material/check_circle:")
                with st.expander("查看返回摘要"):
                    st.json(translated_payload(result))
            except Exception as error:
                show_safe_error(error)

    st.markdown("#### 最近运行")
    manifests = store.list_runs()
    if manifests:
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "运行编号": item.run_id,
                        "运行方式": ui_label(item.mode),
                        "运行状态": ui_label(item.status),
                        "目标模型": ui_label(item.target_model_alias),
                        "提示词版本": ui_label(item.prompt_version),
                        "用例数": item.case_count,
                        "已完成": item.completed_count,
                        "开始时间": item.started_at,
                    }
                    for item in manifests
                ]
            ),
            hide_index=True,
            column_config={
                "开始时间": st.column_config.DatetimeColumn(
                    "开始时间", format="YYYY-MM-DD HH:mm"
                )
            },
        )
    else:
        st.info("当前配置还没有运行记录。", icon=":material/info:")


elif page == "数据与来源":
    page_intro(
        "数据与来源",
        "按任务类型、数据分组和语言检查用例，并核验来源与许可证。",
        "database",
    )
    rows = [
        {
            "用例编号": case.case_id,
            "标题": case.title,
            "任务类型": ui_label(case.task_pack),
            "任务细分": case.task_type,
            "语言": ui_label(case.language),
            "数据分组": ui_label(case.split),
            "来源类型": ui_label(case.source.type),
            "来源名称": case.source.name,
            "许可证": case.source.license,
            "标签": "、".join(case.tags),
            "_task_pack": case.task_pack.value,
            "_split": case.split.value,
            "_language": case.language.value,
        }
        for case in cases
    ]
    frame = pd.DataFrame(rows)
    search_text = st.text_input(
        "搜索用例",
        placeholder="输入用例编号、标题、任务类型、来源或标签",
        icon=":material/search:",
    ).strip().casefold()
    filter_col1, filter_col2, filter_col3 = st.columns(3)
    selected_packs = filter_col1.multiselect(
        "任务类型",
        sorted(frame["_task_pack"].unique()),
        format_func=ui_label,
    )
    selected_splits = filter_col2.multiselect(
        "数据分组",
        sorted(frame["_split"].unique()),
        format_func=ui_label,
    )
    selected_languages = filter_col3.multiselect(
        "语言",
        sorted(frame["_language"].unique()),
        format_func=ui_label,
    )
    filtered = frame
    if search_text:
        searchable = frame[
            ["用例编号", "标题", "任务细分", "来源名称", "标签"]
        ].astype(str)
        mask = searchable.apply(
            lambda column: column.str.casefold().str.contains(
                search_text,
                regex=False,
            )
        ).any(axis=1)
        filtered = filtered[mask]
    if selected_packs:
        filtered = filtered[filtered["_task_pack"].isin(selected_packs)]
    if selected_splits:
        filtered = filtered[filtered["_split"].isin(selected_splits)]
    if selected_languages:
        filtered = filtered[filtered["_language"].isin(selected_languages)]
    visible_columns = [column for column in frame.columns if not column.startswith("_")]
    st.caption(f"当前显示 {len(filtered)} / {len(frame)} 条用例")
    st.dataframe(
        filtered[visible_columns],
        hide_index=True,
        column_config={
            "用例编号": st.column_config.TextColumn("用例编号", pinned=True),
            "标题": st.column_config.TextColumn("标题", pinned=True),
        },
    )
    col1, col2, col3 = st.columns(3)
    task_counts = (
        frame["任务类型"].value_counts().rename_axis("任务类型").reset_index(name="用例数")
    )
    split_counts = (
        frame["数据分组"].value_counts().rename_axis("数据分组").reset_index(name="用例数")
    )
    language_counts = (
        frame["语言"].value_counts().rename_axis("语言").reset_index(name="用例数")
    )
    with col1.container(border=True):
        st.markdown("**按任务类型**")
        st.bar_chart(task_counts, x="任务类型", y="用例数")
    with col2.container(border=True):
        st.markdown("**按数据分组**")
        st.bar_chart(split_counts, x="数据分组", y="用例数")
    with col3.container(border=True):
        st.markdown("**按语言**")
        st.bar_chart(language_counts, x="语言", y="用例数")

    service = RunService(
        project_root=PROJECT_ROOT,
        config_path=config_path,
    )
    frozen = len(cases) == 40
    if st.button("校验数据结构与来源", icon=":material/fact_check:"):
        try:
            audit = service.validate(require_frozen_contract=frozen)
            st.success("数据结构与来源校验完成。", icon=":material/check_circle:")
            with st.expander("查看校验明细"):
                st.json(translated_payload(audit))
        except Exception as error:
            show_safe_error(error)


elif page == "运行评测":
    page_intro(
        "运行评测",
        "选择运行方式和用例范围。真实在线评测会调用已配置的模型。",
        "play_circle",
    )
    mode = RunMode(
        st.selectbox(
            "运行方式",
            [item.value for item in RunMode],
            format_func=ui_label,
        )
    )
    st.caption(RUN_MODE_DESCRIPTIONS[mode.value])
    manifests = store.list_runs()
    source_run_id = None
    outputs_file = None
    if mode != RunMode.LIVE:
        source_type = st.segmented_control(
            "输出来源",
            ["历史运行", "本地结果文件"],
            default="历史运行",
            required=True,
        )
        if source_type == "历史运行":
            source_manifests = [
                item
                for item in manifests
                if item.status.value in {"completed", "partial"}
            ]
            source_options = [item.run_id for item in source_manifests]
            source_labels = {
                item.run_id: run_display_label(item) for item in source_manifests
            }
            source_run_id = st.selectbox(
                "选择历史运行",
                source_options if source_options else [""],
                format_func=lambda value: source_labels.get(value, "暂无可用运行"),
            )
        else:
            outputs_file = st.text_input(
                "项目内结果文件",
                value="fixtures/offline_outputs.jsonl",
                help="只允许项目目录内的 JSONL 文件。",
            )

    has_holdout = any(case.split == DataSplit.HOLDOUT for case in cases)
    allow_holdout = False
    if has_holdout:
        st.warning(
            "当前配置包含密封盲测集。只有配置、评分规则和阈值冻结后才应解封。",
            icon=":material/lock:",
        )
        allow_holdout = st.checkbox("我确认本次需要解封密封盲测集")

    case_title_by_id = {case.case_id: case.title for case in cases}
    selected_cases = st.multiselect(
        "指定用例（可选）",
        [case.case_id for case in cases],
        format_func=lambda value: f"{value}｜{case_title_by_id[value]}",
        placeholder="不选择时运行当前配置的全部用例",
    )
    if st.button(
        "开始评测",
        type="primary",
        icon=":material/play_arrow:",
    ):
        try:
            service = RunService(
                project_root=PROJECT_ROOT,
                config_path=config_path,
            )
            with st.spinner("评测运行中；每题结果会立即保存到本机……"):
                manifest = run_sync(
                    service,
                    mode=mode,
                    source_run_id=source_run_id or None,
                    outputs_file=outputs_file or None,
                    allow_holdout=allow_holdout,
                    case_ids=set(selected_cases) if selected_cases else None,
                )
                export_run_report(store, manifest.run_id)
            st.success(
                f"运行结束：{ui_label(manifest.status)}",
                icon=":material/check_circle:",
            )
            with st.container(horizontal=True):
                st.metric("运行用例", manifest.case_count, border=True)
                st.metric("完成用例", manifest.completed_count, border=True)
                st.metric("运行编号", manifest.run_id, border=True)
            with st.expander("查看运行技术信息"):
                st.json(translated_payload(manifest))
            st.cache_data.clear()
        except Exception as error:
            show_safe_error(error)


elif page == "结果与比较":
    page_intro(
        "结果与比较",
        "查看运行完成度、问题用例和版本差异。机器结论仍需人工复核。",
        "analytics",
    )
    manifests = store.list_runs()
    if not manifests:
        st.info("当前配置还没有运行结果。", icon=":material/info:")
        st.stop()
    run_ids = [item.run_id for item in manifests]
    manifest_by_id = {item.run_id: item for item in manifests}
    selected_run = st.selectbox(
        "查看运行",
        run_ids,
        format_func=lambda value: run_display_label(manifest_by_id[value]),
    )
    summary = store.summarize(selected_run)
    results = store.load_results(selected_run)
    status_counts = summary.status_counts
    mean_score = (
        f"{summary.mean_judge_score:.1%}"
        if summary.mean_judge_score is not None
        else "暂无"
    )
    with st.container(horizontal=True):
        st.metric("用例总数", summary.case_count, border=True)
        st.metric("通过", status_counts.get("PASS", 0), border=True)
        st.metric("需要复核", status_counts.get("REVIEW", 0), border=True)
        st.metric("不通过", status_counts.get("FAIL", 0), border=True)
        st.metric("运行错误", summary.runtime_error_count, border=True)
        st.metric("评分均值", mean_score, border=True)
    st.caption(
        f"目标模型请求 {summary.target_request_count} 次｜"
        f"评分模型请求 {summary.judge_request_count} 次｜"
        f"人工复核 {summary.human_review_count} 条"
    )

    score_band_labels = {
        "PASS_CANDIDATE": "达到候选通过线",
        "BORDERLINE_REVIEW": "临界，等待复核",
        "LOW_SCORE_REVIEW": "明显低分，等待复核",
    }
    result_rows = [
        {
            "用例编号": result.case_id,
            "任务类型": ui_label(result.task_pack),
            "结论": ui_label(result.status),
            "评测方式": ui_label(result.evaluation_scope),
            "评分模型均分": result.judge_score_mean,
            "分数位置": (
                score_band_labels.get(result.judge_score_band.value, "")
                if result.judge_score_band
                else ""
            ),
            "评分是否不稳定": ui_label(result.judge_unstable),
            "运行问题数": len(result.runtime_issues),
        }
        for result in results
    ]
    result_frame = pd.DataFrame(result_rows)
    st.dataframe(
        result_frame,
        hide_index=True,
        column_config={
            "用例编号": st.column_config.TextColumn("用例编号", pinned=True),
            "评分模型均分": st.column_config.NumberColumn(
                "评分模型均分", format="percent"
            ),
        },
    )
    if not result_frame.empty:
        conclusion_counts = (
            result_frame["结论"]
            .value_counts()
            .rename_axis("结论")
            .reset_index(name="用例数")
        )
        st.bar_chart(conclusion_counts, x="结论", y="用例数")

    with st.container(border=True):
        st.markdown("#### 比较两个运行")
        compare_left, compare_right = st.columns(2)
        baseline = compare_left.selectbox(
            "基线运行",
            run_ids,
            key="baseline",
            format_func=lambda value: run_display_label(manifest_by_id[value]),
        )
        candidate = compare_right.selectbox(
            "候选运行",
            run_ids,
            index=min(1, len(run_ids) - 1),
            key="candidate",
            format_func=lambda value: run_display_label(manifest_by_id[value]),
        )
        if st.button("比较运行", icon=":material/compare_arrows:"):
            try:
                comparison = compare_runs(store, baseline, candidate)
                case_comparisons = comparison.get("cases", [])
                summary_comparison = {
                    key: value
                    for key, value in comparison.items()
                    if key != "cases"
                }
                st.json(translated_payload(summary_comparison))
                if case_comparisons:
                    st.dataframe(
                        pd.DataFrame(
                            [translated_payload(item) for item in case_comparisons]
                        ),
                        hide_index=True,
                    )
            except Exception as error:
                show_safe_error(error)

    if st.button("重新生成报告", icon=":material/refresh:"):
        try:
            paths = export_run_report(store, selected_run)
            st.success(
                "报告已生成：" + "、".join(path.name for path in paths.values()),
                icon=":material/check_circle:",
            )
        except Exception as error:
            show_safe_error(error)


elif page == "单题复核":
    page_intro(
        "单题复核",
        "按题查看输入、模型回答、评分依据，并追加人工判断。",
        "fact_check",
    )
    manifests = store.list_runs()
    if not manifests:
        st.info("当前配置还没有运行结果。", icon=":material/info:")
        st.stop()
    manifest_by_id = {item.run_id: item for item in manifests}
    run_id = st.selectbox(
        "选择运行",
        [item.run_id for item in manifests],
        format_func=lambda value: run_display_label(manifest_by_id[value]),
    )
    outputs = store.output_by_case(run_id)
    results = store.result_by_case(run_id)
    available_ids = sorted(set(outputs) & {case.case_id for case in cases})
    if not available_ids:
        st.info("该运行没有可查看的模型输出。")
        st.stop()
    case_title_by_id = {case.case_id: case.title for case in cases}
    case_id = st.selectbox(
        "选择用例",
        available_ids,
        format_func=lambda value: f"{value}｜{case_title_by_id[value]}",
    )
    case = next(item for item in cases if item.case_id == case_id)
    output = outputs[case_id]
    result = results.get(case_id)
    reviews = latest_reviews(store, run_id)

    if case.split == DataSplit.HOLDOUT:
        alignment = holdout_alignment(
            store=store,
            run_id=run_id,
            holdout_cases=[item for item in cases if item.split == DataSplit.HOLDOUT],
        )
        if not alignment["complete"]:
            st.warning(
                f"密封盲测进行中：{alignment['reviewed_count']}/"
                f"{alignment['expected_count']}。完成前隐藏参考答案和机器结论。",
                icon=":material/lock:",
            )
            blind_view = blind_case_view(case=case, output_content=output.content)
            with st.container(border=True):
                st.markdown(f"**{case.title}**")
                st.caption(
                    f"{ui_label(case.task_pack)}｜{ui_label(case.language)}｜"
                    f"用例 {case.case_id}"
                )
                st.markdown("**用户任务**")
                st.write(case.input)
                if case.context:
                    with st.expander("查看给定资料"):
                        render_text_list(case.context)
                render_turns(blind_view.get("turns", []))
            with st.container(border=True):
                st.markdown("**匿名模型回答**")
                st.write(output.content)
            if case_id in reviews:
                st.success(
                    "本题已提交人工结论，请继续其他盲测题。",
                    icon=":material/check_circle:",
                )
            else:
                decision = st.segmented_control(
                    "你的结论",
                    [item.value for item in ReviewDecision],
                    format_func=ui_label,
                    required=True,
                )
                categories = st.multiselect(
                    "问题分类（可选）",
                    [item.value for item in BadCaseCategory],
                    format_func=ui_label,
                    key=f"blind-categories-{case_id}",
                )
                reason = st.text_area(
                    "证据与理由（必填）",
                    placeholder="指出回答中的具体内容，并说明它为什么满足或违反要求。",
                )
                if st.button(
                    "提交本题判断",
                    type="primary",
                    icon=":material/save:",
                ):
                    if not reason.strip():
                        st.error("请填写证据与理由。", icon=":material/error:")
                    else:
                        try:
                            submit_review(
                                store=store,
                                run_id=run_id,
                                case=case,
                                reviewer="candidate",
                                decision=ReviewDecision(decision),
                                reason=reason,
                                issue_categories=[
                                    BadCaseCategory(category) for category in categories
                                ],
                                blind=True,
                            )
                            st.success("已保存，不覆盖机器结果。")
                            st.rerun()
                        except Exception as error:
                            show_safe_error(error)
            st.stop()
        st.success(
            "8 条密封盲测题已全部完成。",
            icon=":material/check_circle:",
        )
        with st.expander("查看盲测一致性摘要"):
            st.json(translated_payload(alignment))

    input_col, answer_col = st.columns(2)
    with input_col.container(border=True, height="stretch"):
        st.markdown("#### 题目与资料")
        st.markdown("**用户任务**")
        st.write(case.input)
        if case.context:
            st.markdown("**给定资料**")
            render_text_list(case.context)
        if case.turns:
            render_turns(
                [turn.model_dump(mode="json", exclude_none=True) for turn in case.turns]
            )
    with answer_col.container(border=True, height="stretch"):
        st.markdown("#### 模型回答")
        st.write(output.content or "本题没有文本回答。")
        if output.tool_calls:
            with st.expander("查看工具调用"):
                st.json(
                    translated_payload(
                        [item.model_dump(mode="json") for item in output.tool_calls]
                    )
                )

    with st.container(border=True):
        st.markdown("#### 参考答案与评分规则")
        reference_col, rule_col = st.columns(2)
        with reference_col:
            st.markdown("**预期输出**")
            st.write(case.expected_output or "未设置固定参考文本。")
            st.markdown("**必须满足的事实**")
            render_text_list(case.expected_facts)
            st.markdown("**不得出现的事实**")
            render_text_list(case.forbidden_facts)
        with rule_col:
            st.markdown("**评分规则**")
            st.write(case.rubric)
    if result is not None:
        st.markdown("#### 机器初审")
        score_value = (
            f"{result.judge_score_mean:.1%}"
            if result.judge_score_mean is not None
            else "暂无"
        )
        with st.container(horizontal=True):
            st.metric("初审结论", ui_label(result.status), border=True)
            st.metric("评分模型均值", score_value, border=True)
            st.metric("评分是否不稳定", ui_label(result.judge_unstable), border=True)
            st.metric("运行问题", len(result.runtime_issues), border=True)
        with st.expander("查看机器初审技术明细"):
            st.json(translated_payload(result))

    latest_review = reviews.get(case_id)
    if latest_review is not None:
        st.markdown("#### 最新人工记录")
        with st.container(border=True):
            st.markdown(f"**人工结论：{ui_label(latest_review.decision)}**")
            st.write(latest_review.reason)
            if latest_review.issue_categories:
                st.caption(
                    "问题分类："
                    + "、".join(
                        ui_label(item) for item in latest_review.issue_categories
                    )
                )
            if latest_review.root_cause_hypothesis:
                st.markdown("**原因假设**")
                st.write(latest_review.root_cause_hypothesis)
            if latest_review.improvement_suggestion:
                st.markdown("**优化建议**")
                st.write(latest_review.improvement_suggestion)

    if case.split != DataSplit.HOLDOUT:
        st.markdown("#### 追加人工复核")
        review_decision = st.segmented_control(
            "人工结论",
            [item.value for item in ReviewDecision],
            format_func=ui_label,
            required=True,
            key=f"review-decision-{case_id}",
        )
        review_categories = st.multiselect(
            "问题分类",
            [item.value for item in BadCaseCategory],
            format_func=ui_label,
            key=f"review-categories-{case_id}",
        )
        review_reason = st.text_area(
            "判断理由（必填）",
            key=f"review-reason-{case_id}",
        )
        root_cause = st.text_area(
            "原因假设（可选）",
            help="这里只记录待验证假设，不能冒充已经证实的根因。",
            key=f"root-cause-{case_id}",
        )
        suggestion = st.text_area(
            "优化建议（可选）",
            key=f"suggestion-{case_id}",
        )
        if st.button(
            "保存人工复核",
            type="primary",
            icon=":material/save:",
            key=f"submit-review-{case_id}",
        ):
            if not review_reason.strip():
                st.error("请填写判断理由。", icon=":material/error:")
            else:
                try:
                    submit_review(
                        store=store,
                        run_id=run_id,
                        case=case,
                        reviewer="candidate",
                        decision=ReviewDecision(review_decision),
                        reason=review_reason,
                        issue_categories=[
                            BadCaseCategory(category) for category in review_categories
                        ],
                        root_cause_hypothesis=root_cause.strip() or None,
                        improvement_suggestion=suggestion.strip() or None,
                        blind=False,
                    )
                    st.success("人工复核已保存，机器原结果未被覆盖。")
                    st.rerun()
                except Exception as error:
                    show_safe_error(error)

        latest_review = latest_reviews(store, run_id).get(case_id)
        if latest_review is not None and latest_review.decision == ReviewDecision.FAIL:
            st.markdown("#### 加入回归集")
            regression_reason = st.text_input(
                "加入回归集的原因",
                key=f"regression-reason-{case_id}",
            )
            promotion_confirmed = st.checkbox(
                "我确认该用例已经人工判定为失败，并创建新的回归集版本",
                key=f"regression-confirm-{case_id}",
            )
            if st.button(
                "创建新回归版本",
                disabled=not promotion_confirmed,
                key=f"promote-regression-{case_id}",
            ):
                try:
                    promoted = promote_case_to_regression(
                        regression_dir=PROJECT_ROOT / "datasets" / "regression",
                        store=store,
                        run_id=run_id,
                        case=case,
                        reason=regression_reason,
                    )
                    st.success(
                        f"已创建回归集版本 {promoted['version']:03d}，旧版本仍保留。"
                    )
                    with st.expander("查看版本技术信息"):
                        st.json(translated_payload(promoted))
                    st.cache_data.clear()
                except Exception as error:
                    show_safe_error(error)


elif page == "可选人工抽检":
    page_intro(
        "自动评测结果与可选人工抽检",
        "评分模型已经形成机器最终报告；人工抽检只用于额外审计，不影响本次机器结论。",
        "fact_check",
    )
    execution_roots = [
        ("V3", PROJECT_ROOT / "artifacts" / "scientific_v3" / "executions"),
        ("V2", PROJECT_ROOT / "artifacts" / "scientific_v2" / "executions"),
        ("V1", PROJECT_ROOT / "artifacts" / "scientific_v1" / "executions"),
    ]
    available: list[tuple[str, Path]] = []
    for version, root in execution_roots:
        if root.exists():
            available.extend(
                (version, path)
                for path in sorted(root.iterdir(), reverse=True)
                if path.is_dir()
                and (path / "candidate_blind_review_package.json").is_file()
            )
    if not available:
        st.info("目前没有可复核的匿名评测批次。", icon=":material/info:")
        st.stop()
    execution_keys = [f"{version}:{path.name}" for version, path in available]
    execution_entries = dict(zip(execution_keys, available, strict=True))
    execution_labels = {
        key: f"{version} 匿名评测批次｜{path.name}"
        for key, (version, path) in execution_entries.items()
    }
    execution_id = st.selectbox(
        "评测批次",
        execution_keys,
        format_func=lambda value: execution_labels[value],
    )
    selected_version, selected_path = execution_entries[execution_id]
    scientific_store = ScientificExecutionStore(
        selected_path.parent, selected_path.name
    )
    with st.expander("查看批次技术信息", icon=":material/info:"):
        st.code(execution_id)

    machine_report_path = scientific_store.directory / "machine_final_report.json"
    if machine_report_path.is_file():
        machine_report = json.loads(machine_report_path.read_text(encoding="utf-8"))
        validation = machine_report.get("judge_validation_summary") or {}
        if validation.get("required_this_run", True):
            validation_message = "本批次已完成 Judge 体检；运行错误未计作内容 0 分。"
        else:
            validation_message = (
                "本批次复用已验收的 Judge 引擎，未重复调用体检题；"
                "运行错误未计作内容 0 分。"
            )
        st.success(validation_message, icon=":material/check_circle:")
        with st.container(horizontal=True):
            st.metric(
                "运行完成率",
                f"{machine_report.get('completion_rate', 0):.0%}",
                border=True,
            )
            st.metric(
                "判断覆盖率",
                f"{machine_report.get('judgment_coverage', 0):.0%}",
                border=True,
            )
            if validation.get("required_this_run", True):
                st.metric(
                    "评分模型体检",
                    f"{validation.get('completed_items', 0)}",
                    border=True,
                )
                agreement = validation.get("mean_item_agreement_supplemental")
                st.metric(
                    "体检参考一致率",
                    f"{agreement:.0%}" if agreement is not None else "无可用值",
                    border=True,
                )
            else:
                st.metric("评分模型体检", "复用既有验收", border=True)
                st.metric("体检参考一致率", "不在本轮重复", border=True)

        config_rows = []
        for config_id, summary in machine_report.get("config_summaries", {}).items():
            status_counts = summary.get("status_counts") or {}
            errors = summary.get("confirmed_error_counts") or {}
            task_scores = summary.get("task_pack_scores") or {}
            config_rows.append(
                {
                    "评测配置": scientific_config_label(config_id),
                    "参考总分": summary.get("reference_score"),
                    "指令生成": task_scores.get("instruction_generation"),
                    "资料问答": task_scores.get("grounded_qa"),
                    "多轮对话": task_scores.get("multi_turn"),
                    "结构化与工具": task_scores.get("structured_tool"),
                    "通过题": status_counts.get("PASS", 0),
                    "需关注题": status_counts.get("REVIEW", 0),
                    "不通过题": status_counts.get("FAIL", 0),
                    "严重错误": errors.get("critical", 0),
                    "主要错误": errors.get("major", 0),
                    "轻微错误": errors.get("minor", 0),
                    "存在发布阻断": (
                        "是"
                        if summary.get("critical_error_blocks_release")
                        else "否"
                    ),
                }
            )
        st.markdown("#### 各配置评测结果")
        st.dataframe(
            pd.DataFrame(config_rows),
            hide_index=True,
            column_config={
                "评测配置": st.column_config.TextColumn("评测配置", pinned=True),
                "参考总分": st.column_config.NumberColumn(
                    "参考总分", format="%.2f"
                ),
                "指令生成": st.column_config.NumberColumn(
                    "指令生成", format="%.2f"
                ),
                "资料问答": st.column_config.NumberColumn(
                    "资料问答", format="%.2f"
                ),
                "多轮对话": st.column_config.NumberColumn(
                    "多轮对话", format="%.2f"
                ),
                "结构化与工具": st.column_config.NumberColumn(
                    "结构化与工具", format="%.2f"
                ),
            },
        )
        st.caption(
            "参考总分按单题判断点汇总、任务包内取平均、四类任务等权计算。"
            "严重错误单独形成发布阻断，不能被高平均分抵消。"
        )

        comparison_rows = []
        comparison_labels = {
            "model_a_vs_model_b": "候选模型一 对比 候选模型二",
            "weak_prompt_v1_vs_v2": "弱基线提示词版本 1 对比版本 2",
        }
        for comparison_id, comparison in machine_report.get(
            "comparisons", {}
        ).items():
            counts = comparison.get("counts") or {}
            comparison_rows.append(
                {
                    "对比组": comparison_labels.get(comparison_id, comparison_id),
                    "后者更好": counts.get("fixed", 0),
                    "后者更差": counts.get("regressed", 0),
                    "持平": counts.get("tied", 0),
                }
            )
        if comparison_rows:
            st.markdown("#### 逐题对比")
            st.dataframe(pd.DataFrame(comparison_rows), hide_index=True)
    else:
        st.info(
            "该历史批次没有机器最终报告，仅保留匿名材料用于失败审计。",
            icon=":material/history:",
        )

    st.markdown("#### 可选人工抽检")
    st.caption(
        "以下页面继续隐藏模型和提示词身份。抽检记录只追加保存，不改写机器最终报告。"
    )
    package = json.loads(
        (
            scientific_store.directory / "candidate_blind_review_package.json"
        ).read_text(encoding="utf-8")
    )
    reviewed_ids: set[str] = set()
    reviews_path = scientific_store.directory / "candidate_reviews.jsonl"
    if reviews_path.exists():
        for raw_line in reviews_path.read_text(encoding="utf-8").splitlines():
            if raw_line.strip():
                reviewed_ids.add(str(json.loads(raw_line)["review_item_id"]))
    items = package["items"]
    pending = [item for item in items if item["review_item_id"] not in reviewed_ids]
    total_count = len(items)
    reviewed_count = len(reviewed_ids)
    with st.container(horizontal=True):
        st.metric("可抽检答案", total_count, border=True)
        st.metric("已抽检", reviewed_count, border=True)
        st.metric("未抽检", len(pending), border=True)
    st.progress(reviewed_count / total_count if total_count else 0.0)
    if st.session_state.pop("blind_review_saved", False):
        st.toast("本条判断已保存。", icon=":material/check_circle:")
    if not pending:
        st.success(
            "可选人工抽检已经全部完成；机器最终报告保持不变。",
            icon=":material/check_circle:",
        )
        st.stop()
    item_number_by_id = {
        value["review_item_id"]: index
        for index, value in enumerate(items, start=1)
    }
    item_by_id = {value["review_item_id"]: value for value in items}

    def review_item_label(value: str) -> str:
        review_item = item_by_id[value]
        return (
            f"第 {item_number_by_id[value]} 项｜"
            f"{ui_label(review_item.get('task_pack'))}"
        )

    review_item_id = st.selectbox(
        "选择一条未抽检答案",
        [item["review_item_id"] for item in pending],
        format_func=review_item_label,
    )
    item = item_by_id[review_item_id]
    current_number = item_number_by_id[review_item_id]
    st.markdown(f"### 第 {current_number} 项：{ui_label(item.get('task_pack'))}")

    with st.container(border=True):
        st.markdown("#### 任务与证据")
        st.markdown("**目标**")
        st.write(item.get("user_goal") or "未提供任务目标。")
        st.markdown("**用户任务**")
        st.write(item.get("input") or "未提供文本任务。")
        context = item.get("context") or []
        if context:
            st.markdown("**给定资料**")
            render_text_list(context)
        render_turns(item.get("turns") or [])
        available_tools = item.get("available_tools") or []
        tool_outputs = item.get("tool_outputs") or []
        if available_tools or tool_outputs:
            with st.expander(
                "查看工具定义与模拟返回",
                icon=":material/build:",
            ):
                if available_tools:
                    st.markdown("**可用工具**")
                    st.json(translated_payload(available_tools))
                if tool_outputs:
                    st.markdown("**模拟工具返回**")
                    st.json(translated_payload(tool_outputs))

    st.markdown("#### 匿名回答")
    render_anonymous_answer(item["candidate_answer"])

    direct_contracts = item.get("direct_contracts") or []
    if direct_contracts:
        with st.expander(
            "查看确定性核验规则（只帮助理解，不显示核验结果）",
            icon=":material/rule:",
        ):
            for index, contract in enumerate(direct_contracts, start=1):
                st.markdown(f"**规则 {index}**")
                st.write(contract.get("description", ""))
                st.caption(
                    f"{ui_label(contract.get('authority'))}｜"
                    f"{ui_label(contract.get('severity'))}｜"
                    f"适用条件：{contract.get('applicability', '始终适用')}"
                )

    reviews: list[HumanCriterionReview] = []
    valid = True
    st.markdown("#### 逐项判断")
    st.caption("每个判断点都必须选择结论，并引用回答中的具体证据。")
    with st.form(f"blind-review-form-{review_item_id}", border=False):
        for index, criterion in enumerate(item["semantic_criteria"], start=1):
            criterion_id = criterion["criterion_id"]
            with st.container(border=True):
                st.markdown(f"##### 判断点 {index}")
                st.write(criterion["behavior"])
                evidence = criterion.get("evidence") or []
                if evidence:
                    st.markdown("**可用证据**")
                    render_text_list(evidence)
                pass_col, fail_col = st.columns(2)
                with pass_col:
                    st.markdown("**通过条件**")
                    st.write(criterion.get("pass_condition") or "未预先登记。")
                with fail_col:
                    st.markdown("**不通过条件**")
                    st.write(criterion.get("fail_condition") or "未预先登记。")
                with st.expander("查看证据不足、不适用条件和示例"):
                    st.markdown("**证据不足条件**")
                    st.write(criterion.get("abstain_condition") or "未预先登记。")
                    st.markdown("**不适用条件**")
                    st.write(
                        criterion.get("not_applicable_condition") or "未预先登记。"
                    )
                    st.markdown("**正面示例**")
                    st.write(criterion.get("positive_example") or "无")
                    st.markdown("**反面示例**")
                    st.write(criterion.get("negative_example") or "无")
                    st.caption(
                        f"判断权限：{ui_label(criterion.get('authority'))}｜"
                        f"严重程度：{ui_label(criterion.get('severity'))}"
                    )
                decision = st.segmented_control(
                    "你的判断",
                    [value.value for value in HumanCriterionDecision],
                    format_func=ui_label,
                    required=True,
                    width="stretch",
                    key=(
                        f"scientific-decision-{review_item_id}-{criterion_id}"
                    ),
                )
                reason = st.text_area(
                    "证据与理由（必填）",
                    placeholder=(
                        "引用匿名回答中的具体内容，并说明它如何满足或违反条件。"
                    ),
                    key=f"scientific-reason-{review_item_id}-{criterion_id}",
                )
                if decision is None or not reason.strip():
                    valid = False
                else:
                    reviews.append(
                        HumanCriterionReview(
                            criterion_id=criterion_id,
                            decision=HumanCriterionDecision(decision),
                            reason=reason.strip(),
                        )
                    )
        submitted = st.form_submit_button(
            "保存本条抽检并进入下一项",
            type="primary",
            icon=":material/save:",
            width="stretch",
        )
    if submitted:
        if not valid or len(reviews) != len(item["semantic_criteria"]):
            st.error(
                "请为每个判断点选择结论并填写证据与理由。",
                icon=":material/error:",
            )
        else:
            try:
                append_blind_review_item(
                    store=scientific_store,
                    review_item_id=review_item_id,
                    criteria=reviews,
                )
                st.session_state["blind_review_saved"] = True
                st.rerun()
            except Exception as error:
                show_safe_error(error)

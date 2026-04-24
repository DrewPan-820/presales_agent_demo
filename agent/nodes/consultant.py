"""阶段一：售前顾问节点。

负责通过多轮对话收集 6 项业务数据，生成《前期需求调研确认单》，
并在客户明确确认后将 phase 切换为 "done"，触发图路由到架构师节点。
"""
from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

from agent.llm import chat, chat_json
from agent.states import (
    REQUIREMENT_FIELDS,
    PresalesState,
    RequirementsDict,
    empty_requirements,
    is_requirements_complete,
)


# ---------------------------------------------------------------------------
# Prompt 片段
# ---------------------------------------------------------------------------

_FIELDS_LIST_TEXT = "\n".join(
    f"  {idx + 1}. {label}（字段名：`{key}`）"
    for idx, (key, label) in enumerate(REQUIREMENT_FIELDS)
)


CONSULTANT_SYSTEM_PROMPT = f"""你是一名专业的 AI 视觉售前顾问，公司的产品是一套面向工业现场的 AI 视频分析方案，
覆盖边缘推理盒、训练机、推理盒管理终端、中心服务器（推训一体）。

你的目标：通过多轮自然对话，收集客户在以下 6 个维度的需求信息：
{_FIELDS_LIST_TEXT}

沟通原则（严格遵守）：
1. 循序渐进：每轮回复中只提问 1-2 个尚未明确的维度，绝不一次性盘问所有维度。
2. 宽容机制：若客户对某些技术细节明确表示"不知道/待定/后续再说"，将该字段记为"待定"并继续推进，不要纠缠。
3. 主动复述：客户提供关键信息后，可用一句话简短复述确认，但不要重复整段。
4. 风格：专业、亲切、克制，每次回复控制在 3-5 句话内。
5. 不要在普通对话中输出 Markdown 表格或确认单，那是后续步骤的产出。
"""


EXTRACTOR_SYSTEM_PROMPT = """你是一个信息抽取助手。
请从用户与售前顾问的完整对话中，抽取以下 6 个字段的当前最新值：
- industry（所属行业）
- scenarios（核心场景/痛点）
- camera_count（监控点位数，可包含数字+单位，例如 "20 路"）
- kpi（预期准确率/漏报率指标）
- environment（物理与IT环境，例如光照/网络/部署空间）
- cycle_time（业务节拍 / 最大容忍延迟）

抽取规则：
- 客户明确表达"不知道/待定/后续确认"等含义时，对应字段填字符串 "待定"。
- 客户尚未提及的字段，填空字符串 ""。
- 不要臆造内容，只能根据对话原文提炼。
- 严格输出 JSON 对象，键名与上述完全一致。"""


CONFIRM_INTENT_SYSTEM_PROMPT = """你是一个意图分类助手。
售前顾问刚刚向客户展示了一份《前期需求调研确认单》。请根据客户的最新回复，判断客户意图：
- 若客户明确表达同意/确认/没问题/可以等含义，返回 {"confirmed": true, "correction": ""}
- 若客户提出修改/补充/纠正/还有疑问，返回 {"confirmed": false, "correction": "<客户希望修改或补充的内容原文摘要>"}

严格输出 JSON 对象。"""


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------

def _to_openai_messages(messages: list[BaseMessage]) -> list[dict[str, str]]:
    """把 LangGraph 消息转成 OpenAI chat 格式。"""
    out: list[dict[str, str]] = []
    for msg in messages:
        if isinstance(msg, SystemMessage):
            out.append({"role": "system", "content": msg.content})
        elif isinstance(msg, HumanMessage):
            out.append({"role": "user", "content": msg.content})
        elif isinstance(msg, AIMessage):
            out.append({"role": "assistant", "content": msg.content})
    return out


def _format_dialogue_for_extraction(messages: list[BaseMessage]) -> str:
    lines: list[str] = []
    for msg in messages:
        if isinstance(msg, HumanMessage):
            lines.append(f"客户：{msg.content}")
        elif isinstance(msg, AIMessage):
            lines.append(f"顾问：{msg.content}")
    return "\n".join(lines)


def _extract_requirements(
    messages: list[BaseMessage],
    previous: RequirementsDict | None,
) -> RequirementsDict:
    dialogue = _format_dialogue_for_extraction(messages)
    if not dialogue.strip():
        return previous or empty_requirements()

    extracted = chat_json(
        [
            {"role": "system", "content": EXTRACTOR_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    "【已收集字段（可能为旧值，请基于最新对话覆盖）】\n"
                    f"{json.dumps(previous or {}, ensure_ascii=False)}\n\n"
                    f"【完整对话】\n{dialogue}"
                ),
            },
        ]
    )

    merged = empty_requirements()
    if previous:
        merged.update(previous)
    for key, _ in REQUIREMENT_FIELDS:
        new_val = (extracted.get(key) or "").strip()
        if new_val:
            merged[key] = new_val  # type: ignore[literal-required]
    return merged


def _build_confirmation_doc(req: RequirementsDict) -> str:
    rows = "\n".join(
        f"| {label} | {req.get(key) or '待定'} |"
        for key, label in REQUIREMENT_FIELDS
    )
    return (
        "## 前期需求调研确认单\n\n"
        "| 维度 | 客户确认内容 |\n"
        "|------|------------|\n"
        f"{rows}\n\n"
        "请确认以上信息是否准确。\n"
        "- 若无误，请回复\"确认\"；\n"
        "- 若有出入，请直接告诉我需要修改/补充的内容，我会更新后再次与您核对。"
    )


def _ask_followup(messages: list[BaseMessage], req: RequirementsDict) -> str:
    """生成下一轮顾问回复（用于继续追问缺失维度）。"""
    summary_lines = []
    missing_labels = []
    for key, label in REQUIREMENT_FIELDS:
        val = (req.get(key) or "").strip()
        if val:
            summary_lines.append(f"- {label}：{val}")
        else:
            missing_labels.append(label)

    summary = "\n".join(summary_lines) if summary_lines else "（暂无）"
    missing_text = "、".join(missing_labels) if missing_labels else "（无缺失）"

    sys_with_context = (
        CONSULTANT_SYSTEM_PROMPT
        + "\n\n【已收集到的字段】\n"
        + summary
        + "\n\n【尚未明确的字段】\n"
        + missing_text
        + "\n\n请基于以上上下文继续与客户对话。优先就最关键的 1-2 个缺失字段提问。"
    )

    chat_messages: list[dict[str, str]] = [{"role": "system", "content": sys_with_context}]
    chat_messages.extend(_to_openai_messages(messages))
    return chat(chat_messages, temperature=0.5)


def _classify_confirmation(latest_user_text: str, current_doc: str) -> dict[str, Any]:
    return chat_json(
        [
            {"role": "system", "content": CONFIRM_INTENT_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"【当前确认单】\n{current_doc}\n\n"
                    f"【客户最新回复】\n{latest_user_text}"
                ),
            },
        ]
    )


def _latest_human_text(messages: list[BaseMessage]) -> str:
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            return msg.content
    return ""


# ---------------------------------------------------------------------------
# LangGraph 节点函数
# ---------------------------------------------------------------------------

def consultant_node(state: PresalesState) -> dict[str, Any]:
    messages: list[BaseMessage] = state.get("messages", []) or []
    phase = state.get("phase") or "consulting"
    requirements = state.get("requirements") or empty_requirements()
    confirmation_doc = state.get("confirmation_doc") or ""

    # ---------- 分支 A：当前正在等待客户确认 ----------
    if phase == "confirmed" and confirmation_doc:
        latest_user = _latest_human_text(messages)
        intent = _classify_confirmation(latest_user, confirmation_doc)
        if intent.get("confirmed"):
            ack = "好的，已收到您的确认。我马上为您出具技术方案与报价，请稍候……"
            return {
                "messages": [AIMessage(content=ack)],
                "phase": "done",
            }

        # 客户希望修改 → 重新抽取并重发确认单
        updated_req = _extract_requirements(messages, requirements)
        new_doc = _build_confirmation_doc(updated_req)
        reply = (
            "好的，我已根据您的反馈更新了调研内容，请您再次核对：\n\n" + new_doc
        )
        return {
            "messages": [AIMessage(content=reply)],
            "phase": "confirmed",
            "requirements": updated_req,
            "confirmation_doc": new_doc,
        }

    # ---------- 分支 B：常规需求挖掘 ----------
    updated_req = _extract_requirements(messages, requirements)

    if is_requirements_complete(updated_req):
        doc = _build_confirmation_doc(updated_req)
        reply = (
            "感谢您的耐心沟通，根据我们刚才的交流，我整理了一份《前期需求调研确认单》，"
            "请您过目：\n\n" + doc
        )
        return {
            "messages": [AIMessage(content=reply)],
            "phase": "confirmed",
            "requirements": updated_req,
            "confirmation_doc": doc,
        }

    reply = _ask_followup(messages, updated_req)
    return {
        "messages": [AIMessage(content=reply)],
        "phase": "consulting",
        "requirements": updated_req,
    }

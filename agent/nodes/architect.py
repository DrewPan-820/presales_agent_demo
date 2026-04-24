"""阶段二：方案架构师节点。

输入：state["requirements"]
输出：一份 Markdown 格式的《技术架构选型方案 + 报价表》，写入 state["solution"]，
并以 AIMessage 形式追加到 messages，供 UI 直接渲染。
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from langchain_core.messages import AIMessage

from agent.llm import chat
from agent.states import REQUIREMENT_FIELDS, PresalesState


KB_DIR = Path(__file__).resolve().parents[2] / "knowledge_base"


@lru_cache(maxsize=1)
def _load_products() -> str:
    return (KB_DIR / "products.json").read_text(encoding="utf-8")


@lru_cache(maxsize=1)
def _load_pricing_rules() -> str:
    return (KB_DIR / "pricing_rules.md").read_text(encoding="utf-8")


ARCHITECT_SYSTEM_PROMPT = """你是一名资深的 AI 视觉解决方案架构师。你将基于客户需求和公司产品目录，
一次性输出一份完整、可直接交付客户的《技术方案与报价》文档。

【输出结构（必须严格遵守，使用一级/二级 Markdown 标题）】
# 技术架构选型方案

## 一、场景分析
（3-5 句话，结合客户行业、痛点、点位规模、节拍要求，说明为什么这是 AI 视频分析的合适场景。）

## 二、推荐架构
（说明边缘部署 vs 中心部署的选择依据；如涉及训练机/管理终端，说明配置原因。）

## 三、产品选型与报价
（必须是 Markdown 表格，列：产品型号 | 用途 | 数量 | 单价（万元） | 小计（万元）。
最后一行为合计。所有金额保留 1 位小数。）

## 四、合计金额
（再次明确总价，单位：万元。）

## 五、补充说明
（针对客户需求中标记为"待定"的字段，给出后续如何确认/兜底建议；
若有可选增值服务（如算法定制、年度运维），在此处建议性提出。）

【硬性约束】
- 严格只能从【产品目录】中选用型号，不要虚构。
- 数量推算逻辑必须合理（参考【报价规则】中的分档建议）。
- 推理盒台数 ≥ 3 时必须配 EdgeManager。
- 每个项目都必须包含一项实施服务费。
- 若客户明确"数据不出厂/需现场迭代"，必须包含 TrainBox 或 CenterServer 推训一体方案。
- 输出语言：中文。
- 不要寒暄、不要追问，直接输出最终方案。
"""


def _format_requirements(req: dict[str, Any]) -> str:
    lines = []
    for key, label in REQUIREMENT_FIELDS:
        val = (req.get(key) or "待定").strip() or "待定"
        lines.append(f"- {label}：{val}")
    return "\n".join(lines)


def architect_node(state: PresalesState) -> dict[str, Any]:
    req = state.get("requirements") or {}

    user_prompt = (
        "【客户需求】\n"
        f"{_format_requirements(req)}\n\n"
        "【产品目录（JSON）】\n"
        f"{_load_products()}\n\n"
        "【报价与选型规则】\n"
        f"{_load_pricing_rules()}\n\n"
        "请按系统提示中的结构输出最终方案。"
    )

    solution = chat(
        [
            {"role": "system", "content": ARCHITECT_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.3,
    )

    return {
        "messages": [AIMessage(content=solution)],
        "solution": solution,
        "phase": "delivered",
    }

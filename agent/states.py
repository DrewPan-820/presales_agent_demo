"""LangGraph 全局状态定义。"""
from __future__ import annotations

from typing import Annotated, TypedDict

from langgraph.graph.message import add_messages


REQUIREMENT_FIELDS: list[tuple[str, str]] = [
    ("industry", "所属行业"),
    ("scenarios", "核心场景（具体痛点）"),
    ("camera_count", "监控点位数"),
    ("kpi", "预期准确率/漏报率指标"),
    ("environment", "物理与IT环境（光照/网络/部署空间）"),
    ("cycle_time", "业务节拍（产线节拍 / 最大容忍延迟）"),
]


class RequirementsDict(TypedDict, total=False):
    industry: str
    scenarios: str
    camera_count: str
    kpi: str
    environment: str
    cycle_time: str


class PresalesState(TypedDict, total=False):
    """整张图共享的状态。

    phase 取值：
      - "consulting"：阶段一，正在挖掘需求
      - "confirmed"：已生成确认单，等待客户确认
      - "done"：客户已确认，应该跳转到架构师节点
    """

    messages: Annotated[list, add_messages]
    phase: str
    requirements: RequirementsDict
    confirmation_doc: str
    solution: str


def empty_requirements() -> RequirementsDict:
    return {key: "" for key, _ in REQUIREMENT_FIELDS}  # type: ignore[return-value]


def is_requirements_complete(req: RequirementsDict) -> bool:
    """所有 6 个字段均有具体值或被显式标记为 '待定' 时视为完成。"""
    for key, _ in REQUIREMENT_FIELDS:
        value = (req or {}).get(key, "")
        if not value or not str(value).strip():
            return False
    return True

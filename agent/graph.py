"""LangGraph 图定义。"""
from __future__ import annotations

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

from agent.nodes.architect import architect_node
from agent.nodes.consultant import consultant_node
from agent.states import PresalesState


def _route_after_consultant(state: PresalesState) -> str:
    """阶段一结束后的路由：

    - phase == "done"：客户已确认调研单 → 跳到架构师节点
    - 其他情况（"consulting" / "confirmed"）：本轮结束，等待下一次用户输入
    """
    if state.get("phase") == "done":
        return "architect"
    return END


def build_graph():
    graph = StateGraph(PresalesState)
    graph.add_node("consultant", consultant_node)
    graph.add_node("architect", architect_node)

    graph.set_entry_point("consultant")
    graph.add_conditional_edges(
        "consultant",
        _route_after_consultant,
        {"architect": "architect", END: END},
    )
    graph.add_edge("architect", END)

    return graph.compile(checkpointer=MemorySaver())


compiled_graph = build_graph()

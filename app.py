"""Streamlit UI 入口。

启动方式：
    streamlit run app.py
"""
from __future__ import annotations

import os
from datetime import datetime
from uuid import uuid4

import streamlit as st
from dotenv import find_dotenv, load_dotenv
from langchain_core.messages import AIMessage, HumanMessage


def _load_secrets_into_env() -> None:
    """把 Streamlit Cloud 上的 Secrets 注入到环境变量。

    - 本地：没有 secrets.toml 时静默跳过，继续走 .env
    - 云端：secrets 中的值会先写入 os.environ，之后的 load_dotenv
      若本地没有 .env 不会覆盖它们；本地有 .env 时 .env 优先。
    """
    try:
        secrets = st.secrets
    except Exception:  # FileNotFoundError / StreamlitSecretNotFoundError
        return
    for key in ("LLM_API_KEY", "LLM_BASE_URL", "LLM_MODEL", "OPENAI_API_KEY"):
        try:
            if key in secrets:
                os.environ[key] = str(secrets[key])
        except Exception:
            continue


_load_secrets_into_env()

ENV_PATH = find_dotenv(usecwd=True)
load_dotenv(ENV_PATH, override=True)

from agent.exporters import markdown_to_docx  # noqa: E402
from agent.graph import compiled_graph  # noqa: E402
from agent.states import REQUIREMENT_FIELDS  # noqa: E402


PHASE_META = {
    "consulting": ("需求挖掘中", "blue", "💬"),
    "confirmed": ("等待客户确认", "orange", "📋"),
    "done": ("生成方案中", "green", "⚙️"),
    "delivered": ("方案已交付", "violet", "✅"),
}


# ---------------------------------------------------------------------------
# 页面初始化
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="AI 视觉售前 Agent",
    page_icon="🎯",
    layout="wide",
)

st.title("🎯 售前 Agent")
st.caption("两阶段对话：需求挖掘 → 方案与报价自动生成")

if "thread_id" not in st.session_state:
    st.session_state.thread_id = str(uuid4())
if "history" not in st.session_state:
    st.session_state.history = []
    greeting = (
        "您好，我是 AI 视觉售前顾问。\n\n"
        "我们的产品可帮助您在工业现场实现 SOP 合规监测、违规行为识别、动态计数等场景。"
        "为给您输出最合适的方案与报价，我会先简短了解几个关键信息。\n\n"
        "请问贵司所属哪个行业？目前希望用 AI 视频分析解决什么具体问题？"
    )
    st.session_state.history.append(("assistant", greeting))


# ---------------------------------------------------------------------------
# 抓取当前会话状态（侧边栏 / 下载按钮均依赖）
# ---------------------------------------------------------------------------

config = {"configurable": {"thread_id": st.session_state.thread_id}}
snapshot = compiled_graph.get_state(config)
state_values = snapshot.values if snapshot and snapshot.values else {}
phase = state_values.get("phase") or "consulting"
requirements = state_values.get("requirements") or {}
solution_md = state_values.get("solution") or ""


# ---------------------------------------------------------------------------
# 侧边栏
# ---------------------------------------------------------------------------

with st.sidebar:
    # ---- 阶段徽章 ----
    label, color, icon = PHASE_META.get(phase, ("未知", "gray", "❓"))
    st.markdown("### 当前阶段")
    st.markdown(f":{color}-background[**{icon}  {label}**]")

    st.markdown("")

    # ---- 调研进度 ----
    collected = sum(
        1 for k, _ in REQUIREMENT_FIELDS if (requirements.get(k) or "").strip()
    )
    total = len(REQUIREMENT_FIELDS)
    st.markdown("### 调研进度")
    st.progress(collected / total, text=f"已收集 {collected} / {total}")

    for key, label in REQUIREMENT_FIELDS:
        val = (requirements.get(key) or "").strip()
        if val == "待定":
            st.markdown(f"⏸️ **{label}** &nbsp;·&nbsp; :gray[待定]")
        elif val:
            display = val if len(val) <= 18 else val[:16] + "…"
            st.markdown(f"✅ **{label}** &nbsp;·&nbsp; :green[{display}]")
        else:
            st.markdown(f"⏳ **{label}** &nbsp;·&nbsp; :gray[未收集]")

    st.markdown("")

    # ---- 模型配置（折叠） ----
    with st.expander("⚙️ 模型配置", expanded=False):
        has_key = bool(os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY"))
        st.markdown(f"**API Key**　{'✅ 已配置' if has_key else '❌ 未配置'}")
        st.markdown(
            f"**Base URL**　`{os.getenv('LLM_BASE_URL') or 'OpenAI 官方'}`"
        )
        st.markdown(f"**Model**　`{os.getenv('LLM_MODEL', 'gpt-4o-mini')}`")
        st.caption(f".env：`{ENV_PATH or '未找到'}`")

    st.markdown("")

    # ---- 下载按钮（方案出来后才显示） ----
    if solution_md:
        st.markdown("### 📥 导出方案")
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")

        st.download_button(
            label="下载 Markdown",
            data=solution_md.encode("utf-8"),
            file_name=f"AI视觉方案_{ts}.md",
            mime="text/markdown",
            use_container_width=True,
        )

        try:
            docx_bytes = markdown_to_docx(
                solution_md, title="AI 视觉解决方案与报价"
            )
            st.download_button(
                label="下载 Word（.docx）",
                data=docx_bytes,
                file_name=f"AI视觉方案_{ts}.docx",
                mime=(
                    "application/vnd.openxmlformats-officedocument."
                    "wordprocessingml.document"
                ),
                use_container_width=True,
                type="primary",
            )
        except Exception as exc:  # noqa: BLE001
            st.error(f"Word 生成失败：{exc}")

        st.markdown("")

    # ---- 重置 ----
    if st.button("🔄 重置会话", use_container_width=True):
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        st.rerun()


# ---------------------------------------------------------------------------
# 主聊天区
# ---------------------------------------------------------------------------

for role, content in st.session_state.history:
    with st.chat_message(role):
        st.markdown(content)


def _invoke_agent(user_text: str) -> None:
    """调用图，把所有新增的 AI 消息追加到历史。"""
    cfg = {"configurable": {"thread_id": st.session_state.thread_id}}
    inputs = {"messages": [HumanMessage(content=user_text)]}

    last_seen_count = 0
    snapshot_before = compiled_graph.get_state(cfg)
    if snapshot_before and snapshot_before.values:
        last_seen_count = len(snapshot_before.values.get("messages", []))

    with st.spinner("AI 正在思考..."):
        for _ in compiled_graph.stream(inputs, config=cfg, stream_mode="values"):
            pass

    snapshot_after = compiled_graph.get_state(cfg)
    new_messages = snapshot_after.values.get("messages", [])[last_seen_count:]
    for msg in new_messages:
        if isinstance(msg, AIMessage):
            st.session_state.history.append(("assistant", msg.content))


user_input = st.chat_input("请输入您的回复…")
if user_input:
    st.session_state.history.append(("user", user_input))
    with st.chat_message("user"):
        st.markdown(user_input)

    _invoke_agent(user_input)
    st.rerun()

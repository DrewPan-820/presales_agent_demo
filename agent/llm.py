"""统一的 LLM 客户端封装。兼容 OpenAI SDK 接口（OpenAI / DeepSeek / 其他兼容服务）。"""
from __future__ import annotations

import json
import os
from functools import lru_cache
from typing import Any

from openai import OpenAI


@lru_cache(maxsize=1)
def get_client() -> OpenAI:
    api_key = os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY")
    base_url = os.getenv("LLM_BASE_URL") or os.getenv("OPENAI_BASE_URL")
    if not api_key:
        raise RuntimeError(
            "未配置 LLM_API_KEY（或 OPENAI_API_KEY）。请在 .env 中设置后重启。"
        )
    return OpenAI(api_key=api_key, base_url=base_url)


def get_model_name() -> str:
    return os.getenv("LLM_MODEL", "gpt-4o-mini")


def chat(
    messages: list[dict[str, str]],
    *,
    temperature: float = 0.4,
    response_format: dict[str, Any] | None = None,
) -> str:
    """同步调用 LLM 并返回纯文本结果。"""
    client = get_client()
    kwargs: dict[str, Any] = {
        "model": get_model_name(),
        "messages": messages,
        "temperature": temperature,
    }
    if response_format is not None:
        kwargs["response_format"] = response_format
    resp = client.chat.completions.create(**kwargs)
    return (resp.choices[0].message.content or "").strip()


def chat_json(
    messages: list[dict[str, str]],
    *,
    temperature: float = 0.0,
) -> dict[str, Any]:
    """要求模型以 JSON 形式返回。"""
    raw = chat(
        messages,
        temperature=temperature,
        response_format={"type": "json_object"},
    )
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # 极少数模型不遵守 response_format，做一次容错截取
        start = raw.find("{")
        end = raw.rfind("}")
        if start != -1 and end != -1 and end > start:
            return json.loads(raw[start : end + 1])
        raise

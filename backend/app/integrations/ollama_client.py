"""本地 Ollama 模型异步 HTTP 客户端（原生 /api/generate 接口）。

用于电商路由分类等需要 raw prompt 格式的场景。
通用 chat 场景请走 llm_client.py（OpenAI 兼容 /v1/chat/completions）。
"""

from __future__ import annotations

import json
import logging

import httpx

logger = logging.getLogger(__name__)


async def ollama_generate(
    prompt: str,
    *,
    model: str,
    base_url: str = "http://localhost:11434",
    temperature: float = 0.1,
    max_tokens: int = 150,
    timeout: float = 10.0,
) -> str:
    """调用 Ollama /api/generate 返回纯文本响应。"""
    url = f"{base_url.rstrip('/')}/api/generate"
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": temperature,
            "num_predict": max_tokens,
        },
    }

    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(url, json=payload)
        resp.raise_for_status()
        data = resp.json()
        return (data.get("response") or "").strip()

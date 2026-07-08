"""翻譯模組：截圖 → Gemini vision 一步完成讀字 + 過濾 group 頻道 + 繁中翻譯。

API key 由 pydantic-ai 的 Google provider 自動從 GOOGLE_API_KEY 環境變數讀取。
"""

from pydantic import BaseModel
from pydantic_ai import Agent, BinaryContent

import config


class ChatLine(BaseModel):
    original: str  # 英文原文（逐字）
    translation: str  # 繁體中文譯文


# Agent 惰性建構：建構時就會讀 API key，延後到第一次翻譯才發生，
# 沒設 key 時錯誤會顯示在 UI 狀態列而不是啟動時直接 crash。
_agent: Agent | None = None

# 已見過的訊息原文（去重用）
_seen: set[str] = set()


def _get_agent() -> Agent:
    global _agent
    if _agent is None:
        _agent = Agent(
            config.MODEL,
            instructions=config.PROMPT,
            output_type=list[ChatLine],
        )
    return _agent


def translate_new_lines(png_bytes: bytes) -> list[ChatLine]:
    """辨識並翻譯截圖中的 group 訊息，只回傳這次新出現的行。

    從 worker thread 呼叫（不在 asyncio event loop 內），故可直接用 run_sync。
    """
    result = _get_agent().run_sync(
        [BinaryContent(data=png_bytes, media_type="image/png")]
    )
    new_lines: list[ChatLine] = []
    for line in result.output:
        key = line.original.strip()
        if not key or key in _seen:
            continue
        _seen.add(key)
        new_lines.append(line)
    return new_lines

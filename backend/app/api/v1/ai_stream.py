"""AI 流式回复 API。"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.dependencies import get_current_user
from app.models.employee import Employee
from app.services.ai.intent.pipeline import IntentRecognitionPipeline
from app.services.ai.message_router import MessageRouter


router = APIRouter(prefix="/ai", tags=["AI"])


class AIStreamRequest(BaseModel):
    """流式调试请求。"""

    text: str = Field(min_length=1)


@router.post("/stream")
async def stream_ai_reply(
    body: AIStreamRequest,
    _current_user: Employee = Depends(get_current_user),
) -> StreamingResponse:
    """识别一段文本并以 SSE 格式流式返回 AI 回复。"""

    async def event_source() -> AsyncIterator[str]:
        routed = await IntentRecognitionPipeline().recognize_and_route(body.text)
        yield _sse(
            "route",
            {
                "route": routed.route,
                "skill": routed.skill,
                "primaryIntent": routed.primary_intent,
                "confidence": routed.confidence,
                "needClarification": routed.need_clarification,
            },
        )
        async for chunk in MessageRouter().dispatch_stream(routed):
            if chunk:
                yield _sse("chunk", {"content": chunk})
        yield _sse("done", {})

    return StreamingResponse(event_source(), media_type="text/event-stream")


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

"""第三方渠道 Webhook 入口。"""

import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal, get_db
from app.integrations import wecom
from app.services import platform_service, webhook_processor

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/webhooks", tags=["Webhook"])


@router.get("/wecom/{guid}", response_class=PlainTextResponse)
async def verify_wecom_webhook(
    guid: int,
    msg_signature: str = Query(default=""),
    timestamp: str = Query(default=""),
    nonce: str = Query(default=""),
    echostr: str = Query(default=""),
    db: AsyncSession = Depends(get_db),
):
    """企业微信回调 URL 验证。

    企业微信后台保存 URL 时会 GET 这个地址；真实加密模式要校验签名并解密 echostr。
    演示阶段允许明文 echostr，方便本地/内网穿透调试。
    """
    platform = await platform_service.get_active_wecom_by_guid(db, guid)
    if platform is None:
        raise HTTPException(status_code=404, detail="企业微信渠道不存在或未启用")

    config = platform.config or {}
    if not wecom.verify_signature(
        config.get("token", ""), timestamp, nonce, msg_signature, echostr
    ):
        raise HTTPException(status_code=403, detail="签名校验失败")
    return wecom.decode_echo(echostr, config.get("encoding_aes_key"))


async def _process_wecom_background(platform_id: int, payload: dict) -> None:
    async with AsyncSessionLocal() as db:
        try:
            platform = await platform_service.get_active_wecom_by_guid(db, platform_id)
            if platform is None:
                logger.warning("后台任务未找到渠道配置：platform_id=%s", platform_id)
                return
            body_str = payload.get("raw", "")
            body_bytes = body_str.encode("utf-8") if body_str else b""
            config = platform.config or {}
            message = wecom.parse_encrypted_xml(body_bytes, config)
            await webhook_processor.process_wecom_message(db, platform, message)
        except Exception:
            logger.exception("处理企业微信消息失败：platform_id=%s", platform_id)


@router.post("/wecom/{guid}")
async def receive_wecom_webhook(
    guid: int,
    request: Request,
    background_tasks: BackgroundTasks,
    msg_signature: str = Query(default=""),
    timestamp: str = Query(default=""),
    nonce: str = Query(default=""),
    db: AsyncSession = Depends(get_db),
):
    """企业微信入站消息回调。

    接收企业微信 XML/AES 加密回调，先快速返回 ok，后台异步处理。
    """
    platform = await platform_service.get_active_wecom_by_guid(db, guid)
    if platform is None:
        logger.warning("企业微信 POST 回调未找到渠道：guid=%s", guid)
        raise HTTPException(status_code=404, detail="企业微信渠道不存在或未启用")

    config = platform.config or {}
    body_bytes = await request.body()
    body_str = body_bytes.decode("utf-8", errors="ignore") if body_bytes else ""
    logger.info("收到企业微信 POST 回调：guid=%s body_len=%s ct=%s", guid, len(body_bytes), request.headers.get("content-type", ""))

    # 签名需要的是 <Encrypt> 标签内容，不是整个 XML body
    sign_content = wecom.extract_encrypt_for_signature(body_str)
    token = config.get("token", "")
    if not wecom.verify_signature(token, timestamp, nonce, msg_signature, sign_content):
        computed = wecom.compute_signature(token, timestamp, nonce, sign_content)
        logger.warning(
            "企业微信 POST 签名校验失败：guid=%s expected=%s computed=%s token_len=%s content_preview=%s",
            guid, msg_signature, computed, len(token), sign_content[:80],
        )
        raise HTTPException(status_code=403, detail="签名校验失败")

    logger.info("企业微信 POST 签名校验通过，加入后台任务：guid=%s", guid)
    payload = {"raw": body_str}
    background_tasks.add_task(_process_wecom_background, guid, payload)
    return {"ok": True, "mode": "accepted"}

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
    """后台异步处理企业微信消息。

    ── 处理步骤 ──
      1. 用独立 DB 会话重新查询渠道配置
      2. 解密 XML body（AES-256-CBC），解析为标准 WeComInboundMessage
      3. 交给 webhook_processor 完成「联系人→会话→消息→AI 处理」全链路
    """
    async with AsyncSessionLocal() as db:
        try:
            # ── 1: 重新查渠道配置（独立 DB 会话）──
            platform = await platform_service.get_active_wecom_by_guid(db, platform_id)
            if platform is None:
                logger.warning("后台任务未找到渠道配置：platform_id=%s", platform_id)
                return
            # ── 2: XML 解密 + 解析 ──
            body_str = payload.get("raw", "")
            body_bytes = body_str.encode("utf-8") if body_str else b""
            config = platform.config or {}
            message = wecom.parse_encrypted_xml(body_bytes, config)
            # ── 3: 全链路异步处理 ──
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

    ── 处理步骤 ──
      1. 根据 guid 查找渠道配置（企微的 CorpId/Token/AESKey 等）
      2. 读取原始 XML body，提取 <Encrypt> 标签内容用于签名校验
      3. 签名校验：失败 → 403 拒绝；通过 → 继续
      4. 将原始 XML 打包为 payload，投递给 BackgroundTasks 异步处理
      5. 立即返回 {"ok":true}（满足企微 5 秒超时限制）
    """
    # ── 1: 查找渠道配置 ──
    platform = await platform_service.get_active_wecom_by_guid(db, guid)
    if platform is None:
        logger.warning("企业微信 POST 回调未找到渠道：guid=%s", guid)
        raise HTTPException(status_code=404, detail="企业微信渠道不存在或未启用")

    # ── 2: 读取原始 XML body ──
    config = platform.config or {}
    body_bytes = await request.body()
    body_str = body_bytes.decode("utf-8", errors="ignore") if body_bytes else ""

    # ── 3: 签名校验 ──
    sign_content = wecom.extract_encrypt_for_signature(body_str)
    token = config.get("token", "")
    if not wecom.verify_signature(token, timestamp, nonce, msg_signature, sign_content):
        computed = wecom.compute_signature(token, timestamp, nonce, sign_content)
        logger.warning(
            "企业微信 POST 签名校验失败：guid=%s expected=%s computed=%s content_preview=%s",
            guid, msg_signature, computed, sign_content[:80],)
        raise HTTPException(status_code=403, detail="签名校验失败")

    # ── 4: 投递后台任务（异步解密 + 路由 + AI 处理）──
    payload = {"raw": body_str}
    background_tasks.add_task(_process_wecom_background, guid, payload)

    # ── 5: 快速返回 200 ──
    return {"ok": True, "mode": "accepted"}

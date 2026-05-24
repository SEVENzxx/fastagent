"""企业微信出站消息客户端。"""

from __future__ import annotations

import time
from typing import Any

import httpx


class WeComOutboundError(RuntimeError):
    """当企业微信拒绝出站请求或配置不完整时抛出。"""


_TOKEN_CACHE: dict[tuple[str, str, str], tuple[str, float]] = {}


class WeComOutboundClient:
    def __init__(self, config: dict) -> None:
        self.config = config
        self.base_url = str(config.get("api_base_url") or "https://qyapi.weixin.qq.com").rstrip("/")

    async def send_text(self, external_userid: str, content: str) -> dict:
        """向打开聊天窗口的企业微信用户发送文本应用消息。

        入站回调中会将企业微信的 ``FromUserName`` 保存为 ``wecom_external_userid``。
        对于自建应用单聊场景，该值即为 ``/cgi-bin/message/send`` 所需的接收人。
        """
        to_user = str(external_userid or "").strip()
        if not to_user:
            raise WeComOutboundError("缺少企业微信 external_userid")

        agentid = str(self.config.get("agentid") or "").strip()
        if not agentid:
            raise WeComOutboundError("缺少企业微信 agentid")

        access_token = await self._get_access_token()
        payload: dict[str, Any] = {
            "touser": to_user,
            "msgtype": "text",
            "agentid": int(agentid) if agentid.isdigit() else agentid,
            "text": {"content": content},
            "safe": 0,
            "enable_duplicate_check": 0,
        }
        data = await self._post_json("/cgi-bin/message/send", {"access_token": access_token}, payload)
        if int(data.get("errcode", -1)) != 0:
            raise WeComOutboundError(self._format_error("发送消息失败", data))
        return {
            "ok": True,
            "api": "message.send",
            "to_user": to_user,
            "response": data,
        }

    async def _get_access_token(self) -> str:
        """获取并缓存企业微信 access_token。"""
        corpid = str(self.config.get("corpid") or "").strip()
        corpsecret = str(self.config.get("corpsecret") or "").strip()
        if not corpid:
            raise WeComOutboundError("缺少企业微信 corpid")
        if not corpsecret:
            raise WeComOutboundError("缺少企业微信 corpsecret")

        cache_key = (self.base_url, corpid, corpsecret)
        now = time.time()
        cached = _TOKEN_CACHE.get(cache_key)
        if cached and cached[1] > now:
            return cached[0]

        data = await self._get_json(
            "/cgi-bin/gettoken",
            {"corpid": corpid, "corpsecret": corpsecret},
        )
        if int(data.get("errcode", -1)) != 0 or not data.get("access_token"):
            raise WeComOutboundError(self._format_error("获取 token 失败", data))

        expires_in = int(data.get("expires_in") or 7200)
        # 提前 5 分钟过期，避免边界情况下的 token 失效
        _TOKEN_CACHE[cache_key] = (str(data["access_token"]), now + max(expires_in - 300, 60))
        return str(data["access_token"])

    async def _get_json(self, path: str, params: dict[str, str]) -> dict:
        url = f"{self.base_url}{path}"
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.get(url, params=params)
                response.raise_for_status()
                return response.json()
        except httpx.HTTPError as exc:
            raise WeComOutboundError(f"wecom http error: {exc}") from exc

    async def _post_json(self, path: str, params: dict[str, str], payload: dict) -> dict:
        url = f"{self.base_url}{path}"
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.post(url, params=params, json=payload)
                response.raise_for_status()
                return response.json()
        except httpx.HTTPError as exc:
            raise WeComOutboundError(f"wecom http error: {exc}") from exc

    @staticmethod
    def _format_error(prefix: str, data: dict) -> str:
        errcode = data.get("errcode")
        errmsg = data.get("errmsg") or "unknown error"
        return f"{prefix}: errcode={errcode}, errmsg={errmsg}"

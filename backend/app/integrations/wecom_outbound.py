"""企业微信出站消息 API 占位。

真实上线时这里负责：
1. 使用 corpid + corpsecret 获取 access_token，并缓存 token。
2. 调用企业微信发送应用消息、微信客服消息或客户群消息 API。
3. 把发送结果回写消息 metadata，便于排查失败原因。
"""


class WeComOutboundClient:
    def __init__(self, config: dict) -> None:
        self.config = config

    async def send_text(self, external_userid: str, content: str) -> dict:
        """发送文本消息占位。

        暂不真正调用企业微信，避免没有企业微信账号时无法演示。
        """
        return {
            "ok": False,
            "stub": True,
            "external_userid": external_userid,
            "content": content,
            "message": "企业微信出站 API 将在真实账号配置后接入",
        }

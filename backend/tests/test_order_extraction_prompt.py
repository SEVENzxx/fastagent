"""Order extraction prompt 导入与构建测试。"""

from app.ai.prompts.order_extraction import build_order_extraction_messages


class TestOrderExtractionPrompt:
    """确保 prompt 可导入且函数返回合法结构。"""

    def test_build_messages(self) -> None:
        messages = build_order_extraction_messages("查一下我今天的订单")
        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"
        assert "查一下我今天的订单" in messages[1]["content"]

    def test_empty_content(self) -> None:
        messages = build_order_extraction_messages("")
        assert len(messages) == 2
        assert messages[0]["role"] == "system"

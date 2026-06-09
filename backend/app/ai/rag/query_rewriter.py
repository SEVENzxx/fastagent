"""RAG 检索前的轻量查询归一化与改写。

这里不承担意图识别，只做召回友好的文本清理：去掉寒暄/泛化动词，
保留型号、品类、参数词，降低“向量库有内容但 query 噪声太大”的漏召回概率。

注意：这是 SaaS 平台级代码，不能内置任何商家品牌、商品名、型号或错拼纠正。
商品别名和纠错只能来自租户上传的商品资料、SKU、别名或向量召回结果。
"""

from __future__ import annotations

import re

NOISE_PHRASES = (
    "我想咨询一下",
    "咨询一下",
    "我想了解一下",
    "了解一下",
    "给我介绍一下",
    "介绍一下",
    "详细介绍一下",
    "帮我看看",
    "看一下",
    "这款",
    "这个",
)

def normalize_query(query: str) -> str:
    """保留可读空格的归一化 query，适合传给 embedding。"""

    text = str(query or "").strip()
    for phrase in NOISE_PHRASES:
        text = text.replace(phrase, " ")
    # 通用格式归一化：拆开英文/数字边界，不包含任何商家专属词。
    text = re.sub(r"([A-Za-z])(\d)", r"\1 \2", text)
    text = re.sub(r"(\d)([A-Za-z])", r"\1 \2", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def rewrite_product_consult_query(query: str, product_name: str | None = None) -> str:
    """产品咨询召回改写。

    SaaS 平台层不能写入具体行业属性，例如某类商品的功能词。
    这里只追加跨行业通用的资料字段，具体品牌、型号、属性和别名必须来自租户数据。
    """

    normalized = normalize_query(query)
    hints = "商品资料 商品详情 规格参数 使用说明 常见问题 服务政策 价格 库存"
    parts = [part for part in (product_name, normalized, hints) if part]
    return " ".join(parts)

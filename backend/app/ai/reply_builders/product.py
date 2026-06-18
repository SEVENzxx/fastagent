"""ProductReplyBuilder — 产品回复模板集中管理。

不把回复文案散落在 Handler 或 Skill 中。
"""
from __future__ import annotations

from typing import Any


class ProductReplyBuilder:
    """产品回复模板。"""

    @staticmethod
    def product_list(
        products: list[dict[str, Any]],
        *,
        category: str | None = None,
        header_suffix: str | None = None,
        show_pagination: bool = False,
    ) -> str:
        """商品列表回复。

        Args:
            products: 商品列表
            category: 分类名称（可选），如 "耳机"
            header_suffix: 标题后缀（可选），如 "¥500元以下"
            show_pagination: 是否显示翻页提示
        """
        if not products:
            return "暂时没有找到相关商品，请尝试其他关键词或分类。"

        lines: list[str] = []
        if category:
            prefix = f"以下是为您找到的 {category} 商品"
        else:
            prefix = "以下是为您找到的商品"
        if header_suffix:
            prefix += f"（{header_suffix}）"
        lines.append(f"{prefix}：")

        for i, p in enumerate(products, 1):
            name = p.get("name", "未知商品")
            price = p.get("price")
            price_str = f" - ¥{float(price):.2f}" if price is not None else ""
            sku_str = f" [{p.get('sku', '')}]" if p.get("sku") else ""
            lines.append(f"{i}. {name}{sku_str}{price_str}")

        lines.append("")
        lines.append("请回复序号查看详情，或告诉我更具体的需求。")
        if show_pagination:
            lines.append("（输入「下一页」「上一页」可翻页）")
        return "\n".join(lines)

    @staticmethod
    def product_detail(
        product: dict[str, Any] | None,
        *,
        knowledge: list[dict[str, Any]] | None = None,
    ) -> str:
        """商品详情回复。"""
        if product is None:
            return "暂时没有找到该商品的详细信息。"

        name = product.get("name", "未知商品")
        price = product.get("price")
        stock = product.get("stock")
        sku = product.get("sku", "")
        description = product.get("description", "")

        lines: list[str] = [name]
        lines.append("=" * 20)
        if price is not None:
            lines.append(f"价格：¥{float(price):.2f}")
        if stock is not None:
            lines.append(f"库存：{stock} 件")
        if sku:
            lines.append(f"SKU：{sku}")
        if description:
            lines.append(f"描述：{description}")

        tags = product.get("feature_tags") or []
        if tags:
            lines.append(f"标签：{'、'.join(tags[:5])}")

        if knowledge:
            lines.append("")
            lines.append("相关知识：")
            for k in knowledge[:3]:
                title = k.get("title", "")
                content = k.get("content", "")
                if title:
                    lines.append(f"  - {title}：{content[:80]}")
                elif content:
                    lines.append(f"  - {content[:80]}")

        lines.append("")
        lines.append("您还想了解这款产品的哪些信息？")
        return "\n".join(lines)

    @staticmethod
    def compare_result(
        products: list[dict[str, Any]],
        *,
        comparison_text: str | None = None,
    ) -> str:
        """商品对比回复。"""
        if len(products) < 2:
            return "需要至少两款商品才能进行对比。"

        p0 = products[0]
        p1 = products[1]
        lines: list[str] = [
            "【商品对比】",
            "",
            f"{p0.get('name', '?')}  vs  {p1.get('name', '?')}",
            "━" * 36,
        ]

        # 价格
        p0_price = p0.get("price")
        p1_price = p1.get("price")
        if p0_price is not None or p1_price is not None:
            p0_str = f"¥{float(p0_price):.2f}" if p0_price is not None else "-"
            p1_str = f"¥{float(p1_price):.2f}" if p1_price is not None else "-"
            lines.append(f"💰 价格  {p0_str}  |  {p1_str}")

        # 库存
        s0 = p0.get("stock")
        s1 = p1.get("stock")
        if s0 is not None or s1 is not None:
            lines.append(f"📦 库存  {s0 or '-'}件  |  {s1 or '-'}件")

        # 描述
        d0 = (p0.get("description") or "").strip()
        d1 = (p1.get("description") or "").strip()
        if d0 or d1:
            lines.append(f"📝 描述  {d0[:50]}  |  {d1[:50]}")

        # 标签
        t0 = p0.get("feature_tags") or []
        t1 = p1.get("feature_tags") or []
        if t0 or t1:
            lines.append(f"🏷️  标签  {'、'.join(t0[:3]) or '-'}  |  {'、'.join(t1[:3]) or '-'}")

        if comparison_text:
            lines.append("")
            lines.append(f"📋 {comparison_text}")

        lines.append("")
        lines.append("如需了解更多差异，请继续提问。")
        return "\n".join(lines)

    @staticmethod
    def clarify_candidates(candidates: list[dict[str, Any]]) -> str:
        """多候选追问。"""
        if not candidates:
            return "请提供更完整的商品名称或型号。"

        lines: list[str] = ["找到多款相近商品："]
        for c in candidates:
            idx = c.get("index", 0)
            name = c.get("name") or c.get("product_name", "未知商品")
            lines.append(f"{idx}. {name}")

        lines.append("")
        lines.append("请回复序号（如 1、2），或提供更完整的型号。")
        return "\n".join(lines)

    @staticmethod
    def no_results(query_context: str = "") -> str:
        """无结果回复。"""
        if query_context:
            return f"暂时没有找到与「{query_context}」相关的商品，请尝试其他关键词或分类。"
        return "暂时没有找到相关商品，请尝试其他关键词或分类。"

    @staticmethod
    def category_list(categories: list[dict[str, Any]]) -> str:
        """商品分类树回复。"""
        if not categories:
            return "当前没有可用的商品分类。"

        lines: list[str] = ["商品分类如下："]
        for i, cat in enumerate(categories, 1):
            name = cat.get("name", "未知分类")
            children = cat.get("children", [])
            if children:
                child_names = "、".join(
                    c.get("name", "") for c in children[:5]
                )
                lines.append(f"{i}. {name}（{child_names}…）")
            else:
                lines.append(f"{i}. {name}")

        lines.append("")
        lines.append("请回复序号查看该分类下的商品。")
        return "\n".join(lines)

    @staticmethod
    def product_attributes(
        product: dict[str, Any],
        attributes: dict[str, Any] | None = None,
    ) -> str:
        """商品属性回复。"""
        name = product.get("name", "未知商品")
        tags = product.get("feature_tags") or []
        attrs = attributes or {}

        lines: list[str] = [f"{name} 的属性信息如下："]
        lines.append("=" * 24)

        if attrs:
            for key, value in attrs.items():
                if value is not None and str(value).strip():
                    lines.append(f"  {key}：{value}")
        else:
            lines.append("  暂无结构化属性数据。")

        if tags:
            lines.append(f"  标签：{'、'.join(tags[:5])}")

        lines.append("")
        lines.append("您还想了解哪些属性？")
        return "\n".join(lines)

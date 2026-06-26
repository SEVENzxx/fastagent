"""ScenarioExtractor 包 — 按场景用 LLM 抽取结构化参数。"""
from app.ai.components.extractors.base import ExtractionResult, ScenarioExtractor
from app.ai.components.extractors.product_detail import ProductDetailExtractor
from app.ai.components.extractors.product_filter import ProductFilterExtractor

__all__ = [
    "ExtractionResult",
    "ScenarioExtractor",
    "ProductDetailExtractor",
    "ProductFilterExtractor",
]

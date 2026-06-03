"""文档解析器 — PDF/DOCX/MD/TXT/HTML → 纯文本"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class DocumentParseError(RuntimeError):
    """文档解析失败"""


class DocumentParser:
    """将常见文档格式解析为纯文本。

    支持格式：pdf / docx / md / txt / html
    """

    async def parse(self, file_path: str, file_type: str) -> str:
        """解析文件，返回纯文本。"""
        path = Path(file_path)
        if not path.exists():
            raise DocumentParseError(f"文件不存在: {file_path}")

        file_type = file_type.lower().lstrip(".")

        parser_method = {
            "pdf": self._parse_pdf,
            "docx": self._parse_docx,
            "md": self._parse_text,
            "txt": self._parse_text,
            "html": self._parse_html,
        }.get(file_type)

        if parser_method is None:
            raise DocumentParseError(f"不支持的文件类型: {file_type}")

        try:
            content = await parser_method(path)
            if not content or not content.strip():
                raise DocumentParseError("解析结果为空")
            return content.strip()
        except DocumentParseError:
            raise
        except Exception as exc:
            logger.warning("文档解析异常: %s type=%s", exc, file_type)
            raise DocumentParseError(f"解析失败: {exc}") from exc

    async def _parse_pdf(self, path: Path) -> str:
        """PDF → 纯文本（pdfplumber）"""
        import pdfplumber

        pages: list[str] = []
        with pdfplumber.open(str(path)) as pdf:
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    pages.append(text)
        return "\n\n".join(pages)

    async def _parse_docx(self, path: Path) -> str:
        """DOCX → 纯文本（python-docx）"""
        from docx import Document

        doc = Document(str(path))
        paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
        return "\n".join(paragraphs)

    async def _parse_text(self, path: Path) -> str:
        """纯文本/Markdown → 读取全文"""
        return path.read_text(encoding="utf-8")

    async def _parse_html(self, path: Path) -> str:
        """HTML → 纯文本（BeautifulSoup）"""
        from bs4 import BeautifulSoup

        html = path.read_text(encoding="utf-8")
        soup = BeautifulSoup(html, "html.parser")
        # 移除脚本、样式和常见页面框架元素。
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()
        return soup.get_text(separator="\n")

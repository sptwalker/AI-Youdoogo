"""文本抽取单测：txt/md/docx/pdf 真实字节 → 纯文本；不支持类型报错。"""

from io import BytesIO

import pytest
from docx import Document
from reportlab.pdfgen import canvas

from app.core.exceptions import AppError
from app.knowledge.extract import extract_text


def test_txt_utf8() -> None:
    assert extract_text("你好 hello".encode(), "text/plain", "a.txt") == "你好 hello"


def test_md_by_extension() -> None:
    assert "标题" in extract_text("# 标题\n正文".encode(), None, "note.md")


def _docx_bytes(paras: list[str]) -> bytes:
    doc = Document()
    for p in paras:
        doc.add_paragraph(p)
    buf = BytesIO()
    doc.save(buf)
    return buf.getvalue()


def test_docx_paragraphs() -> None:
    content = _docx_bytes(["第一段运营策略", "", "第二段风险评估"])
    text = extract_text(content, None, "plan.docx")
    assert "第一段运营策略" in text and "第二段风险评估" in text


def _pdf_bytes(lines: list[str]) -> bytes:
    buf = BytesIO()
    c = canvas.Canvas(buf)
    y = 800
    for line in lines:
        c.drawString(72, y, line)
        y -= 20
    c.save()
    return buf.getvalue()


def test_pdf_pages() -> None:
    content = _pdf_bytes(["Quarterly report", "DAU growth 12 percent"])
    text = extract_text(content, "application/pdf", "report.pdf")
    assert "Quarterly report" in text and "DAU growth" in text


def test_unsupported_type_rejected() -> None:
    with pytest.raises(AppError, match="暂不支持"):
        extract_text(b"\x00\x01", "image/png", "pic.png")


def test_corrupt_docx_reported() -> None:
    with pytest.raises(AppError, match="解析失败"):
        extract_text(b"not a real docx", None, "bad.docx")


def test_non_utf8_text_rejected() -> None:
    with pytest.raises(AppError, match="UTF-8"):
        extract_text("你好".encode("gbk"), "text/plain", "gbk.txt")

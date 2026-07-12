"""文本抽取：把上传文件字节解出纯文本（MVP 仅 txt/md）。

docs 决策：MVP 输入=txt/md/粘贴/飞书文档，零解析依赖；docx/pdf 后续增量。
"""

from __future__ import annotations

from app.core.exceptions import AppError

_TEXT_MIMES = {"text/plain", "text/markdown", "text/x-markdown", ""}
_TEXT_EXTS = (".txt", ".md", ".markdown")


def extract_text(content: bytes, mime_type: str | None, file_name: str) -> str:
    """把文件字节解成纯文本。仅支持文本类；其余抛 AppError。"""
    name = file_name.lower()
    mime = (mime_type or "").split(";")[0].strip().lower()
    if mime not in _TEXT_MIMES and not name.endswith(_TEXT_EXTS):
        raise AppError(f"MVP 仅支持 txt/md/粘贴/飞书文档，暂不支持：{mime_type or file_name}")
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise AppError("文件不是 UTF-8 文本，无法解析") from exc

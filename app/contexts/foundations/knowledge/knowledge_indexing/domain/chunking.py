"""Pure paragraph-aware chunking policy owned by Knowledge Indexing.

策略：先按空行切段落 → 贪心打包到 max_chars 一块；单段超长则按字符窗口 + overlap 再切。
overlap 让跨块语义不被硬切断，检索命中率更稳。
"""

from __future__ import annotations

import re

_BLANK_LINES = re.compile(r"\n\s*\n")
_WS = re.compile(r"[ \t　]+")


def _norm(text: str) -> str:
    """行内空白折叠、去行尾空白、去首尾空行。不动段落结构（保留单换行）。"""
    lines = [_WS.sub(" ", ln).strip() for ln in text.replace("\r\n", "\n").split("\n")]
    return "\n".join(lines).strip()


def _split_long(para: str, max_chars: int, overlap: int) -> list[str]:
    """把超过 max_chars 的段落按字符窗口切分，相邻窗口重叠 overlap。"""
    step = max_chars - overlap
    return [para[i : i + max_chars] for i in range(0, len(para), step)]


def chunk_text(text: str, *, max_chars: int = 800, overlap: int = 100) -> list[str]:
    """把长文本切成适合 embedding 的块列表。

    Args:
        text: 原始纯文本。
        max_chars: 单块最大字符数。
        overlap: 超长段切分时相邻块的重叠字符数（须 < max_chars）。

    Returns:
        非空文本块列表；输入全空白时返回 []。
    """
    if overlap >= max_chars:
        raise ValueError("overlap 必须小于 max_chars")

    normalized = _norm(text)
    if not normalized:
        return []

    chunks: list[str] = []
    buf = ""
    for para in _BLANK_LINES.split(normalized):
        para = para.strip()
        if not para:
            continue
        if len(para) > max_chars:
            if buf:
                chunks.append(buf)
                buf = ""
            chunks.extend(_split_long(para, max_chars, overlap))
            continue
        candidate = f"{buf}\n\n{para}" if buf else para
        if len(candidate) <= max_chars:
            buf = candidate
        else:
            chunks.append(buf)
            buf = para
    if buf:
        chunks.append(buf)
    return chunks

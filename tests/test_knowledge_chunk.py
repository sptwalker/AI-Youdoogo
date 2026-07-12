"""文本分块单测（纯逻辑，无网络）。"""

from app.knowledge.chunk import chunk_text


def test_short_text_single_chunk() -> None:
    assert chunk_text("一段短文本。") == ["一段短文本。"]


def test_empty_returns_nothing() -> None:
    assert chunk_text("") == []
    assert chunk_text("   \n\n  \t ") == []


def test_paragraphs_packed_under_max() -> None:
    text = "A" * 300 + "\n\n" + "B" * 300
    chunks = chunk_text(text, max_chars=800, overlap=100)
    assert len(chunks) == 1  # 300+300+分隔 < 800，打包成一块
    assert "A" * 300 in chunks[0] and "B" * 300 in chunks[0]


def test_paragraphs_split_when_exceed_max() -> None:
    text = "A" * 500 + "\n\n" + "B" * 500
    chunks = chunk_text(text, max_chars=800, overlap=100)
    assert len(chunks) == 2  # 合起来 >800，各成一块
    assert set(chunks[0]) == {"A"} and set(chunks[1]) == {"B"}


def test_long_paragraph_windowed_with_overlap() -> None:
    text = "".join(chr(ord("a") + i % 26) for i in range(2000))
    chunks = chunk_text(text, max_chars=800, overlap=100)
    assert all(len(c) <= 800 for c in chunks)
    # 相邻窗口尾/首重叠 overlap 个字符
    assert chunks[0][-100:] == chunks[1][:100]
    # step=700，2000 字符 → 3 块 (0-800, 700-1500, 1400-2000)
    assert len(chunks) == 3


def test_whitespace_normalized() -> None:
    chunks = chunk_text("行内   多  空格\t制表")
    assert chunks == ["行内 多 空格 制表"]

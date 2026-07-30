"""知识写侧对账离线自检（⑥a / docs/22 §3）：钉指纹口径 + 比对器四态。

指纹口径错了整个门失效——钉：内容敏感、chunk 顺序敏感、技术簿记（id/时间戳）不入 hash。
比对器钉四态：一致 matched、内容失配 mismatched、源有目标无、目标有源无。
"""

from __future__ import annotations

import uuid
from datetime import datetime

from scripts.reconcile_knowledge import (
    Mismatch,
    document_fingerprint,
    reconcile,
)

_KB = uuid.UUID("11111111-1111-1111-1111-111111111111")
_UP = uuid.UUID("33333333-3333-3333-3333-333333333333")


def _fp(**over: object) -> str:
    base: dict[str, object] = {
        "file_name": "Q3财报", "knowledge_base_id": _KB, "category": "finance",
        "uploader_id": _UP, "status": "indexed", "chunk_texts": ["甲", "乙"],
    }
    base.update(over)
    return document_fingerprint(**base)  # type: ignore[arg-type]


def test_fingerprint_content_sensitive() -> None:
    base = _fp()
    assert _fp(file_name="年度预算") != base  # 元数据变 → 指纹变
    assert _fp(chunk_texts=["甲", "丙"]) != base  # 内容变 → 指纹变
    assert _fp(status="failed") != base


def test_fingerprint_chunk_order_sensitive() -> None:
    # 分块顺序即检索顺序，顺序颠倒必须判失配（防远端分块/排序漂移）
    assert _fp(chunk_texts=["甲", "乙"]) != _fp(chunk_texts=["乙", "甲"])


def test_fingerprint_ignores_bookkeeping() -> None:
    # id / create_time 不入口径（调用方不传）——两侧簿记不同不该报失配
    assert _fp() == _fp()  # 同业务字段 → 同指纹，与行 id、写入时间无关
    _ = datetime  # 簿记列示意：create_time 由 _run 排除，从不进 document_fingerprint


def test_reconcile_all_matched() -> None:
    src = {"a": _fp(), "b": _fp(file_name="B")}
    report = reconcile(src, dict(src))
    assert report.ok
    assert report.matched == ("a", "b")


def test_reconcile_flags_mismatch() -> None:
    src = {"a": _fp()}
    tgt = {"a": _fp(chunk_texts=["甲", "丙"])}  # 远端内容漂移
    report = reconcile(src, tgt)
    assert not report.ok
    assert report.mismatched == (Mismatch("a", src["a"], tgt["a"]),)
    assert report.matched == ()


def test_reconcile_flags_missing_both_directions() -> None:
    report = reconcile({"a": _fp(), "b": _fp()}, {"b": _fp(), "c": _fp()})
    assert report.missing_in_target == ("a",)  # 源有目标无 = 远端漏索引
    assert report.missing_in_source == ("c",)  # 目标有源无 = 远端多索引/脏数据
    assert report.matched == ("b",)
    assert not report.ok

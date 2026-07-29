"""reconcile.content_hash 确定性测试（D6 数据完整性锚点）。

指纹一旦不确定，整个对账口径失效——所以这里只钉三件事：键序无关、值敏感、复杂类型稳定折叠。
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from scripts.reconcile import content_hash


def test_key_order_independent() -> None:
    a = content_hash({"name": "盒子A5", "role": "daily", "n": 3})
    b = content_hash({"n": 3, "role": "daily", "name": "盒子A5"})
    assert a == b  # dict 插入序不改变指纹


def test_value_sensitive() -> None:
    base = content_hash({"name": "盒子A5", "role": "daily"})
    assert content_hash({"name": "盒子A6", "role": "daily"}) != base  # 值变 → 指纹变
    assert content_hash({"name": "盒子A5", "role": "reasoning"}) != base


def test_none_distinct_from_missing() -> None:
    # None → null 入 JSON；缺列则键消失，两者必须可区分（否则漏列被当成一致）
    assert content_hash({"a": 1, "b": None}) != content_hash({"a": 1})


def test_complex_types_fold_stably() -> None:
    # uuid/datetime 走 default=str，同值必得同指纹（跨进程稳定）
    uid = UUID("12345678-1234-5678-1234-567812345678")
    ts = datetime(2026, 7, 25, 10, 30, 0)
    h1 = content_hash({"id": uid, "at": ts})
    h2 = content_hash({"id": UUID(str(uid)), "at": datetime(2026, 7, 25, 10, 30, 0)})
    assert h1 == h2

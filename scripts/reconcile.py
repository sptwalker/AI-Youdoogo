"""数据迁移对账指纹（D6 / docs/22 §2）：把一行的业务字段折成确定性 content_hash。

迁移双跑期用它逐行比对源库↔目标服务：hash 相同 = 业务内容一致（技术簿记列如 id/时间戳/租约
不参与，由调用方在选列时排除）。确定性要求（数据完整性边界，不可偷懒）：
- 键序无关（sort_keys）——dict 插入序不该改变指纹；
- 跨进程/机器稳定——ensure_ascii=False + 紧凑分隔符 + uuid/datetime/Decimal 一律 str 折叠；
- None 与缺列可区分——None 进 JSON 为 null，缺列则整个键不出现，两者 hash 不同。

对账口径见 docs/22；本模块只负责「一行业务字段 → 稳定十六进制指纹」这一纯函数。
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping


def canonical_json(fields: Mapping[str, object]) -> str:
    """业务字段的确定性 JSON 串（排序键 + 紧凑 + 非 ASCII 原样 + 复杂类型 str 折叠）。"""
    return json.dumps(
        fields,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        default=str,  # uuid/datetime/Decimal → 其 str()，确定且跨环境稳定
    )


def content_hash(fields: Mapping[str, object]) -> str:
    """一行业务字段的 sha256 十六进制指纹。调用方先剔除技术簿记列再传入。"""
    return hashlib.sha256(canonical_json(fields).encode("utf-8")).hexdigest()

"""时钟与标识符的生产实现。

结构化类型（Protocol）匹配，因此这两个类不需要继承任何 Context 的协议：
只要方法签名一致，即可直接注入到声明了 Clock / IdentifierPort 的 Application。
`new_object_token` 供需要对象存储路径分片的 Context 使用（附件类场景）。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime


class SystemClock:
    """返回 UTC 感知时间。全库唯一的生产时钟实现。"""

    def now(self) -> datetime:
        return datetime.now(UTC)


class UUIDIdentifier:
    """随机标识符生成器。Context 特有的编码规则（如会商编号）仍留在本地适配器。"""

    def new_id(self) -> uuid.UUID:
        return uuid.uuid4()

    def new_object_token(self) -> str:
        return uuid.uuid4().hex

"""进程级时钟与标识符生成机制（无业务语义，供各 Context 的 composition 复用）。

各 Context 仍在自己的 ports.py 声明 Clock / IdentifierPort 协议以保持边界自治；
这里只提供生产环境的唯一实现，避免同一份 `datetime.now(UTC)` / `uuid.uuid4()`
在十余个 infrastructure 适配器里逐字重复。测试仍可注入各自的假实现。
"""

from app.platform.deterministic.generators import SystemClock, UUIDIdentifier

__all__ = ["SystemClock", "UUIDIdentifier"]

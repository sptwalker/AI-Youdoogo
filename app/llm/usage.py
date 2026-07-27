"""One-way compatibility shim for Usage & Budget governance.

正典已迁至 ``app.contexts.foundations.governance.usage_budget.public``；本模块仅为
``app/agents``、``app/services`` 等迁移期 legacy facade 保留旧导入路径。
``app/contexts`` 下新代码禁止再引本模块（见架构守卫），一律经 usage_budget.public。
"""

from __future__ import annotations

from app.contexts.foundations.governance.usage_budget.public import (
    budget_exceeded as budget_exceeded,
)
from app.contexts.foundations.governance.usage_budget.public import (
    extract_usage as extract_usage,
)
from app.contexts.foundations.governance.usage_budget.public import (
    record_usage as record_usage,
)

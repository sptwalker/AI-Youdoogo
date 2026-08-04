"""Agent protocol and typed capability adapter for Deliverable Management."""

from __future__ import annotations

import logging
import re
import uuid
from collections.abc import Callable
from typing import Any, Protocol

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

import app.platform.object_storage.gateway as object_storage
from app.agents.contracts import (
    AgentSubject,
    ExecutionContext,
    SkillRequest,
    SkillResult,
    agent_subject,
)
from app.agents.directive_dispatch import dispatch_requests, merge_execution_context
from app.contexts.foundations.execution.deliverable_management.contracts.delivery import (
    DeliverableFormat,
    PublishDeliverableCommand,
)
from app.contexts.foundations.execution.deliverable_management.entrypoints import operations
from app.contexts.foundations.execution.deliverable_management.infrastructure.adapters import (
    ObjectPut,
)

logger = logging.getLogger(__name__)

_MAX_DELIVERIES = 2
_DELIVER_RE = re.compile(
    r"【交付】\s*名称[：:]\s*([^；;\n]+?)\s*[；;]\s*格式[：:]\s*"
    r"(csv|xlsx|md|txt)\s*\n+```[^\n]*\n(.*?)\n?```",
    re.DOTALL,
)


class FeatureFlagResolver(Protocol):
    async def __call__(
        self,
        db: AsyncSession,
        key: str,
        default: Any = None,
    ) -> Any: ...


class DeliveryArgs(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    format: str = Field(pattern="^(csv|xlsx|md|txt)$")
    body: str = Field(min_length=1)


PROMPT_SECTION = (
    "\n\n【文件交付】（系统内建，已启用）当用户要你产出可下载的表格或文档时，"
    "在回复中单独写一段交付指令，系统会自动生成文件并放入用户工作桌面的「文件交付区」：\n"
    "格式：先写一行 【交付】名称：<文件名>；格式：<csv|xlsx|md|txt>，"
    "紧接一个 ``` 代码块作为内容。\n"
    "- 表格（csv/xlsx）：代码块里放标准 Markdown 表格（首行表头，第二行 --- 分隔）。\n"
    "- 文档（md/txt）：代码块里放正文。\n"
    "每次回复最多交付 2 个文件。示例：\n"
    "【交付】名称：销售周报；格式：xlsx\n```\n| 日期 | 产品 | 销量 |\n| --- | --- | --- |\n"
    "| 2026-07-14 | A | 120 |\n```\n"
    "需要别的同事的数据时，先用【咨询 @AI名】取数，拿到后再在同一或下一轮回复里交付。"
)


def parse(output: str) -> list[tuple[str, str, str]]:
    items = [
        (name.strip(), file_format.lower(), body)
        for name, file_format, body in _DELIVER_RE.findall(output or "")
        if name.strip() and body.strip()
    ]
    return items[:_MAX_DELIVERIES]


async def _enabled(
    db: AsyncSession,
    resolver: FeatureFlagResolver | None,
) -> bool:
    if resolver is None:
        return True
    flag = await resolver(db, "agent_deliver", True)
    return str(flag).lower() not in ("false", "0")


class DeliverySkillExecutor:
    key = "deliver"

    def __init__(self, *, publisher: ObjectPut | None = None) -> None:
        self._publisher = publisher

    def requires_idempotency(self, _request: SkillRequest) -> bool:
        return True

    async def execute(
        self,
        db: AsyncSession,
        role: AgentSubject | object,
        request: SkillRequest,
        context: ExecutionContext,
    ) -> SkillResult:
        subject = agent_subject(role)
        args = DeliveryArgs.model_validate(request.arguments)
        if context.user_id is None:
            return SkillResult(notes=["交付需指定接收人，自动任务无桌面归属，已跳过文件交付"])
        artifact = await operations.publish_deliverable(
            db,
            PublishDeliverableCommand(
                owner_user_id=context.user_id,
                agent_id=subject.expert_id,
                agent_name=subject.name,
                name=args.name,
                file_format=DeliverableFormat(args.format),
                body=args.body,
                idempotency_key=context.action_key("deliver", request.action_index),
            ),
            publisher=self._publisher or object_storage.put_object,
        )
        return SkillResult(
            notes=[f"已交付文件「{artifact.file_name}」，见工作桌面文件交付区"],
            artifacts=[artifact.to_reference()],
        )


ExecutorFactory = Callable[[], DeliverySkillExecutor]


def _delivery_failure_note(request: SkillRequest) -> str:
    name = str(request.arguments.get("name", ""))
    file_format = str(request.arguments.get("format", ""))
    logger.warning(
        "交付执行失败 name=%s fmt=%s",
        name,
        file_format,
        exc_info=True,
    )
    return f"交付「{name}」失败，已忽略"


async def execute(
    db: AsyncSession,
    initiator: AgentSubject | object,
    output: str,
    *,
    user_id: uuid.UUID | None = None,
    execution_context: ExecutionContext | None = None,
    feature_flag_resolver: FeatureFlagResolver | None = None,
    executor_factory: ExecutorFactory = DeliverySkillExecutor,
) -> SkillResult:
    """Execute delivery directives without allowing protocol failures to escape."""
    subject = agent_subject(initiator)
    context = merge_execution_context(execution_context, user_id=user_id)
    result = SkillResult()
    try:
        items = parse(output)
        if not items or not await _enabled(db, feature_flag_resolver):
            return result
        if context.user_id is None:
            result.notes.append("交付需指定接收人，自动任务无桌面归属，已跳过文件交付")
            return result
        requests = [
            SkillRequest(
                skill_key="deliver",
                action_index=index,
                arguments={
                    "name": name,
                    "format": file_format,
                    "body": body,
                },
                raw_text=output,
            )
            for index, (name, file_format, body) in enumerate(items)
        ]
        return await dispatch_requests(
            db,
            subject,
            requests,
            context,
            executor_factory=executor_factory,
            failure_note=_delivery_failure_note,
        )
    except Exception:  # noqa: BLE001 - never break the business message flow
        logger.warning("交付协议处理失败", exc_info=True)
    return result


__all__ = [
    "DeliveryArgs",
    "DeliverySkillExecutor",
    "PROMPT_SECTION",
    "execute",
    "parse",
]

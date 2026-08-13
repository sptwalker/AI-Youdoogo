"""Agent 文本协议 adapter：留存知识库（把已确认的结论/报告写入公司知识库）。

终端型内部写（区别于 read_url/web_search 的 interpret 回喂环）：解析【留存知识库】指令 → 经
``knowledge_indexing.public`` 写侧端口 index_text 落库 → 只回 note，不做知识库综合、不链式派发。
写内部知识库属「辅助执行」（可检索复用、可软删、非对外发布），故无真人停点；跨 Context 写一律经
``build_knowledge_index_port`` 选择器（local/remote 对等），绝不直连 gateway。
"""

from __future__ import annotations

import logging
import re
import uuid

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.contracts import (
    AgentSubject,
    ExecutionContext,
    SkillRequest,
    SkillResult,
    agent_subject,
)
from app.agents.directive_dispatch import dispatch_requests, merge_execution_context
from app.contexts.foundations.knowledge.knowledge_indexing.contracts import (
    IndexTextCommand,
)

logger = logging.getLogger(__name__)

_MAX_ARCHIVES = 2
# 一行指令头「标题：<标题>」+ 紧随一个代码块作为正文（正文可多行，`.` 需跨行 → DOTALL）。
_ARCHIVE_RE = re.compile(
    r"【留存知识库】\s*标题[：:]\s*([^\n]+?)\s*\n+```[^\n]*\n(.*?)\n?```",
    re.DOTALL,
)


class KnowledgeIndexArgs(BaseModel):
    """结构化留存参数。"""

    title: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1)


def parse(output: str) -> list[tuple[str, str]]:
    """从 Agent 文本解析至多 _MAX_ARCHIVES 条留存指令；★不触任何外部调用★。"""
    items = [
        (title.strip(), body)
        for title, body in _ARCHIVE_RE.findall(output or "")
        if title.strip() and body.strip()
    ]
    return items[:_MAX_ARCHIVES]


class KnowledgeIndexSkillExecutor:
    """把一段已确认内容留存到默认知识库（终端型内部写，无停点、无回喂）。"""

    key = "knowledge_index"

    def requires_idempotency(self, _request: SkillRequest) -> bool:
        # 归档可重入：重复留存至多多一条内部文档（可软删），无不可逆对外副作用 → 免持久化幂等。
        return False

    async def execute(
        self,
        db: AsyncSession,
        role: AgentSubject | object,
        request: SkillRequest,
        context: ExecutionContext,
    ) -> SkillResult:
        del role
        args = KnowledgeIndexArgs.model_validate(request.arguments)
        if context.user_id is None:
            # 无归属用户（无操作人的纯自动任务）→ 无 uploader，安全跳过（不硬造 uploader）。
            return SkillResult(notes=["留存知识库需归属用户，当前任务无归属，已跳过留存"])
        # 懒加载跨 Context 门面，避免模块装载期形成 knowledge_indexing↔wiki_management 依赖环。
        from app.contexts.foundations.knowledge.knowledge_indexing.public import (
            build_knowledge_index_port,
        )
        from app.contexts.foundations.knowledge.wiki_management.public import (
            get_default_knowledge_base,
        )

        base = await get_default_knowledge_base(db)
        document = await build_knowledge_index_port(db).index_text(
            IndexTextCommand(
                title=args.title,
                text=args.body,
                uploader_id=context.user_id,
                knowledge_base_id=base.id,
                category="report",
            )
        )
        return SkillResult(notes=[f"已留存到知识库「{document.file_name}」，后续可检索复用"])


def _archive_failure_note(request: SkillRequest) -> str:
    title = str(request.arguments.get("title", ""))
    logger.warning("留存知识库执行失败 title=%s", title[:60], exc_info=True)
    return f"留存「{title[:60]}」失败，已忽略"


async def execute(
    db: AsyncSession,
    initiator: AgentSubject | object,
    output: str,
    *,
    user_id: uuid.UUID | None = None,
    execution_context: ExecutionContext | None = None,
) -> SkillResult:
    """解析并执行留存指令；任何协议失败都不打断消息流。"""
    context = merge_execution_context(execution_context, user_id=user_id)
    subject = agent_subject(initiator)
    result = SkillResult()
    try:
        items = parse(output)
        if not items:
            return result
        requests = [
            SkillRequest(
                skill_key="knowledge_index",
                action_index=index,
                arguments={"title": title, "body": body},
                raw_text=output,
            )
            for index, (title, body) in enumerate(items)
        ]
        return await dispatch_requests(
            db,
            subject,
            requests,
            context,
            executor_factory=KnowledgeIndexSkillExecutor,
            failure_note=_archive_failure_note,
        )
    except Exception:  # noqa: BLE001 - 留存协议失败不得打断消息流
        logger.warning("留存知识库协议处理失败", exc_info=True)
    return result


async def prompt_section() -> str:
    """广告留存指令（内部写，无凭证依赖 → 恒可用；是否触发由模型按用户诉求判断）。"""
    return (
        "\n\n留存知识库:当用户明确要把一份已确认的结论/报告长期沉淀到公司知识库（供日后检索复用）时，"
        "单独一行写 【留存知识库】标题：<标题>，紧接一个 ``` 代码块放正文，系统会把它写入知识库。"
        "仅留存已确认无误的内容，每次回复最多 2 条；这是内部知识沉淀，不是对外发布。"
    )


__all__ = [
    "KnowledgeIndexArgs",
    "KnowledgeIndexSkillExecutor",
    "execute",
    "parse",
    "prompt_section",
]

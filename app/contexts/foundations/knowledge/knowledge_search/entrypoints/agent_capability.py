"""Agent 文本协议：显式检索历史同类案例（步骤⑤），复用 read_url 的「取回→回喂综合」环。

与 read_url 唯一差异：检索源是**公司内部知识库**（可信）而非外部网页，故不加防注入 fence
（沿用对 KB 内容的既有信任约定）；且检索范围受 agent 可见知识库权限约束
（operations.search_visible）。只读、无副作用 → 进 AUTOMATIC，编排步无真人停点。
"""

from __future__ import annotations

import logging
import re
import uuid

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.contracts import (
    AgentRunner,
    AgentSubject,
    ExecutionContext,
    SkillRequest,
    SkillResult,
    agent_execution_result,
    agent_subject,
)
from app.agents.directive_dispatch import dispatch_requests, merge_execution_context
from app.contexts.foundations.knowledge.knowledge_retrieval.contracts import KnowledgeHit
from app.contexts.foundations.knowledge.knowledge_search.entrypoints import operations
from app.contexts.foundations.workforce.expert_management import public as expert_management

logger = logging.getLogger(__name__)

_MAX_QUERIES = 2
_QUERY_RE = re.compile(r"【检索案例】\s*([^\n]+)")


def _search_failure_note(request: SkillRequest) -> str:
    query = str(request.arguments.get("query", ""))
    logger.warning("案例检索执行失败 query=%s", query[:60], exc_info=True)
    return f"案例检索执行异常，已忽略:{query[:60]}"


class KnowledgeSearchArgs(BaseModel):
    """结构化检索参数。"""

    query: str = Field(min_length=1, max_length=400)


def parse(output: str) -> list[str]:
    """从 Agent 回复中解析至多两条案例检索指令。"""
    queries = [match.strip() for match in _QUERY_RE.findall(output or "") if match.strip()]
    return queries[:_MAX_QUERIES]


def render_hits(hits: tuple[KnowledgeHit, ...]) -> str:
    """把命中片段渲染成回喂 Agent 的参考块。"""
    blocks = [
        f"{index}. 《{hit.document_name}》(片段 {hit.chunk_index})\n   {hit.content}"
        for index, hit in enumerate(hits, 1)
    ]
    return "\n".join(blocks)


class KnowledgeSearchSkillExecutor:
    """执行一次知识库检索并把命中的历史案例回喂给 Agent 参考。"""

    key = "knowledge_search"

    def requires_idempotency(self, _request: SkillRequest) -> bool:
        return False

    async def execute(
        self,
        db: AsyncSession,
        role: AgentSubject | object,
        request: SkillRequest,
        context: ExecutionContext,
    ) -> SkillResult:
        subject = agent_subject(role)
        args = KnowledgeSearchArgs.model_validate(request.arguments)
        result = SkillResult()
        hits = await operations.search_visible(db, subject, args.query)
        if not hits:
            # 如实声明无同类案例，绝不臆造（docs/26 §P0-2 验收项）。
            result.notes.append(f"未检索到同类历史案例:{args.query[:60]}")
            return result
        result.datasets.append(
            {
                "query": args.query,
                "hits": [
                    {
                        "document_id": str(hit.document_id),
                        "document_name": hit.document_name,
                        "chunk_index": hit.chunk_index,
                        "content": hit.content,
                    }
                    for hit in hits
                ],
            }
        )
        await self._interpret(db, subject, request.raw_text or args.query, hits, context, result)
        return result

    async def _interpret(
        self,
        db: AsyncSession,
        initiator: AgentSubject,
        original: str,
        hits: tuple[KnowledgeHit, ...],
        context: ExecutionContext,
        result: SkillResult,
    ) -> None:
        intent_line = (
            f"用户的原始诉求是:「{context.user_intent.strip()}」。请据此聚焦参考。\n"
            if context.user_intent and context.user_intent.strip()
            else ""
        )
        prompt = (
            "你之前的回复中发起了历史案例检索，系统已在公司知识库中检索到以下同类案例与处置参考:\n\n"
            f"{render_hits(hits)}\n\n"
            f"{intent_line}"
            "请结合以上历史案例，提炼可借鉴的处置经验并融入你的答复；"
            "只依据检索到的内容，不要编造未检索到的案例;引用处标注来源文档名。"
            "不要再写【检索案例】指令（资料已就绪）。"
        )
        runner = context.agent_runner
        if runner is None:
            result.notes.append("历史案例已检索就绪，但缺少 AgentRunner，未生成综合参考")
            return
        expert = await expert_management.get_expert_execution(db, initiator.expert_id)
        if expert is None:
            result.notes.append("历史案例已检索就绪，但专家执行快照不存在，未生成综合参考")
            return
        record = await runner(
            db,
            expert,
            task_type="knowledge_search_synthesis",
            input_summary=f"综合历史案例:{original[:40]}",
            user_message=prompt,
            user_id=context.user_id,
            use_knowledge=False,
            execution_context=context,
        )
        result.consult_replies.append((initiator, agent_execution_result(record)))
        interpret_text = record.output_content or ""
        if interpret_text and context.dispatcher is not None:
            sub = await context.dispatcher.dispatch_text(
                db,
                initiator,
                interpret_text,
                context,
                exclude=set(context.excluded_skills) | {"knowledge_search"},
            )
            result.merge(sub)


async def execute(
    db: AsyncSession,
    initiator: AgentSubject | object,
    output: str,
    *,
    user_id: uuid.UUID | None = None,
    user_intent: str | None = None,
    exclude: set[str] | None = None,
    execution_context: ExecutionContext | None = None,
    agent_runner: AgentRunner | None = None,
) -> SkillResult:
    """解析并执行案例检索指令，任何失败都不打断消息流。"""
    subject = agent_subject(initiator)
    context = merge_execution_context(
        execution_context,
        user_id=user_id,
        user_intent=user_intent,
        agent_runner=agent_runner,
        exclude=exclude,
    )
    result = SkillResult()
    try:
        queries = parse(output)
        if not queries:
            return result
        requests = [
            SkillRequest(
                skill_key="knowledge_search",
                action_index=index,
                arguments={"query": query},
                raw_text=output,
            )
            for index, query in enumerate(queries)
        ]
        return await dispatch_requests(
            db,
            subject,
            requests,
            context,
            executor_factory=KnowledgeSearchSkillExecutor,
            failure_note=_search_failure_note,
        )
    except Exception:  # noqa: BLE001 - 检索协议失败不得打断消息流
        logger.warning("案例检索协议处理失败", exc_info=True)
    return result


async def prompt_section() -> str:
    """广告案例检索指令（只读，纯内部，无需门控开关，始终可用）。"""
    return (
        "\n\n历史案例检索:需要参考公司过往同类处置经验时，单独一行写 "
        "【检索案例】<查询关键词>，系统会在你可见的知识库中检索并把命中的历史案例加入对话，"
        "你可据此提炼处置参考。每次回复最多 2 次；若无同类案例，请如实说明、不要臆造。"
    )


__all__ = [
    "KnowledgeSearchArgs",
    "KnowledgeSearchSkillExecutor",
    "execute",
    "parse",
    "prompt_section",
    "render_hits",
]

"""Agent text-protocol and typed-capability adapter for governed data queries."""

from __future__ import annotations

import logging
import re
import uuid
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.contracts import AgentRunner, ExecutionContext, SkillRequest, SkillResult
from app.agents.directive_dispatch import dispatch_requests, merge_execution_context
from app.contexts.foundations.integration.governed_data_query.contracts import (
    GovernedQueryRequest,
)
from app.contexts.foundations.integration.governed_data_query.entrypoints import operations
from app.models.agent import AgentRole

logger = logging.getLogger(__name__)

_MAX_QUERIES = 2
_MAX_PREVIEW_ROWS = 50
_QUERY_RE = re.compile(r"【取数】\s*([^\n]+)")

FallbackExecutor = Callable[
    [AsyncSession, AgentRole, str, ExecutionContext, set[str]],
    Awaitable[SkillResult],
]
ExecutorFactory = Callable[[], "DataQuerySkillExecutor"]
RunnerProvider = Callable[[], AgentRunner | None]


def _query_failure_note(request: SkillRequest) -> str:
    sql = str(request.arguments.get("sql", ""))
    logger.warning("取数执行失败 sql=%s", sql[:80], exc_info=True)
    return f"取数执行异常，已忽略:{sql[:80]}"


class ReadonlyQuery(Protocol):
    async def __call__(
        self,
        db: AsyncSession,
        sql: str,
        *,
        actor_id: uuid.UUID | None,
        actor_role: str | None,
        source: str = "agent",
    ) -> dict[str, Any]: ...


class FeatureFlagResolver(Protocol):
    async def __call__(
        self,
        db: AsyncSession,
        key: str,
        default: Any = None,
    ) -> Any: ...


class DataQueryArgs(BaseModel):
    """Structured read-only query arguments."""

    sql: str = Field(min_length=1, max_length=12000)


async def run_readonly_sql(
    db: AsyncSession,
    sql: str,
    *,
    actor_id: uuid.UUID | None,
    actor_role: str | None,
    source: str = "agent",
) -> dict[str, Any]:
    """Run one query through the local published Governed Data Query operation."""
    result = await operations.run_query(
        db,
        GovernedQueryRequest(
            sql=sql,
            actor_id=actor_id,
            actor_role=actor_role,
            source=source,
        ),
    )
    return result.to_dict()


def parse(output: str) -> list[str]:
    """Parse at most two governed-query directives from an Agent response."""
    sqls = [match.strip() for match in _QUERY_RE.findall(output or "") if match.strip()]
    return sqls[:_MAX_QUERIES]


def render_table(result: dict[str, Any]) -> str:
    """Render one query result as the compact Markdown table fed back to the Agent."""
    rows = result.get("rows") or []
    columns = result.get("columns") or []
    if not rows:
        return "（0 行）"
    head = "| " + " | ".join(columns) + " |"
    separator = "| " + " | ".join("---" for _ in columns) + " |"
    body = [
        "| " + " | ".join(str(row.get(column, "")) for column in columns) + " |"
        for row in rows[:_MAX_PREVIEW_ROWS]
    ]
    tail = f"\n（共 {result['row_count']} 行" + (
        "，已截断" if result.get("truncated") else ""
    ) + "）"
    return "\n".join([head, separator, *body]) + tail


async def _enabled(
    db: AsyncSession,
    resolver: FeatureFlagResolver | None,
) -> bool:
    if resolver is None:
        return True
    flag = await resolver(db, "agent_data_query", True)
    return str(flag).lower() not in ("false", "0")


class DataQuerySkillExecutor:
    """Execute one typed governed query and feed successful data back to the Agent."""

    key = "data_query"

    def __init__(
        self,
        *,
        runner_provider: RunnerProvider | None = None,
        query_provider: Callable[[], ReadonlyQuery] | None = None,
        fallback_executor: FallbackExecutor | None = None,
    ) -> None:
        self._runner_provider = runner_provider
        self._query_provider = query_provider
        self._fallback_executor = fallback_executor

    def requires_idempotency(self, _request: SkillRequest) -> bool:
        return False

    async def execute(
        self,
        db: AsyncSession,
        role: AgentRole,
        request: SkillRequest,
        context: ExecutionContext,
    ) -> SkillResult:
        args = DataQueryArgs.model_validate(request.arguments)
        result = SkillResult()
        query = self._query_provider() if self._query_provider is not None else run_readonly_sql
        query_result = await query(
            db,
            args.sql,
            actor_id=context.user_id,
            actor_role=None,
            source=f"agent:{role.name}",
        )
        status = query_result.get("status")
        if status == "rejected":
            result.notes.append(
                f"取数被拒（{query_result.get('reason', '')}）:{args.sql[:80]}"
            )
            return result
        if status == "fail":
            result.notes.append(
                f"取数失败（{query_result.get('msg', '')}）:{args.sql[:80]}"
            )
            return result
        result.datasets.append(
            {
                "sql": args.sql,
                "columns": query_result.get("columns") or [],
                "rows": query_result.get("rows") or [],
                "row_count": query_result.get("row_count", 0),
                "truncated": bool(query_result.get("truncated")),
            }
        )
        await self._interpret(
            db,
            role,
            request.raw_text or args.sql,
            [f"查询:{args.sql}\n结果:\n{render_table(query_result)}"],
            context,
            result,
        )
        return result

    async def _interpret(
        self,
        db: AsyncSession,
        initiator: AgentRole,
        original: str,
        blocks: list[str],
        context: ExecutionContext,
        result: SkillResult,
    ) -> None:
        data_text = "\n\n".join(blocks)
        intent_line = (
            f"用户的原始诉求是:「{context.user_intent.strip()}」。请据此判断除解读外是否还需交付文档"
            "（若用户要日报/表格/文件，请用【交付】指令生成对应文件）。\n"
            if context.user_intent and context.user_intent.strip()
            else ""
        )
        prompt = (
            f"你之前的回复中发起了数据查询，系统已执行并返回真实结果如下:\n\n{data_text}\n\n"
            f"{intent_line}"
            "请基于以上真实数据，面向提问者给出简明的运营解读:先用 1~3 句话说明关键结论"
            "（如整体量级、亮点或异常），再用一个清晰的 Markdown 表格呈现核心指标。"
            "只依据上面的数据，不要编造未查询的数字;不要再写【取数】指令"
            "（数据已就绪，无需再查）。"
        )
        runner = (
            self._runner_provider() if self._runner_provider is not None else None
        ) or context.agent_runner
        if runner is None:
            result.notes.append("取数结果已生成，但缺少 AgentRunner，未生成自然语言解读")
            return
        record = await runner(
            db,
            initiator,
            task_type="data_interpret",
            input_summary=f"解读取数结果:{original[:40]}",
            user_message=prompt,
            user_id=context.user_id,
            use_knowledge=False,
            execution_context=context,
        )
        result.consult_replies.append((initiator, record))
        interpret_text = record.output_content or ""
        excluded = set(context.excluded_skills)
        if interpret_text and context.dispatcher is not None:
            sub = await context.dispatcher.dispatch_text(
                db,
                initiator,
                interpret_text,
                context,
                exclude=excluded | {"data_query"},
            )
            result.merge(sub)
        elif (
            interpret_text
            and self._fallback_executor is not None
            and "deliver" not in excluded
        ):
            result.merge(
                await self._fallback_executor(
                    db,
                    initiator,
                    interpret_text,
                    context,
                    excluded,
                )
            )


async def execute(
    db: AsyncSession,
    initiator: AgentRole,
    output: str,
    *,
    user_id: uuid.UUID | None = None,
    user_intent: str | None = None,
    exclude: set[str] | None = None,
    execution_context: ExecutionContext | None = None,
    agent_runner: AgentRunner | None = None,
    feature_flag_resolver: FeatureFlagResolver | None = None,
    executor_factory: ExecutorFactory = DataQuerySkillExecutor,
) -> SkillResult:
    """Parse and execute governed-query directives without breaking the message flow."""
    context = merge_execution_context(
        execution_context,
        user_id=user_id,
        user_intent=user_intent,
        agent_runner=agent_runner,
        exclude=exclude,
    )
    result = SkillResult()
    try:
        sqls = parse(output)
        if not sqls:
            return result
        if not await _enabled(db, feature_flag_resolver):
            return result

        requests = [
            SkillRequest(
                skill_key="data_query",
                action_index=index,
                arguments={"sql": sql},
                raw_text=output,
            )
            for index, sql in enumerate(sqls)
        ]
        return await dispatch_requests(
            db,
            initiator,
            requests,
            context,
            executor_factory=executor_factory,
            failure_note=_query_failure_note,
        )
    except Exception:  # noqa: BLE001 - query protocol failure must not break the message flow
        logger.warning("取数协议处理失败", exc_info=True)
    return result


async def prompt_section(db: AsyncSession) -> str:
    """Build the catalog-backed Agent prompt section for governed queries."""
    catalog = await operations.catalog_prompt(db)
    if not catalog:
        return ""
    return (
        catalog + "\n取数指令:需要数据时，单独一行写 【取数】<你的只读 SELECT 语句>，"
        "系统会自动校验执行并把结果表格加入对话。每次回复最多 2 次;"
        "只能 SELECT 上表列出的视图，系统会自动限制返回行数。"
    )


__all__ = [
    "DataQueryArgs",
    "DataQuerySkillExecutor",
    "execute",
    "parse",
    "prompt_section",
    "render_table",
    "run_readonly_sql",
]

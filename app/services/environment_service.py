"""系统档案员与环境快照（docs/13 §9）：让所有 AI 感知系统环境。

- 档案员是常驻种子 AI 身份（code=sys_archivist），仅有资料整理权：快照写入知识库以它留痕，
  采集由确定性代码完成（准确/可审计/零幻觉），不经 LLM。
- build_snapshot 渲染组织树 + AI 花名册 + 真人名录 + 数据接口清单（含对接AI）；
  不含任何敏感字段（密码/secret_ref/config 一律不进快照）。
- 来源变更经 transactional outbox 单向通知本投影；refresh_env_doc 保留为兼容入口，
  get_env_context 供提示词注入（实时 build + 60s 缓存）。
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import app.knowledge.ingest as _legacy_ingest
import app.services.agent_role_service as agent_role_service
import app.services.auth_service as auth_service
import app.services.data_source_service as data_source_service
import app.services.org_service as org_service
from app.contexts.foundations.environment_projection.contracts.context_snapshot import (
    ContextSnapshot,
    MissingSnapshotSource,
    SnapshotProvenance,
    SnapshotScope,
    SnapshotSourceVersion,
)
from app.contexts.foundations.environment_projection.contracts.source_change import (
    EnvironmentSourceChange,
)
from app.contexts.foundations.environment_projection.infrastructure.archivist import (
    ARCHIVIST_CODE as ARCHIVIST_CODE,
)
from app.contexts.foundations.environment_projection.infrastructure.archivist import (
    ARCHIVIST_NAME as ARCHIVIST_NAME,
)
from app.contexts.foundations.environment_projection.infrastructure.archivist import (
    ensure_archivist as ensure_archivist,
)
from app.contexts.foundations.knowledge.knowledge_indexing.contracts import IndexTextCommand
from app.contexts.foundations.knowledge.knowledge_indexing.public import (
    index_text,
    remove_document_index,
)
from app.contexts.foundations.knowledge.wiki_management.public import (
    get_default_knowledge_base,
)
from app.models.knowledge import KnowledgeFile
from app.models.system import SysUser
from app.platform.outbox.model import OutboxEvent
from app.platform.outbox.source_change import (
    DEFAULT_TENANT_ID,
    ENVIRONMENT_SOURCE_CHANGED_V1,
)

logger = logging.getLogger(__name__)

# Kept for compatibility with tests/plugins that monkeypatch the old ingestion seam.
ingest = _legacy_ingest

ENV_DOC_TITLE = "系统环境快照"
_ENV_DOC_CATEGORY = "系统档案"
_CACHE_TTL_SECONDS = 60.0

_TIER_LABEL = {"exec": "高管", "director": "总监", "member": "员工"}
_ROLE_LABEL = {"admin": "管理员", "executive": "高管", "member": "员工"}
_SECRET_LABEL = {"not_set": "未配置密钥", "configured": "密钥已配置", "missing": "密钥缺失"}

_SNAPSHOT_AREAS = ("organization", "expert", "identity", "connector")

# 注入用快照缓存。来源事件触发 refresh_env_doc 时一并失效。
_cache: ContextSnapshot | None = None


def _render_tree(nodes: list[dict[str, Any]], counts: dict[str, int], depth: int = 0) -> list[str]:
    """渲染组织树。计数来自花名册同一份数据（直挂本节点的AI数，不含真人专属助理），
    与花名册口径一致——不用 get_tree 的 employee_count（那是给组织页的，含助理）。"""
    lines: list[str] = []
    for n in nodes:
        lines.append(f"{'  ' * depth}- {n['name']}（直属AI员工 {counts.get(n['id'], 0)} 名）")
        lines.extend(_render_tree(n["children"], counts, depth + 1))
    return lines


async def build_snapshot(db: AsyncSession) -> str:
    """确定性渲染环境快照（markdown）。数据源均稳定排序，同状态下两次调用结果一致。"""
    tree = await org_service.get_tree(db)
    agents = await agent_role_service.list_agent_roles(db)
    users = await auth_service.list_users(db)
    sources = await data_source_service.list_ds(db)

    dept_name: dict[str, str] = {}

    def _collect(nodes: list[dict[str, Any]]) -> None:
        for n in nodes:
            dept_name[n["id"]] = n["name"]
            _collect(n["children"])

    _collect(tree)

    def _dept(dept_id: Any) -> str:
        return dept_name.get(str(dept_id), "未挂部门") if dept_id else "未挂部门"

    # 各节点直属AI数（与花名册同一数据源，口径一致）
    dept_counts: dict[str, int] = {}
    for a in agents:
        if a.department_id:
            key = str(a.department_id)
            dept_counts[key] = dept_counts.get(key, 0) + 1
    unassigned = sum(1 for a in agents if not a.department_id)

    agent_lines = [
        f"- {a.name}（{_TIER_LABEL.get(a.tier, a.tier)}"
        + (f"，{a.title}" if a.title and a.title != a.name else "")
        + f"，{_dept(a.department_id)}"
        + ("" if a.is_active else "，已停用")
        + "）"
        for a in agents
    ]
    user_lines = [
        f"- {u.real_name or u.username}（账号 {u.username}，"
        f"{_ROLE_LABEL.get(u.role_code, u.role_code)}，{_dept(u.department_id)}"
        + ("" if u.is_active else "，已停用")
        + "）"
        for u in users
    ]
    agent_by_id = {str(a.id): a.name for a in agents}
    ds_lines = [
        f"- {s['name']}（类型 {s['type']}，{'启用' if s['is_active'] else '停用'}，"
        f"{_SECRET_LABEL.get(s['secret_status'], s['secret_status'])}，"
        f"对接AI：{agent_by_id.get(s.get('owner_agent_id') or '', '未指派')}）"
        for s in sources
    ]

    def _section(title: str, lines: list[str], empty: str) -> str:
        return f"## {title}\n" + ("\n".join(lines) if lines else f"（{empty}）")

    roster_title = f"AI 员工花名册（共 {len(agents)} 名"
    roster_title += f"，其中未挂部门 {unassigned} 名）" if unassigned else "）"
    return "\n\n".join(
        [
            f"# {ENV_DOC_TITLE}",
            "本文档由系统档案员自动维护，反映系统当前的组织架构、AI员工、真人用户与数据接口。"
            "（AI员工数不含真人的专属助理；组织树括号内为直挂该节点的AI数，非子树合计。）",
            _section("组织架构", _render_tree(tree, dept_counts), "尚未初始化组织树"),
            _section(roster_title, agent_lines, "暂无AI员工"),
            _section("真人用户", user_lines, "暂无用户"),
            _section("数据接口", ds_lines, "暂无数据接口"),
        ]
    )


async def _snapshot_source_metadata(
    db: AsyncSession,
) -> tuple[tuple[SnapshotProvenance, ...], tuple[SnapshotSourceVersion, ...]]:
    """Translate committed source-change evidence into immutable snapshot metadata."""
    events = list(
        (
            await db.execute(
                select(OutboxEvent)
                .where(OutboxEvent.event_type == ENVIRONMENT_SOURCE_CHANGED_V1)
                .order_by(OutboxEvent.create_time, OutboxEvent.id)
            )
        ).scalars()
    )
    newest: dict[tuple[str, uuid.UUID], tuple[EnvironmentSourceChange, uuid.UUID]] = {}
    for event in events:
        try:
            change = EnvironmentSourceChange.from_wire(
                event_id=event.id,
                event_type=event.event_type,
                payload=event.payload,
            )
        except (TypeError, ValueError):
            logger.warning("忽略无效的环境来源事件 event_id=%s", event.id, exc_info=True)
            continue
        if change.tenant_id != DEFAULT_TENANT_ID:
            continue
        key = (change.source_type, change.source_id)
        current = newest.get(key)
        if current is None or change.source_version > current[0].source_version:
            newest[key] = (change, event.id)

    ordered = sorted(
        newest.values(),
        key=lambda item: (item[0].source_type, str(item[0].source_id)),
    )
    provenance = tuple(
        SnapshotProvenance(
            event_id=event_id,
            source_type=change.source_type,
            source_id=change.source_id,
            observed_at=change.occurred_at,
        )
        for change, event_id in ordered
    )
    versions = tuple(
        SnapshotSourceVersion(
            source_type=change.source_type,
            source_id=change.source_id,
            version=change.source_version,
        )
        for change, _event_id in ordered
    )
    return provenance, versions


async def get_context_snapshot(db: AsyncSession) -> ContextSnapshot:
    """Return the canonical scoped snapshot contract with freshness metadata."""
    global _cache
    now = datetime.now(UTC)
    if _cache is not None and not _cache.is_expired(now):
        return _cache
    scope = SnapshotScope(tenant_id=DEFAULT_TENANT_ID, areas=_SNAPSHOT_AREAS)
    try:
        content = await build_snapshot(db)
        provenance, versions = await _snapshot_source_metadata(db)
    except Exception:  # noqa: BLE001 - callers inspect stale/missing instead of failing open
        logger.warning("环境快照构建失败，本次不注入", exc_info=True)
        return ContextSnapshot(
            scope=scope,
            content="",
            provenance=(),
            source_versions=(),
            missing=tuple(
                MissingSnapshotSource(source_type=area, reason="projection_unavailable")
                for area in scope.areas
            ),
            stale=True,
            generated_at=now,
            expires_at=now,
        )
    snapshot = ContextSnapshot(
        scope=scope,
        content=content,
        provenance=provenance,
        source_versions=versions,
        missing=(),
        stale=False,
        generated_at=now,
        expires_at=now + timedelta(seconds=_CACHE_TTL_SECONDS),
    )
    _cache = snapshot
    return snapshot


def invalidate_cache() -> None:
    """Mark the process-local prompt snapshot stale."""
    global _cache
    _cache = None


async def refresh_env_doc(db: AsyncSession, *, suppress_errors: bool = True) -> None:
    """刷新快照文档（upsert 进公司公共知识库，以档案员留痕）。

    直接兼容调用默认吞异常；Outbox handler 使用严格模式以触发租约重试。
    """
    invalidate_cache()
    try:
        kb = await get_default_knowledge_base(db)
        # uploader 是非空 FK→sys_user，取最早的 admin；无 admin（如初装）则先跳过
        admin = (
            await db.execute(
                select(SysUser)
                .where(SysUser.role_code == "admin", SysUser.is_delete.is_(False))
                .order_by(SysUser.create_time)
                .limit(1)
            )
        ).scalar_one_or_none()
        if admin is None:
            logger.warning("环境快照跳过：系统尚无 admin 用户可作 uploader")
            return
        text = await build_snapshot(db)
        old = (
            await db.execute(
                select(KnowledgeFile).where(
                    KnowledgeFile.file_name == ENV_DOC_TITLE,
                    KnowledgeFile.knowledge_base_id == kb.id,
                    KnowledgeFile.is_delete.is_(False),
                )
            )
        ).scalars()
        for f in old:
            await remove_document_index(db, f.id)
        await index_text(
            db,
            IndexTextCommand(
                title=ENV_DOC_TITLE,
                text=text,
                uploader_id=admin.id,
                knowledge_base_id=kb.id,
                category=_ENV_DOC_CATEGORY,
                publish_events=False,
            ),
        )
    except Exception:  # noqa: BLE001 - compatibility calls remain non-fatal
        logger.warning("环境快照刷新失败（不影响业务操作）", exc_info=True)
        if not suppress_errors:
            raise


async def get_env_context(db: AsyncSession) -> str:
    """提示词注入用的实时快照（60 秒缓存）。失败返回空串，不阻断 AI 执行。"""
    snapshot = await get_context_snapshot(db)
    return snapshot.content if snapshot.is_usable() else ""

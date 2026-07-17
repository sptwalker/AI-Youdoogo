"""系统档案员与环境快照（docs/13 §9）：让所有 AI 感知系统环境。

- 档案员是常驻种子 AI 身份（code=sys_archivist），仅有资料整理权：快照写入知识库以它留痕，
  采集由确定性代码完成（准确/可审计/零幻觉），不经 LLM。
- build_snapshot 渲染组织树 + AI 花名册 + 真人名录 + 数据接口清单（含对接AI）；
  不含任何敏感字段（密码/secret_ref/config 一律不进快照）。
- refresh_env_doc 在组织/用户/AI/数据源变更后被各 service 同步直调（整体吞异常，
  embedding 故障不连累业务操作）；get_env_context 供提示词注入（实时 build + 60s 缓存）。
"""

from __future__ import annotations

import logging
import time
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.knowledge import ingest
from app.models.agent import TIER_MEMBER, AgentRole
from app.models.knowledge import KnowledgeFile
from app.models.system import SysUser
from app.services import (
    agent_role_service,
    auth_service,
    data_source_service,
    knowledge_base_service,
    org_service,
)

logger = logging.getLogger(__name__)

ARCHIVIST_CODE = "sys_archivist"
ARCHIVIST_NAME = "系统档案员"
ENV_DOC_TITLE = "系统环境快照"
_ENV_DOC_CATEGORY = "系统档案"
_CACHE_TTL_SECONDS = 60.0

_ARCHIVIST_PROMPT = (
    "你是系统档案员，负责维护《系统环境快照》：公司组织架构、AI员工花名册、真人名录、"
    "数据接口清单。你只有资料整理权，无业务决议权；快照内容由系统代码自动采集，你以此身份留痕。"
)

_TIER_LABEL = {"exec": "高管", "director": "总监", "member": "员工"}
_ROLE_LABEL = {"admin": "管理员", "executive": "高管", "member": "员工"}
_SECRET_LABEL = {"not_set": "未配置密钥", "configured": "密钥已配置", "missing": "密钥缺失"}

# 注入用快照缓存：(渲染时间, 文本)。变更触发 refresh_env_doc 时一并失效。
_cache: tuple[float, str] | None = None


async def ensure_archivist(db: AsyncSession) -> AgentRole:
    """取或建系统档案员（幂等，启动自举）。挂公司根节点（无根则暂不挂）。"""
    stmt = select(AgentRole).where(
        AgentRole.code == ARCHIVIST_CODE, AgentRole.is_delete.is_(False)
    )
    agent = (await db.execute(stmt)).scalar_one_or_none()
    if agent is not None:
        return agent
    from app.models.system import COMPANY, SysDepartment

    root = (
        await db.execute(
            select(SysDepartment).where(
                SysDepartment.node_type == COMPANY, SysDepartment.is_delete.is_(False)
            )
        )
    ).scalar_one_or_none()
    agent = AgentRole(
        code=ARCHIVIST_CODE, name=ARCHIVIST_NAME, title="系统档案员", tier=TIER_MEMBER,
        model_role="daily", department_id=root.id if root else None, is_seed=True,
        duty="维护系统环境快照（组织/AI/用户/数据接口）", prompt_template=_ARCHIVIST_PROMPT,
    )
    db.add(agent)
    await db.commit()
    await db.refresh(agent)
    return agent


def _render_tree(
    nodes: list[dict[str, Any]], counts: dict[str, int], depth: int = 0
) -> list[str]:
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
    return "\n\n".join([
        f"# {ENV_DOC_TITLE}",
        "本文档由系统档案员自动维护，反映系统当前的组织架构、AI员工、真人用户与数据接口。"
        "（AI员工数不含真人的专属助理；组织树括号内为直挂该节点的AI数，非子树合计。）",
        _section("组织架构", _render_tree(tree, dept_counts), "尚未初始化组织树"),
        _section(roster_title, agent_lines, "暂无AI员工"),
        _section("真人用户", user_lines, "暂无用户"),
        _section("数据接口", ds_lines, "暂无数据接口"),
    ])


async def refresh_env_doc(db: AsyncSession) -> None:
    """变更后刷新快照文档（upsert 进公司公共知识库，以档案员留痕）。

    整体吞异常：embedding/知识库故障绝不连累触发它的业务操作；下次变更自然重试。
    """
    global _cache
    _cache = None  # 注入缓存立即失效，提示词侧下次实时重建
    try:
        kb = await knowledge_base_service.get_default_kb(db)
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
            await ingest.delete_file(db, f.id)
        await ingest.ingest_text(
            db, title=ENV_DOC_TITLE, text=text,
            uploader_id=admin.id, knowledge_base_id=kb.id, category=_ENV_DOC_CATEGORY,
        )
    except Exception:  # noqa: BLE001 - 快照失败不阻断业务操作，记日志下次重试
        logger.warning("环境快照刷新失败（不影响业务操作）", exc_info=True)


async def get_env_context(db: AsyncSession) -> str:
    """提示词注入用的实时快照（60 秒缓存）。失败返回空串，不阻断 AI 执行。"""
    global _cache
    now = time.monotonic()
    if _cache is not None and now - _cache[0] < _CACHE_TTL_SECONDS:
        return _cache[1]
    try:
        text = await build_snapshot(db)
    except Exception:  # noqa: BLE001 - 环境注入失败不阻断 AI
        logger.warning("环境快照构建失败，本次不注入", exc_info=True)
        return ""
    _cache = (now, text)
    return text

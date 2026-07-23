"""Persistence adapter for the Environment Projection's archival identity."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.foundations.organization_structure import public as organization_structure
from app.contexts.foundations.workforce.expert_management import public as expert_management

ARCHIVIST_CODE = "sys_archivist"
ARCHIVIST_NAME = "系统档案员"

_ARCHIVIST_PROMPT = (
    "你是系统档案员，负责维护《系统环境快照》：公司组织架构、AI员工花名册、真人名录、"
    "数据接口清单。你只有资料整理权，无业务决议权；快照内容由系统代码自动采集，你以此身份留痕。"
)


async def ensure_archivist(db: AsyncSession) -> expert_management.LegacyExpertView:
    """Ensure the archival expert through the sole Expert Management writer."""
    organization = await organization_structure.get_snapshot(db)
    root = organization.roots[0].department if organization.roots else None
    snapshot = await expert_management.seed_expert(
        db,
        code=ARCHIVIST_CODE,
        name=ARCHIVIST_NAME,
        prompt_template=_ARCHIVIST_PROMPT,
        title="系统档案员",
        tier="member",
        model_role="daily",
        department_id=root.department_id if root is not None else None,
        duty="维护系统环境快照（组织/AI/用户/数据接口）",
        report_to_id=None,
    )
    return expert_management.to_legacy_view(snapshot)

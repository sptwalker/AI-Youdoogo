"""公司骨架幂等种子（F1）：一键初始化 公司根 + 8 一级部门 + 7 高管 + 8 总监。

按稳定 `code` upsert，可重入（管理员改名后重跑不造重复）。不进 Alembic（业务配置非 schema）。
CEO=最高管理员(真人)，不设 CEO Agent；公司根真人主管=触发者/指定 admin。
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import TIER_DIRECTOR, TIER_EXEC, AgentRole
from app.models.system import COMPANY, DEPT_L1, SysDepartment

# 8 个一级部门：code, 名称, 排序
_DEPARTMENTS: list[tuple[str, str, int]] = [
    ("dept_product_base", "基础产品部", 1),
    ("dept_game_rd", "游戏研发部", 2),
    ("dept_platform_ops", "平台运营部", 3),
    ("dept_business", "商务合作部", 4),
    ("dept_marketing", "营销销售部", 5),
    ("dept_brand", "品牌宣传部", 6),
    ("dept_hr", "人资行政部", 7),
    ("dept_finance", "财务部", 8),
]

# 7 高管：code, 职位缩写, 中文全称, 分管部门 code 列表
_EXECS: list[tuple[str, str, str, list[str]]] = [
    ("exec_cpo", "CPO", "首席产品官", ["dept_product_base"]),
    ("exec_cto", "CTO", "首席技术官", ["dept_game_rd"]),
    ("exec_coo", "COO", "首席运营官", ["dept_platform_ops"]),
    ("exec_cmo", "CMO", "首席营销官", ["dept_marketing", "dept_brand"]),
    ("exec_cbo", "CBO", "首席商务官", ["dept_business"]),
    ("exec_cho", "CHO", "首席人事官", ["dept_hr"]),
    ("exec_cfo", "CFO", "首席财务官", ["dept_finance"]),
]

# 8 总监：code, 名称, 所属部门 code, 汇报高管 code
_DIRECTORS: list[tuple[str, str, str, str]] = [
    ("dir_product_base", "基础产品部总监", "dept_product_base", "exec_cpo"),
    ("dir_game_rd", "游戏研发部总监", "dept_game_rd", "exec_cto"),
    ("dir_platform_ops", "运营AI总监", "dept_platform_ops", "exec_coo"),  # 复用现有种子
    ("dir_business", "商务合作部总监", "dept_business", "exec_cbo"),
    ("dir_marketing", "营销销售部总监", "dept_marketing", "exec_cmo"),
    ("dir_brand", "品牌宣传部总监", "dept_brand", "exec_cmo"),
    ("dir_hr", "人资行政部总监", "dept_hr", "exec_cho"),
    ("dir_finance", "财务部总监", "dept_finance", "exec_cfo"),
]

_EXEC_PROMPT = (
    "你是创想悦动的{title}（公司高管AI）。职责：从全局视角对分管领域做战略分析、"
    "风险评估、方案利弊推演，为管理层决策提供参考。红线：你仅有建议/分析权，"
    "涉及资金/人事/项目/业务调整的决议必须真人确认生效。"
)
_DIRECTOR_PROMPT = (
    "你是创想悦动{dept}的AI总监。职责：统筹本部门数据监控、报告生成、任务拆解与执行、"
    "运营优化建议。红线：你仅有建议/执行权，一切生效动作须真人确认，产出可溯源、全程留痕。"
)


async def _get_dept_by_code(db: AsyncSession, code: str) -> SysDepartment | None:
    stmt = select(SysDepartment).where(
        SysDepartment.code == code, SysDepartment.is_delete.is_(False)
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def _get_agent_by_code(db: AsyncSession, code: str) -> AgentRole | None:
    stmt = select(AgentRole).where(AgentRole.code == code, AgentRole.is_delete.is_(False))
    return (await db.execute(stmt)).scalar_one_or_none()


async def _ensure_company_root(db: AsyncSession, ceo_user_id: uuid.UUID | None) -> SysDepartment:
    """确保公司根节点存在（迁移已建；此处兜底 + 设 CEO 真人主管）。"""
    root = await _get_dept_by_code(db, "company")
    if root is None:
        root = SysDepartment(name="创想悦动", code="company", node_type=COMPANY, level=0, path="")
        db.add(root)
        await db.flush()
        root.path = f"/{root.id}/"
    if ceo_user_id is not None:
        root.supervisor_user_id = ceo_user_id  # 公司根主管 = CEO/最高管理员
    return root


async def _upsert_dept(
    db: AsyncSession, root: SysDepartment, code: str, name: str, sort: int
) -> SysDepartment:
    dept = await _get_dept_by_code(db, code)
    if dept is None:
        dept = SysDepartment(
            name=name, code=code, parent_id=root.id, node_type=DEPT_L1, level=1, sort_order=sort
        )
        db.add(dept)
        await db.flush()
        dept.path = f"{root.path}{dept.id}/"
    else:
        dept.name, dept.parent_id, dept.node_type, dept.level = name, root.id, DEPT_L1, 1
        dept.sort_order, dept.path = sort, f"{root.path}{dept.id}/"
    return dept


async def _upsert_agent(
    db: AsyncSession, code: str, name: str, title: str, tier: str, model_role: str,
    department_id: uuid.UUID, prompt: str,
) -> AgentRole:
    agent = await _get_agent_by_code(db, code)
    if agent is None:
        agent = AgentRole(code=code, prompt_template=prompt)
        db.add(agent)
    agent.name, agent.title, agent.tier = name, title, tier
    agent.model_role, agent.department_id, agent.is_seed = model_role, department_id, True
    if not agent.duty:
        agent.duty = title
    return agent


async def seed_org_template(
    db: AsyncSession, *, ceo_user_id: uuid.UUID | None = None
) -> dict[str, Any]:
    """幂等初始化公司骨架。返回各类计数。"""
    root = await _ensure_company_root(db, ceo_user_id)
    await db.flush()

    dept_by_code: dict[str, SysDepartment] = {}
    for code, name, sort in _DEPARTMENTS:
        dept_by_code[code] = await _upsert_dept(db, root, code, name, sort)
    await db.flush()

    exec_by_code: dict[str, AgentRole] = {}
    for code, abbr, full, _ in _EXECS:
        exec_by_code[code] = await _upsert_agent(
            db, code, f"{full}（{abbr}）", abbr, TIER_EXEC, "reasoning",
            root.id, _EXEC_PROMPT.format(title=f"{full}（{abbr}）"),
        )
    await db.flush()

    for code, name, dept_code, exec_code in _DIRECTORS:
        dept = dept_by_code[dept_code]
        director = await _upsert_agent(
            db, code, name, name, TIER_DIRECTOR, "daily",
            dept.id, _DIRECTOR_PROMPT.format(dept=dept.name),
        )
        director.report_to_id = exec_by_code[exec_code].id

    await db.commit()
    return {
        "root": root.name,
        "departments": len(_DEPARTMENTS),
        "execs": len(_EXECS),
        "directors": len(_DIRECTORS),
    }

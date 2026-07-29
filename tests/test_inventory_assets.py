"""资产盘点纯函数测试（无 DB）：skill 覆盖/孤儿 + 悬挂外键判定 + 归属表完整。"""

from __future__ import annotations

from scripts.inventory_assets import OWNERSHIP, dangling_refs, skill_coverage


def test_skill_coverage_orphans() -> None:
    cov = skill_coverage(["collab", "ghost_skill", "", "collab"], ["collab", "deliver"])
    assert cov.orphans == ("ghost_skill",)  # 引用了注册表没有的 → 迁移丢功能
    assert cov.referenced == ("collab", "ghost_skill")  # 去重 + 空串剔除
    assert cov.defined == ("collab", "deliver")


def test_skill_coverage_all_covered() -> None:
    cov = skill_coverage(["collab"], ["collab", "deliver"])
    assert cov.orphans == ()  # 全被注册表覆盖


def test_dangling_refs() -> None:
    existing = ["a", "b"]
    assert dangling_refs(["a", None, "zzz"], existing) == ("zzz",)  # 指向已删专家
    assert dangling_refs([None, None], existing) == ()  # None 引用忽略
    assert dangling_refs(["a"], existing) == ()


def test_ownership_covers_all_asset_classes() -> None:
    assert set(OWNERSHIP) == {"expert", "prompt", "skill_tool", "tool_execution", "workflow"}

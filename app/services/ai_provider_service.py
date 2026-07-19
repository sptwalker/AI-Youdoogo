"""AI 模型卡片管理（迁移 019）：CRUD + 主用互斥 + 启停 + 连通测试 + 同步 factory。

红线：api_key 存本表但 list 脱敏（只回 hint + is_set），审计打码，绝不回显明文。
每次增删改/启停/设主用后由 API 层调 sync_to_factory，把卡片推进 LLM 网关运行时状态。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError
from app.llm import factory
from app.llm.model_tester import test_card
from app.models.ai_provider import TIER_DAILY, TIER_REASONING, VALID_TIERS, AiProvider


def _provider_id(card: AiProvider) -> str:
    """卡片 → factory 注册用 provider_id（稳定、小写、合法字符）。"""
    return f"card_{card.id.hex}"


def _hint(api_key: str) -> str:
    """密钥末 4 位提示（不足则全打码），供 list 显示不泄露明文。"""
    key = (api_key or "").strip()
    if not key:
        return ""
    return f"****{key[-4:]}" if len(key) >= 4 else "****"


def _check_tier(tier: str) -> None:
    if tier not in VALID_TIERS:
        raise AppError(f"tier 仅支持 {'/'.join(VALID_TIERS)}")


async def get_provider(db: AsyncSession, provider_id: uuid.UUID) -> AiProvider:
    card = await db.get(AiProvider, provider_id)
    if card is None or card.is_delete:
        raise AppError("AI 卡片不存在", code=404, status_code=404)
    return card


async def _active_of_tier(db: AsyncSession, tier: str) -> list[AiProvider]:
    """某档位全部 active 卡片（create_time 升序）。"""
    stmt = (
        select(AiProvider)
        .where(
            AiProvider.tier == tier,
            AiProvider.is_active.is_(True),
            AiProvider.is_delete.is_(False),
        )
        .order_by(AiProvider.create_time)
    )
    return list((await db.execute(stmt)).scalars())


async def create(
    db: AsyncSession, *, name: str, tier: str, base_url: str, api_key: str, model: str
) -> AiProvider:
    """新建卡片。该档位首张卡片自动设为主用。"""
    _check_tier(tier)
    first_of_tier = not await _active_of_tier(db, tier)
    card = AiProvider(
        name=name, tier=tier, base_url=base_url.strip(), api_key=api_key.strip(),
        api_key_hint=_hint(api_key), model=model.strip(),
        is_primary=first_of_tier, is_active=True,
    )
    db.add(card)
    await db.commit()
    await db.refresh(card)
    return card


async def update(
    db: AsyncSession,
    provider_id: uuid.UUID,
    *,
    name: str | None = None,
    tier: str | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
    model: str | None = None,
) -> AiProvider:
    """改卡片。api_key 仅在传入非空时更新（空表示不改，保留原 Key）。"""
    card = await get_provider(db, provider_id)
    if name is not None:
        card.name = name
    if tier is not None:
        _check_tier(tier)
        card.tier = tier
    if base_url is not None:
        card.base_url = base_url.strip()
    if model is not None:
        card.model = model.strip()
    if api_key:  # 非空才改；空串=保持原 Key
        card.api_key = api_key.strip()
        card.api_key_hint = _hint(api_key)
    await db.commit()
    await db.refresh(card)
    return card


async def delete(db: AsyncSession, provider_id: uuid.UUID) -> None:
    """软删卡片。若删的是主用卡片，自动把同档另一张 active 卡片提升为主用。"""
    card = await get_provider(db, provider_id)
    card.is_delete = True
    card.is_primary = False
    await db.flush()
    await _promote_if_no_primary(db, card.tier)
    await db.commit()


async def _promote_if_no_primary(db: AsyncSession, tier: str) -> None:
    """确保某档位至少有一张 active 主用卡片：若当前无主用，提升第一张 active。"""
    actives = await _active_of_tier(db, tier)
    if not actives or any(c.is_primary for c in actives):
        return
    actives[0].is_primary = True
    await db.flush()


async def set_primary(db: AsyncSession, provider_id: uuid.UUID) -> AiProvider:
    """把卡片设为该档位主用（同档互斥：其余同档卡片清零）。禁用卡片不可设主用。"""
    card = await get_provider(db, provider_id)
    if not card.is_active:
        raise AppError("禁用中的卡片不能设为主用，请先启用")
    stmt = select(AiProvider).where(
        AiProvider.tier == card.tier, AiProvider.is_delete.is_(False)
    )
    for other in (await db.execute(stmt)).scalars():
        other.is_primary = other.id == card.id
    await db.commit()
    await db.refresh(card)
    return card


async def toggle_active(db: AsyncSession, provider_id: uuid.UUID, active: bool) -> AiProvider:
    """启用/禁用卡片。禁用主用卡片时自动把同档另一张 active 提升为主用。"""
    card = await get_provider(db, provider_id)
    card.is_active = active
    if not active:
        card.is_primary = False
    await db.flush()
    await _promote_if_no_primary(db, card.tier)
    await db.commit()
    await db.refresh(card)
    return card


async def test_provider(db: AsyncSession, provider_id: uuid.UUID) -> dict[str, Any]:
    """连通测试并落 last_test_*，返回 {status, latency_ms, msg}。"""
    card = await get_provider(db, provider_id)
    result = await test_card(card.base_url, card.api_key, card.model)
    card.last_test_status = result["status"]
    card.last_test_latency_ms = result.get("latency_ms")
    card.last_test_msg = result.get("msg", "")[:256]
    card.last_test_at = datetime.now(UTC)
    await db.commit()
    return result


async def test_all(db: AsyncSession) -> list[dict[str, Any]]:
    """逐张测所有未删卡片（禁用卡片跳过测试，回 disabled 状态）。"""
    stmt = select(AiProvider).where(AiProvider.is_delete.is_(False)).order_by(
        AiProvider.tier, AiProvider.create_time
    )
    out: list[dict[str, Any]] = []
    for card in (await db.execute(stmt)).scalars():
        if not card.is_active:
            out.append(
                {"id": str(card.id), "status": "disabled", "latency_ms": None, "msg": "已禁用"}
            )
            continue
        result = await test_card(card.base_url, card.api_key, card.model)
        card.last_test_status = result["status"]
        card.last_test_latency_ms = result.get("latency_ms")
        card.last_test_msg = result.get("msg", "")[:256]
        card.last_test_at = datetime.now(UTC)
        out.append({"id": str(card.id), **result})
    await db.commit()
    return out


async def list_providers(db: AsyncSession) -> list[dict[str, Any]]:
    """卡片列表（api_key 脱敏：只回 hint + is_set）。"""
    stmt = select(AiProvider).where(AiProvider.is_delete.is_(False)).order_by(
        AiProvider.tier, AiProvider.create_time
    )
    return [
        {
            "id": str(c.id), "name": c.name, "tier": c.tier, "base_url": c.base_url,
            "model": c.model, "api_key_hint": c.api_key_hint, "api_key_set": bool(c.api_key),
            "is_primary": c.is_primary, "is_active": c.is_active,
            "last_test_status": c.last_test_status,
            "last_test_at": c.last_test_at.isoformat() if c.last_test_at else None,
            "last_test_latency_ms": c.last_test_latency_ms,
            "last_test_msg": c.last_test_msg,
        }
        for c in (await db.execute(stmt)).scalars()
    ]


async def seed_from_env(db: AsyncSession) -> int:
    """首次部署兜底：库中无任何卡片且 .env 有 DeepSeek 密钥 → 自动建 daily+reasoning 两张卡。

    让全新生产库开箱即 AI 可用（docs/12 缺口1 方案A），避免"无卡片 AI 不可用"卡住首屏。
    幂等:已存在任何卡片则跳过（返回 0）;开发库已手动建卡故为空操作。返回新建卡片数。
    """
    from app.core.config import get_settings

    existing = (
        await db.execute(select(AiProvider).where(AiProvider.is_delete.is_(False)).limit(1))
    ).first()
    if existing is not None:
        return 0  # 已有卡片，不覆盖
    key = (get_settings().deepseek_api_key or "").strip()
    if not key:
        return 0  # 无密钥，无从建卡（部署者需登录后手动建）
    # DeepSeek 一家两档：daily=deepseek-chat，reasoning=deepseek-reasoner
    await create(
        db, name="DeepSeek 日常", tier=TIER_DAILY,
        base_url="https://api.deepseek.com", api_key=key, model="deepseek-chat",
    )
    await create(
        db, name="DeepSeek 推理", tier=TIER_REASONING,
        base_url="https://api.deepseek.com", api_key=key, model="deepseek-reasoner",
    )
    return 2


async def sync_to_factory(db: AsyncSession) -> None:
    """把卡片推进 LLM 网关运行时：注册 active 卡片 + 设各档位主用/候选顺序。

    启动 + 每次卡片变更后调用。禁用/已删卡片不注册；候选顺序主用置顶。
    """
    stmt = select(AiProvider).where(AiProvider.is_delete.is_(False)).order_by(
        AiProvider.create_time
    )
    cards = list((await db.execute(stmt)).scalars())

    factory.clear_card_providers()
    inactive_ids: list[str] = []
    tier_ids: dict[str, list[str]] = {}
    primary_by_tier: dict[str, str] = {}
    for c in cards:
        pid = _provider_id(c)
        if not c.is_active:
            inactive_ids.append(pid)
            continue
        factory.register_custom_provider(pid, c.base_url, api_key=c.api_key, default_model=c.model)
        tier_ids.setdefault(c.tier, [])
        if c.is_primary:
            tier_ids[c.tier].insert(0, pid)  # 主用置顶
            primary_by_tier[c.tier] = pid
        else:
            tier_ids[c.tier].append(pid)
    factory.set_provider_status(inactive_ids, primary_by_tier, tier_ids)

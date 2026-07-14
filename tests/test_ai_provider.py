"""AI 卡片管理单测：CRUD/脱敏/主用互斥/启停/同步 factory/按档取模型（不发真实请求）。"""

import uuid
from collections.abc import AsyncGenerator

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.llm import NoAvailableProviderError, factory, get_llm_for_role, health
from app.models import Base
from app.services import ai_provider_service as svc


@pytest.fixture(autouse=True)
def _reset_factory() -> None:
    """每用例前清空进程内卡片注册 + 状态 + 熔断，避免串扰。"""
    factory.clear_card_providers()
    factory.set_provider_status([], {}, {})
    health.reset()


@pytest.fixture
async def db() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
    await engine.dispose()


async def _mk(
    db: AsyncSession, name: str, tier: str = "daily", key: str = "sk-secret-1234"
) -> uuid.UUID:
    card = await svc.create(
        db, name=name, tier=tier, base_url="https://api.x.com", api_key=key, model="m1"
    )
    return card.id


async def test_first_card_of_tier_is_primary(db: AsyncSession) -> None:
    """某档位首张卡片自动主用；第二张非主用。"""
    a = await _mk(db, "A")
    b = await _mk(db, "B")
    cards = {c["id"]: c for c in await svc.list_providers(db)}
    assert cards[str(a)]["is_primary"] is True
    assert cards[str(b)]["is_primary"] is False


async def test_list_masks_api_key(db: AsyncSession) -> None:
    """list 不回显明文，只回 hint 末4位 + is_set。"""
    await _mk(db, "A", key="sk-abcd-9876")
    row = (await svc.list_providers(db))[0]
    assert "api_key" not in row
    assert row["api_key_set"] is True
    assert row["api_key_hint"] == "****9876"


async def test_set_primary_exclusive_within_tier(db: AsyncSession) -> None:
    """同档设主用互斥；不影响另一档。"""
    a = await _mk(db, "A", "daily")
    b = await _mk(db, "B", "daily")
    r = await _mk(db, "R", "reasoning")
    await svc.set_primary(db, b)
    cards = {c["id"]: c for c in await svc.list_providers(db)}
    assert cards[str(b)]["is_primary"] is True
    assert cards[str(a)]["is_primary"] is False
    assert cards[str(r)]["is_primary"] is True  # 另一档独立，仍是其首张主用


async def test_disable_primary_promotes_sibling(db: AsyncSession) -> None:
    """禁用主用卡片 → 同档另一张 active 自动升主用。"""
    a = await _mk(db, "A", "daily")
    b = await _mk(db, "B", "daily")
    await svc.toggle_active(db, a, False)  # a 是主用
    cards = {c["id"]: c for c in await svc.list_providers(db)}
    assert cards[str(a)]["is_active"] is False
    assert cards[str(a)]["is_primary"] is False
    assert cards[str(b)]["is_primary"] is True


async def test_delete_primary_promotes_sibling(db: AsyncSession) -> None:
    """删主用卡片 → 同档另一张升主用。"""
    a = await _mk(db, "A", "daily")
    b = await _mk(db, "B", "daily")
    await svc.delete(db, a)
    rows = await svc.list_providers(db)
    assert [c["id"] for c in rows] == [str(b)]
    assert rows[0]["is_primary"] is True


async def test_sync_to_factory_registers_active_and_status(db: AsyncSession) -> None:
    """sync 后：active 卡片注册可用、被禁卡片不可用、主用置于档位首位。"""
    a = await _mk(db, "A", "daily")
    b = await _mk(db, "B", "daily")
    await svc.set_primary(db, b)
    await svc.toggle_active(db, a, False)
    await svc.sync_to_factory(db)

    pid_a, pid_b = f"card_{a.hex}", f"card_{b.hex}"
    assert factory.provider_available(pid_b)
    assert not factory.provider_available(pid_a)  # 被禁
    assert factory.providers_for_tier("daily") == [pid_b]


async def test_get_llm_for_role_uses_tier_cards(db: AsyncSession) -> None:
    """建 daily 卡片并 sync 后，default 角色（daily 档）能构出模型，主候选为该卡。"""
    a = await _mk(db, "A", "daily")
    await svc.sync_to_factory(db)
    llm = get_llm_for_role("default")
    assert llm.candidates[0][1] == f"card_{a.hex}"
    assert llm.candidates[0][2] == "m1"


async def test_get_llm_for_role_no_card_raises(db: AsyncSession) -> None:
    """无卡片 → 抛 NoAvailableProviderError（必须先建卡片）。"""
    await svc.sync_to_factory(db)  # 无卡片
    with pytest.raises(NoAvailableProviderError):
        get_llm_for_role("default")


async def test_reasoning_role_picks_reasoning_tier(db: AsyncSession) -> None:
    """meeting_expert（reasoning 档）取 reasoning 卡片，不取 daily 卡片。"""
    await _mk(db, "D", "daily")
    r = await _mk(db, "R", "reasoning")
    await svc.sync_to_factory(db)
    llm = get_llm_for_role("meeting_expert")
    assert [c[1] for c in llm.candidates] == [f"card_{r.hex}"]


async def test_test_provider_persists_status(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """test_provider 打桩：落 last_test_* 状态。"""
    async def _fake(base_url: str, api_key: str, model: str, timeout: int = 20) -> dict:
        return {"status": "ok", "latency_ms": 42, "msg": "连通正常"}

    monkeypatch.setattr(svc, "test_card", _fake)
    a = await _mk(db, "A")
    result = await svc.test_provider(db, a)
    assert result["status"] == "ok"
    row = (await svc.list_providers(db))[0]
    assert row["last_test_status"] == "ok"
    assert row["last_test_latency_ms"] == 42


async def test_invalid_tier_rejected(db: AsyncSession) -> None:
    from app.core.exceptions import AppError

    with pytest.raises(AppError, match="tier"):
        await svc.create(db, name="X", tier="bogus", base_url="u", api_key="k", model="m")

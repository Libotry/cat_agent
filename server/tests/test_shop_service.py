"""Tests for ShopService (U10-U15, U18) and boundary cases."""

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, patch

from sqlalchemy import select, func as sa_func
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from app.core.database import Base
from app.models import Agent, VirtualItem, AgentItem, Job
from app.services.shop_service import shop_service

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def agent(db):
    """Agent(id=1, credits=50)."""
    a = Agent(id=1, name="TestBot", persona="test", credits=50)
    db.add(a)
    await db.commit()
    await db.refresh(a)
    return a


@pytest_asyncio.fixture
async def item(db):
    """VirtualItem(id=1, price=20, avatar_frame)."""
    vi = VirtualItem(id=1, name="金色头像框", item_type="avatar_frame", price=20, description="闪闪发光")
    db.add(vi)
    await db.commit()
    await db.refresh(vi)
    return vi


# ---------------------------------------------------------------------------
# U10: 正常购买扣费
# ---------------------------------------------------------------------------

async def test_purchase_success(db, agent, item):
    result = await shop_service.purchase(agent_id=1, item_id=1, db=db)

    assert result["ok"] is True
    assert result["reason"] == "success"
    assert result["item_name"] == "金色头像框"
    assert result["price"] == 20
    assert result["remaining_credits"] == 30

    # DB verification
    await db.refresh(agent)
    assert agent.credits == 30

    row = (await db.execute(
        select(AgentItem).where(AgentItem.agent_id == 1, AgentItem.item_id == 1)
    )).scalar_one_or_none()
    assert row is not None


# ---------------------------------------------------------------------------
# U11: 余额不足被拒
# ---------------------------------------------------------------------------

async def test_purchase_insufficient_credits(db, item):
    """Agent credits=10 < price=20 -> insufficient_credits."""
    a = Agent(id=2, name="PoorBot", persona="test", credits=10)
    db.add(a)
    await db.commit()

    result = await shop_service.purchase(agent_id=2, item_id=1, db=db)

    assert result["ok"] is False
    assert result["reason"] == "insufficient_credits"

    await db.refresh(a)
    assert a.credits == 10  # unchanged


# ---------------------------------------------------------------------------
# U12: 重复购买被拒
# ---------------------------------------------------------------------------

async def test_purchase_already_owned(db, agent, item):
    """Agent already owns the item -> already_owned."""
    db.add(AgentItem(agent_id=1, item_id=1))
    await db.commit()

    result = await shop_service.purchase(agent_id=1, item_id=1, db=db)

    assert result["ok"] is False
    assert result["reason"] == "already_owned"

    await db.refresh(agent)
    assert agent.credits == 50  # unchanged


# ---------------------------------------------------------------------------
# U13: Agent 物品列表正确
# ---------------------------------------------------------------------------

async def test_get_agent_items(db, agent):
    """Agent owns 2 items -> list returns both with correct fields."""
    vi1 = VirtualItem(id=1, name="金色头像框", item_type="avatar_frame", price=20, description="")
    vi2 = VirtualItem(id=2, name="勤劳之星", item_type="title", price=15, description="")
    db.add_all([vi1, vi2])
    await db.commit()

    db.add_all([AgentItem(agent_id=1, item_id=1), AgentItem(agent_id=1, item_id=2)])
    await db.commit()

    items = await shop_service.get_agent_items(agent_id=1, db=db)

    assert len(items) == 2
    names = {i["name"] for i in items}
    assert names == {"金色头像框", "勤劳之星"}
    for i in items:
        assert "item_id" in i
        assert "item_type" in i
        assert "purchased_at" in i


# ---------------------------------------------------------------------------
# U14: agent_not_found 购买被拒
# ---------------------------------------------------------------------------

async def test_purchase_agent_not_found(db, item):
    """Non-existent agent_id=999 -> agent_not_found."""
    result = await shop_service.purchase(agent_id=999, item_id=1, db=db)

    assert result["ok"] is False
    assert result["reason"] == "agent_not_found"


# ---------------------------------------------------------------------------
# U15: item_not_found 购买被拒
# ---------------------------------------------------------------------------

async def test_purchase_item_not_found(db, agent):
    """Non-existent item_id=999 -> item_not_found."""
    result = await shop_service.purchase(agent_id=1, item_id=999, db=db)

    assert result["ok"] is False
    assert result["reason"] == "item_not_found"


# ---------------------------------------------------------------------------
# U18: seed 幂等性
# ---------------------------------------------------------------------------

async def test_seed_idempotent():
    """seed_jobs_and_items called twice -> no duplicate rows."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    def fake_session():
        return maker()

    with patch("main.async_session", side_effect=fake_session):
        from main import seed_jobs_and_items
        await seed_jobs_and_items()
        await seed_jobs_and_items()  # second call

    async with maker() as session:
        job_count = (await session.execute(select(sa_func.count(Job.id)))).scalar()
        item_count = (await session.execute(select(sa_func.count(VirtualItem.id)))).scalar()

    assert job_count == 5
    assert item_count == 5

    await engine.dispose()


# ---------------------------------------------------------------------------
# Extra: credits 恰好等于 price 边界
# ---------------------------------------------------------------------------

async def test_purchase_exact_credits(db, item):
    """credits == price -> purchase succeeds, remaining_credits == 0."""
    a = Agent(id=3, name="ExactBot", persona="test", credits=20)
    db.add(a)
    await db.commit()

    result = await shop_service.purchase(agent_id=3, item_id=1, db=db)

    assert result["ok"] is True
    assert result["remaining_credits"] == 0

    await db.refresh(a)
    assert a.credits == 0

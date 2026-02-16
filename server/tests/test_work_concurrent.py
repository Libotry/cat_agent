"""
M3 并发测试 (C1-C6)
对应测试用例文档: docs/tests/TEST-M3-城市经济.md
"""

import asyncio

import pytest
import pytest_asyncio
from sqlalchemy import event, select, func as sa_func, text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from app.core.database import Base
from app.models import Agent, Job, CheckIn, VirtualItem, AgentItem
from app.services.work_service import WorkService
from app.services.shop_service import ShopService

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Fixtures: 使用真实 SQLite 文件 + WAL 模式，支持多连接并发
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def db_factory(tmp_path):
    """
    返回 (engine, session_factory)。
    使用文件数据库而非 :memory:，因为并发测试需要多个连接看到彼此的 commit。
    通过 connect + begin 事件实现 BEGIN IMMEDIATE，确保并发事务串行化。
    """
    db_path = str(tmp_path / "test_concurrent.db").replace("\\", "/")
    url = f"sqlite+aiosqlite:///{db_path}"

    engine = create_async_engine(url, echo=False)

    @event.listens_for(engine.sync_engine, "connect")
    def _set_pragma(dbapi_conn, _rec):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA busy_timeout=30000")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.close()
        # autocommit 模式，让 SQLAlchemy 通过 begin 事件控制事务
        dbapi_conn.isolation_level = None

    @event.listens_for(engine.sync_engine, "begin")
    def _do_begin(dbapi_conn):
        dbapi_conn.exec_driver_sql("BEGIN IMMEDIATE")

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    yield engine, factory
    await engine.dispose()


# ---------------------------------------------------------------------------
# C1: 10 Agent 并发打卡 max_workers=5 — 恰好 5 成功 5 被拒
# ---------------------------------------------------------------------------

async def test_concurrent_checkin_max_workers(db_factory):
    engine, make_session = db_factory

    # Setup: 1 job (max_workers=5) + 10 agents
    async with make_session() as s:
        job = Job(id=1, title="矿工", description="挖矿", daily_reward=8, max_workers=5)
        s.add(job)
        for i in range(1, 11):
            s.add(Agent(id=i, name=f"Agent{i}", persona="test", credits=100))
        await s.commit()

    ws = WorkService()

    async def do_checkin(agent_id: int):
        async with make_session() as s:
            result = await ws.check_in(agent_id, 1, s)
            await s.commit()
            return result

    results = await asyncio.gather(*[do_checkin(i) for i in range(1, 11)])

    ok_count = sum(1 for r in results if r["ok"])
    fail_count = sum(1 for r in results if not r["ok"] and r["reason"] == "job_full")
    assert ok_count == 5, f"Expected 5 ok, got {ok_count}: {results}"
    assert fail_count == 5, f"Expected 5 job_full, got {fail_count}: {results}"

    # DB 验证: checkins 表恰好 5 条
    async with make_session() as s:
        cnt = (await s.execute(
            select(sa_func.count(CheckIn.id)).where(CheckIn.job_id == 1)
        )).scalar()
        assert cnt == 5


# ---------------------------------------------------------------------------
# C2: 同一 Agent 并发打卡 2 次 — 仅 1 成功
# ---------------------------------------------------------------------------

async def test_concurrent_checkin_same_agent(db_factory):
    engine, make_session = db_factory

    async with make_session() as s:
        s.add(Job(id=1, title="矿工", description="挖矿", daily_reward=8, max_workers=5))
        s.add(Agent(id=1, name="Agent1", persona="test", credits=100))
        await s.commit()

    ws = WorkService()

    async def do_checkin():
        async with make_session() as s:
            result = await ws.check_in(1, 1, s)
            await s.commit()
            return result

    results = await asyncio.gather(do_checkin(), do_checkin())

    ok_count = sum(1 for r in results if r["ok"])
    dup_count = sum(1 for r in results if not r["ok"] and r["reason"] == "already_checked_in")
    assert ok_count == 1, f"Expected 1 ok, got {ok_count}: {results}"
    assert dup_count == 1, f"Expected 1 already_checked_in, got {dup_count}: {results}"

    # DB 验证
    async with make_session() as s:
        cnt = (await s.execute(
            select(sa_func.count(CheckIn.id)).where(CheckIn.agent_id == 1)
        )).scalar()
        assert cnt == 1


# ---------------------------------------------------------------------------
# C3: 2 不同 Agent 并发购买同一商品 — 各自成功
# ---------------------------------------------------------------------------

async def test_concurrent_purchase_different_agents(db_factory):
    engine, make_session = db_factory

    async with make_session() as s:
        s.add(Agent(id=1, name="Agent1", persona="test", credits=50))
        s.add(Agent(id=2, name="Agent2", persona="test", credits=50))
        s.add(VirtualItem(id=1, name="金色头像框", description="", item_type="avatar_frame", price=20))
        await s.commit()

    ss = ShopService()

    async def do_purchase(agent_id: int):
        async with make_session() as s:
            result = await ss.purchase(agent_id, 1, s)
            await s.commit()
            return result

    results = await asyncio.gather(do_purchase(1), do_purchase(2))

    ok_count = sum(1 for r in results if r["ok"])
    assert ok_count == 2, f"Expected 2 ok, got {ok_count}: {results}"

    # DB 验证: AgentItem 2 条, 各 Agent credits 减少 20
    async with make_session() as s:
        cnt = (await s.execute(
            select(sa_func.count(AgentItem.id))
        )).scalar()
        assert cnt == 2

        a1 = await s.get(Agent, 1)
        a2 = await s.get(Agent, 2)
        assert a1.credits == 30, f"Agent1 credits={a1.credits}, expected 30"
        assert a2.credits == 30, f"Agent2 credits={a2.credits}, expected 30"


# ---------------------------------------------------------------------------
# C4: 同一 Agent 并发购买同一商品 — 仅 1 成功
# ---------------------------------------------------------------------------

async def test_concurrent_purchase_same_agent_same_item(db_factory):
    engine, make_session = db_factory

    async with make_session() as s:
        s.add(Agent(id=1, name="Agent1", persona="test", credits=100))
        s.add(VirtualItem(id=1, name="金色头像框", description="", item_type="avatar_frame", price=20))
        await s.commit()

    ss = ShopService()

    async def do_purchase():
        async with make_session() as s:
            result = await ss.purchase(1, 1, s)
            try:
                await s.commit()
            except Exception:
                await s.rollback()
                return {"ok": False, "reason": "already_owned"}
            return result

    results = await asyncio.gather(do_purchase(), do_purchase())

    ok_count = sum(1 for r in results if r["ok"])
    dup_count = sum(1 for r in results if not r["ok"] and r["reason"] == "already_owned")
    assert ok_count == 1, f"Expected 1 ok, got {ok_count}: {results}"
    assert dup_count == 1, f"Expected 1 already_owned, got {dup_count}: {results}"

    # DB 验证: AgentItem 恰好 1 条, credits 仅扣一次
    async with make_session() as s:
        cnt = (await s.execute(
            select(sa_func.count(AgentItem.id)).where(
                AgentItem.agent_id == 1, AgentItem.item_id == 1
            )
        )).scalar()
        assert cnt == 1

        a = await s.get(Agent, 1)
        assert a.credits == 80, f"Agent credits={a.credits}, expected 80"


# ---------------------------------------------------------------------------
# C5: 同一 Agent 并发购买两个不同商品（总价超余额）— credits >= 0
# ---------------------------------------------------------------------------

async def test_concurrent_purchase_different_items_insufficient(db_factory):
    engine, make_session = db_factory

    async with make_session() as s:
        s.add(Agent(id=1, name="Agent1", persona="test", credits=30))
        s.add(VirtualItem(id=1, name="金色头像框", description="", item_type="avatar_frame", price=20))
        s.add(VirtualItem(id=2, name="勤劳之星", description="", item_type="title", price=25))
        await s.commit()

    ss = ShopService()

    async def do_purchase(item_id: int):
        async with make_session() as s:
            result = await ss.purchase(1, item_id, s)
            try:
                await s.commit()
            except Exception:
                await s.rollback()
                return {"ok": False, "reason": "insufficient_credits"}
            return result

    results = await asyncio.gather(do_purchase(1), do_purchase(2))

    ok_count = sum(1 for r in results if r["ok"])
    assert ok_count <= 1, f"Expected at most 1 ok, got {ok_count}: {results}"

    # 核心断言: credits >= 0（CHECK 约束兜底）
    async with make_session() as s:
        a = await s.get(Agent, 1)
        assert a.credits >= 0, f"Agent credits={a.credits}, must be >= 0"


# ---------------------------------------------------------------------------
# C6: max_workers=0 并发打卡 10 人 — 全部成功
# ---------------------------------------------------------------------------

async def test_concurrent_checkin_unlimited_job(db_factory):
    engine, make_session = db_factory

    async with make_session() as s:
        s.add(Job(id=1, title="自由职业", description="无限制", daily_reward=5, max_workers=0))
        for i in range(1, 11):
            s.add(Agent(id=i, name=f"Agent{i}", persona="test", credits=100))
        await s.commit()

    ws = WorkService()

    async def do_checkin(agent_id: int):
        async with make_session() as s:
            result = await ws.check_in(agent_id, 1, s)
            await s.commit()
            return result

    results = await asyncio.gather(*[do_checkin(i) for i in range(1, 11)])

    ok_count = sum(1 for r in results if r["ok"])
    assert ok_count == 10, f"Expected 10 ok, got {ok_count}: {results}"

    # DB 验证: checkins 10 条, 每个 agent credits += 5
    async with make_session() as s:
        cnt = (await s.execute(
            select(sa_func.count(CheckIn.id)).where(CheckIn.job_id == 1)
        )).scalar()
        assert cnt == 10

        for i in range(1, 11):
            a = await s.get(Agent, i)
            assert a.credits == 105, f"Agent{i} credits={a.credits}, expected 105"

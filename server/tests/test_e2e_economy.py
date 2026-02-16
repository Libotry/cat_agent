"""M3 E2E tests: work + shop economic loop via real HTTP endpoints."""

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy import text

from app.core.database import Base, engine, async_session
from app.models import Agent, Job, VirtualItem

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    """Create tables + seed, tear down after each test."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    # seed minimal data
    async with async_session() as db:
        db.add(Agent(id=0, name="Human", persona="human", model="none", status="idle"))
        db.add(Agent(id=99, name="E2EBot", persona="test", model="none", credits=0))
        db.add(Job(id=1, title="矿工", description="挖矿", daily_reward=10, max_workers=5))
        db.add(VirtualItem(id=1, name="金框", item_type="avatar_frame", price=8, description="test"))
        db.add(VirtualItem(id=2, name="贵框", item_type="avatar_frame", price=999, description="expensive"))
        await db.commit()

    yield

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def client():
    from main import app
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# ---------- E1: 打卡 → 余额增加 ----------

async def test_e2e_checkin_credits_increase(client: AsyncClient):
    # 初始 credits=0
    r = await client.get("/api/agents/99")
    assert r.status_code == 200
    initial_credits = r.json()["credits"]

    # 打卡
    r = await client.post("/api/work/jobs/1/checkin", json={"agent_id": 99})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["reward"] == 10

    # 验证 credits 增加
    r = await client.get("/api/agents/99")
    assert r.json()["credits"] == initial_credits + 10


# ---------- E2: 打卡 → 购买 → 余额减少 + 物品出现 ----------

async def test_e2e_checkin_then_purchase(client: AsyncClient):
    # credits=0, 先打卡赚 10
    r = await client.post("/api/work/jobs/1/checkin", json={"agent_id": 99})
    assert r.json()["ok"] is True

    # 购买 price=8 的商品
    r = await client.post("/api/shop/purchase", json={"agent_id": 99, "item_id": 1})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["remaining_credits"] == 2  # 10 - 8

    # 验证物品出现
    r = await client.get("/api/shop/agents/99/items")
    items = r.json()
    assert len(items) == 1
    assert items[0]["item_id"] == 1


# ---------- E3: 余额不足 → 打卡赚钱 → 再次购买成功 ----------

async def test_e2e_insufficient_then_earn_then_buy(client: AsyncClient):
    # credits=0, 直接购买 → 失败
    r = await client.post("/api/shop/purchase", json={"agent_id": 99, "item_id": 1})
    body = r.json()
    assert body["ok"] is False
    assert body["reason"] == "insufficient_credits"

    # 打卡赚钱
    r = await client.post("/api/work/jobs/1/checkin", json={"agent_id": 99})
    assert r.json()["ok"] is True

    # 再次购买 → 成功
    r = await client.post("/api/shop/purchase", json={"agent_id": 99, "item_id": 1})
    body = r.json()
    assert body["ok"] is True
    assert body["remaining_credits"] == 2


# ---------- E4: 打卡 WebSocket 事件推送 ----------

async def test_e2e_checkin_websocket_event(client: AsyncClient):
    from starlette.testclient import TestClient
    from main import app

    # 用同步 TestClient 做 WebSocket（starlette 标准方式）
    with TestClient(app) as sync_client:
        with sync_client.websocket_connect("/api/ws/0") as ws:
            # 收到 online 事件
            _online = ws.receive_json()

            # 打卡（通过 HTTP）
            r = await client.post("/api/work/jobs/1/checkin", json={"agent_id": 99})
            assert r.json()["ok"] is True

            # 从 WebSocket 收到 system_event
            event = ws.receive_json()
            assert event["type"] == "system_event"
            assert event["data"]["event"] == "checkin"
            assert event["data"]["agent_id"] == 99


# ---------- E5: 购买 WebSocket 事件推送 ----------

async def test_e2e_purchase_websocket_event(client: AsyncClient):
    # 先给 agent 加钱
    async with async_session() as db:
        agent = await db.get(Agent, 99)
        agent.credits = 100
        await db.commit()

    from starlette.testclient import TestClient
    from main import app

    with TestClient(app) as sync_client:
        with sync_client.websocket_connect("/api/ws/0") as ws:
            _online = ws.receive_json()

            r = await client.post("/api/shop/purchase", json={"agent_id": 99, "item_id": 1})
            assert r.json()["ok"] is True

            event = ws.receive_json()
            assert event["type"] == "system_event"
            assert event["data"]["event"] == "purchase"
            assert event["data"]["agent_id"] == 99


# ---------- E6: WebSocket 事件后查询 API 数据一致 ----------

async def test_e2e_websocket_then_api_consistency(client: AsyncClient):
    # 打卡
    r = await client.post("/api/work/jobs/1/checkin", json={"agent_id": 99})
    assert r.json()["ok"] is True

    # commit 先于 broadcast，所以此时 API 查询应该已经反映变化
    r = await client.get("/api/agents/99")
    assert r.json()["credits"] == 10  # 0 + 10

    r = await client.get("/api/work/agents/99/today")
    assert r.status_code == 200
    body = r.json()
    assert body is not None
    assert body["job_id"] == 1
    assert body["reward"] == 10

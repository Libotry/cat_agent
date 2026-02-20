"""M6.2-P2 E2E: SOUL 深度人格 — 通过 API 端到端验证

覆盖场景：
E1. 创建 Agent 时带 personality_json，GET 返回清洗后的数据
E2. 创建 Agent 时 personality_json 超限字段被截断
E3. 创建 Agent 时 personality_json 无效 → 静默忽略，personality_json=null
E4. PUT 更新 personality_json，GET 返回新值
E5. PUT 清除 personality_json（设为 null），GET 返回 null
E6. 创建 Agent 不带 personality_json，GET 返回 null
E7. personality_json 含 extra 字段 → 被 strip
"""
import pytest
from httpx import AsyncClient, ASGITransport
from app.core.database import engine, Base
from main import app, ensure_human_agent


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(autouse=True)
async def setup_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    await ensure_human_agent()
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


SOUL_FULL = {
    "values": ["正义", "勇气"],
    "speaking_style": "冷静理性",
    "knowledge_domains": ["历史", "哲学"],
    "emotional_tendency": "乐观",
    "catchphrases": ["嗯哼", "有意思"],
    "relationships": {"Alice": "友好"},
    "taboos": ["说谎"],
}


# --- E1: 创建带 SOUL 的 Agent ---
@pytest.mark.anyio
async def test_e1_create_agent_with_soul(client):
    r = await client.post("/api/agents/", json={
        "name": "SoulBot",
        "persona": "测试人格",
        "personality_json": SOUL_FULL,
    })
    assert r.status_code == 201
    data = r.json()
    pj = data["personality_json"]
    assert pj is not None
    assert pj["values"] == ["正义", "勇气"]
    assert pj["speaking_style"] == "冷静理性"
    assert pj["catchphrases"] == ["嗯哼", "有意思"]
    assert pj["relationships"] == {"Alice": "友好"}
    assert pj["taboos"] == ["说谎"]

    # GET 也能读到
    r2 = await client.get(f"/api/agents/{data['id']}")
    assert r2.json()["personality_json"] == pj


# --- E2: 超限截断 ---
@pytest.mark.anyio
async def test_e2_create_agent_soul_truncated(client):
    r = await client.post("/api/agents/", json={
        "name": "TruncBot",
        "persona": "test",
        "personality_json": {
            "values": ["a", "b", "c", "d", "e", "f", "g"],  # 7 → 截断到 5
            "catchphrases": ["x", "y", "z", "w"],  # 4 → 截断到 3
        },
    })
    assert r.status_code == 201
    pj = r.json()["personality_json"]
    assert len(pj["values"]) == 5
    assert len(pj["catchphrases"]) == 3


# --- E3: 无效 personality_json 静默忽略 ---
@pytest.mark.anyio
async def test_e3_create_agent_invalid_soul_ignored(client):
    r = await client.post("/api/agents/", json={
        "name": "BadSoul",
        "persona": "test",
        "personality_json": {"values": "not a list"},
    })
    assert r.status_code == 201
    assert r.json()["personality_json"] is None


# --- E4: PUT 更新 personality_json ---
@pytest.mark.anyio
async def test_e4_update_personality_json(client):
    cr = await client.post("/api/agents/", json={
        "name": "UpdateBot",
        "persona": "test",
    })
    aid = cr.json()["id"]
    assert cr.json()["personality_json"] is None

    # 更新
    r = await client.put(f"/api/agents/{aid}", json={
        "personality_json": {"values": ["善良"], "speaking_style": "温柔"},
    })
    assert r.status_code == 200
    pj = r.json()["personality_json"]
    assert pj["values"] == ["善良"]
    assert pj["speaking_style"] == "温柔"

    # GET 确认持久化
    r2 = await client.get(f"/api/agents/{aid}")
    assert r2.json()["personality_json"] == pj


# --- E5: PUT 清除 personality_json ---
@pytest.mark.anyio
async def test_e5_clear_personality_json(client):
    cr = await client.post("/api/agents/", json={
        "name": "ClearBot",
        "persona": "test",
        "personality_json": SOUL_FULL,
    })
    aid = cr.json()["id"]
    assert cr.json()["personality_json"] is not None

    # 设为 null
    r = await client.put(f"/api/agents/{aid}", json={
        "personality_json": None,
    })
    assert r.status_code == 200
    assert r.json()["personality_json"] is None


# --- E6: 不带 personality_json 创建 ---
@pytest.mark.anyio
async def test_e6_create_without_soul(client):
    r = await client.post("/api/agents/", json={
        "name": "PlainBot",
        "persona": "普通人格",
    })
    assert r.status_code == 201
    assert r.json()["personality_json"] is None


# --- E7: extra 字段被 strip ---
@pytest.mark.anyio
async def test_e7_extra_fields_stripped(client):
    r = await client.post("/api/agents/", json={
        "name": "ExtraBot",
        "persona": "test",
        "personality_json": {
            "values": ["ok"],
            "bogus_field": "should disappear",
            "another_unknown": 123,
        },
    })
    assert r.status_code == 201
    pj = r.json()["personality_json"]
    assert pj is not None
    assert "bogus_field" not in pj
    assert "another_unknown" not in pj
    assert pj["values"] == ["ok"]

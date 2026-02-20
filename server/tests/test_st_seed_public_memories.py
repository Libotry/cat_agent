"""M6.2-P4 系统测试：公共记忆种子数据端到端验证"""
import json
import os
from unittest.mock import AsyncMock, patch

import numpy as np
import pytest
import pytest_asyncio
from sqlalchemy import select, func as sa_func

from app.models import Memory, MemoryType


SEED_DATA_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "public_memories.json")


def _fake_embedding_blob():
    """生成一个非全零的 mock embedding blob"""
    vec = np.random.rand(1024).astype(np.float32)
    return vec.tobytes()


async def _realistic_upsert(memory_id, agent_id, content, db):
    """模拟真实 upsert：写入非零 embedding blob"""
    mem = await db.get(Memory, memory_id)
    if mem is None:
        raise ValueError(f"Memory {memory_id} not found")
    mem.embedding = _fake_embedding_blob()


# ---------------------------------------------------------------------------
# ST-1: 完整种子填充 + embedding 非全零（AC-1 + AC-3）
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_st_seed_full_with_embeddings(db):
    """种子数据全部插入且 embedding 非全零"""
    from main import seed_public_memories

    with patch("main.async_session") as mock_session_ctx, \
         patch("main.upsert_memory", side_effect=_realistic_upsert):
        mock_session_ctx.return_value.__aenter__ = AsyncMock(return_value=db)
        mock_session_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
        await seed_public_memories()

    with open(SEED_DATA_PATH, "r", encoding="utf-8") as f:
        total = len(json.load(f))

    rows = (await db.execute(
        select(Memory).where(Memory.memory_type == MemoryType.PUBLIC)
    )).scalars().all()

    # AC-1: ≥10 条
    assert len(rows) >= 10
    assert len(rows) == total

    # AC-3: embedding 非全零
    for mem in rows:
        assert mem.embedding is not None, f"记忆 '{mem.content[:20]}' 缺少 embedding"
        vec = np.frombuffer(mem.embedding, dtype=np.float32)
        assert np.linalg.norm(vec) > 1e-6, f"记忆 '{mem.content[:20]}' embedding 为全零"


# ---------------------------------------------------------------------------
# ST-2: 幂等 + 自愈完整流程（AC-4 + AC-5 联合）
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_st_idempotent_and_heal(db):
    """首次部分失败 → 二次补全 → 三次跳过"""
    from main import seed_public_memories

    call_count = 0

    async def flaky_then_ok(memory_id, agent_id, content, session):
        nonlocal call_count
        call_count += 1
        if call_count == 3:
            raise RuntimeError("模拟 API 超时")
        await _realistic_upsert(memory_id, agent_id, content, session)

    # 第一次：第 3 条失败
    with patch("main.async_session") as mock_ctx, \
         patch("main.upsert_memory", side_effect=flaky_then_ok):
        mock_ctx.return_value.__aenter__ = AsyncMock(return_value=db)
        mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
        await seed_public_memories()

    with open(SEED_DATA_PATH, "r", encoding="utf-8") as f:
        total = len(json.load(f))

    count_1 = (await db.execute(
        select(sa_func.count(Memory.id)).where(Memory.memory_type == MemoryType.PUBLIC)
    )).scalar()
    assert count_1 == total - 1, f"首次应插入 {total - 1} 条，实际 {count_1}"

    # 第二次：全部成功，补全 1 条
    with patch("main.async_session") as mock_ctx, \
         patch("main.upsert_memory", side_effect=_realistic_upsert):
        mock_ctx.return_value.__aenter__ = AsyncMock(return_value=db)
        mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
        await seed_public_memories()

    count_2 = (await db.execute(
        select(sa_func.count(Memory.id)).where(Memory.memory_type == MemoryType.PUBLIC)
    )).scalar()
    assert count_2 == total, f"二次应补全到 {total} 条，实际 {count_2}"

    # 第三次：全部已存在，跳过
    with patch("main.async_session") as mock_ctx, \
         patch("main.upsert_memory", new_callable=AsyncMock) as mock_upsert:
        mock_ctx.return_value.__aenter__ = AsyncMock(return_value=db)
        mock_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
        await seed_public_memories()

    count_3 = (await db.execute(
        select(sa_func.count(Memory.id)).where(Memory.memory_type == MemoryType.PUBLIC)
    )).scalar()
    assert count_3 == total, "三次调用不应新增记录"
    mock_upsert.assert_not_awaited()


# ---------------------------------------------------------------------------
# ST-3: search 召回公共记忆（AC-2 端到端）
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_st_search_recalls_public_memory(db):
    """Agent 搜索时能召回公共记忆"""
    from app.services.memory_service import memory_service

    # 插入一条带 embedding 的公共记忆
    mem = Memory(agent_id=None, memory_type=MemoryType.PUBLIC, content="长安城经济以信用点为通用货币")
    db.add(mem)
    await db.flush()
    mem.embedding = _fake_embedding_blob()
    await db.commit()
    await db.refresh(mem)

    # mock search_memories 返回该条
    mock_results = [{"memory_id": mem.id, "text": mem.content, "_distance": 0.05}]
    with patch("app.services.memory_service.vector_store.search_memories",
               new_callable=AsyncMock, return_value=mock_results):
        results = await memory_service.search(1, "信用点", db=db)

    assert len(results) == 1
    assert results[0].agent_id is None
    assert results[0].memory_type == MemoryType.PUBLIC
    assert "信用点" in results[0].content

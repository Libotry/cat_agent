"""M6.2-P4 公共记忆种子数据单元测试"""
import json
import os
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import select, func as sa_func

from app.models import Memory, MemoryType


SEED_DATA_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "public_memories.json")


# ---------------------------------------------------------------------------
# AC-1: 服务启动后公共记忆表有 ≥10 条种子数据
# ---------------------------------------------------------------------------
class TestSeedPublicMemories:

    @pytest.mark.asyncio
    async def test_seed_inserts_all_records(self, db):
        """种子数据全部插入成功（mock embedding）"""
        from main import seed_public_memories

        with open(SEED_DATA_PATH, "r", encoding="utf-8") as f:
            seeds = json.load(f)

        with patch("main.async_session") as mock_session_ctx, \
             patch("main.upsert_memory", new_callable=AsyncMock) as mock_upsert:
            mock_session_ctx.return_value.__aenter__ = AsyncMock(return_value=db)
            mock_session_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

            await seed_public_memories()

        count_result = await db.execute(
            select(sa_func.count(Memory.id)).where(Memory.memory_type == MemoryType.PUBLIC)
        )
        count = count_result.scalar()
        assert count >= 10, f"期望 ≥10 条公共记忆，实际 {count}"
        assert count == len(seeds), f"期望 {len(seeds)} 条，实际 {count}"
        assert mock_upsert.await_count == len(seeds)

    @pytest.mark.asyncio
    async def test_seed_memory_fields(self, db):
        """每条种子记忆的字段正确：agent_id=None, memory_type=PUBLIC"""
        from main import seed_public_memories

        with patch("main.async_session") as mock_session_ctx, \
             patch("main.upsert_memory", new_callable=AsyncMock):
            mock_session_ctx.return_value.__aenter__ = AsyncMock(return_value=db)
            mock_session_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

            await seed_public_memories()

        rows = (await db.execute(
            select(Memory).where(Memory.memory_type == MemoryType.PUBLIC)
        )).scalars().all()

        for mem in rows:
            assert mem.agent_id is None, "公共记忆 agent_id 应为 None"
            assert mem.memory_type == MemoryType.PUBLIC
            assert len(mem.content) > 0

    # ---------------------------------------------------------------------------
    # AC-4: 重复启动不会重复插入
    # ---------------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_seed_idempotent(self, db):
        """已有公共记忆时跳过，不重复插入"""
        from main import seed_public_memories

        # 第一次填充
        with patch("main.async_session") as mock_session_ctx, \
             patch("main.upsert_memory", new_callable=AsyncMock):
            mock_session_ctx.return_value.__aenter__ = AsyncMock(return_value=db)
            mock_session_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
            await seed_public_memories()

        count_after_first = (await db.execute(
            select(sa_func.count(Memory.id)).where(Memory.memory_type == MemoryType.PUBLIC)
        )).scalar()

        # 第二次填充
        with patch("main.async_session") as mock_session_ctx, \
             patch("main.upsert_memory", new_callable=AsyncMock) as mock_upsert:
            mock_session_ctx.return_value.__aenter__ = AsyncMock(return_value=db)
            mock_session_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
            await seed_public_memories()

        count_after_second = (await db.execute(
            select(sa_func.count(Memory.id)).where(Memory.memory_type == MemoryType.PUBLIC)
        )).scalar()

        assert count_after_second == count_after_first, "重复调用不应插入新记录"
        mock_upsert.assert_not_awaited()

    # ---------------------------------------------------------------------------
    # AC-5: 单条 embedding 失败时跳过该条，不阻塞
    # ---------------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_seed_skips_on_embedding_failure(self, db):
        """部分 embedding 失败时跳过失败条目，其余正常插入"""
        from main import seed_public_memories

        call_count = 0

        async def flaky_upsert(memory_id, agent_id, content, session):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise RuntimeError("Embedding API 超时")

        with patch("main.async_session") as mock_session_ctx, \
             patch("main.upsert_memory", side_effect=flaky_upsert):
            mock_session_ctx.return_value.__aenter__ = AsyncMock(return_value=db)
            mock_session_ctx.return_value.__aexit__ = AsyncMock(return_value=False)

            # 不应抛异常
            await seed_public_memories()

        with open(SEED_DATA_PATH, "r", encoding="utf-8") as f:
            total = len(json.load(f))

        count = (await db.execute(
            select(sa_func.count(Memory.id)).where(Memory.memory_type == MemoryType.PUBLIC)
        )).scalar()

        # 失败的那条被删除，其余成功
        assert count == total - 1, f"期望 {total - 1} 条，实际 {count}"

    # ---------------------------------------------------------------------------
    # P1-3 修复验证：部分失败后重启能补全缺失条目
    # ---------------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_seed_heals_after_partial_failure(self, db):
        """首次部分失败后，二次调用能补全缺失条目"""
        from main import seed_public_memories

        call_count = 0

        async def flaky_upsert(memory_id, agent_id, content, session):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise RuntimeError("Embedding API 超时")

        # 第一次：第 2 条失败
        with patch("main.async_session") as mock_session_ctx, \
             patch("main.upsert_memory", side_effect=flaky_upsert):
            mock_session_ctx.return_value.__aenter__ = AsyncMock(return_value=db)
            mock_session_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
            await seed_public_memories()

        with open(SEED_DATA_PATH, "r", encoding="utf-8") as f:
            total = len(json.load(f))

        count_after_first = (await db.execute(
            select(sa_func.count(Memory.id)).where(Memory.memory_type == MemoryType.PUBLIC)
        )).scalar()
        assert count_after_first == total - 1

        # 第二次：全部成功，应补全缺失的 1 条
        with patch("main.async_session") as mock_session_ctx, \
             patch("main.upsert_memory", new_callable=AsyncMock) as mock_upsert:
            mock_session_ctx.return_value.__aenter__ = AsyncMock(return_value=db)
            mock_session_ctx.return_value.__aexit__ = AsyncMock(return_value=False)
            await seed_public_memories()

        count_after_second = (await db.execute(
            select(sa_func.count(Memory.id)).where(Memory.memory_type == MemoryType.PUBLIC)
        )).scalar()
        assert count_after_second == total, f"期望补全到 {total} 条，实际 {count_after_second}"
        mock_upsert.assert_awaited_once()  # 只补了 1 条

    # ---------------------------------------------------------------------------
    # AC-2: search 包含公共记忆（复用 memory_service 已有测试模式）
    # ---------------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_search_includes_public_memories(self, db):
        """向量检索返回公共记忆时，search 能正确返回"""
        from app.services.memory_service import memory_service

        # 插入一条公共记忆
        pub_mem = Memory(agent_id=None, memory_type=MemoryType.PUBLIC, content="长安城规则")
        db.add(pub_mem)
        await db.commit()
        await db.refresh(pub_mem)

        mock_results = [{"memory_id": pub_mem.id, "text": "长安城规则", "_distance": 0.05}]
        with patch("app.services.memory_service.vector_store.search_memories",
                    new_callable=AsyncMock, return_value=mock_results):
            results = await memory_service.search(1, "长安城", db=db)

        assert len(results) == 1
        assert results[0].id == pub_mem.id
        assert results[0].memory_type == MemoryType.PUBLIC
        assert results[0].agent_id is None


# ---------------------------------------------------------------------------
# 种子数据文件校验
# ---------------------------------------------------------------------------
class TestSeedDataFile:

    def test_json_file_exists(self):
        """种子数据 JSON 文件存在"""
        assert os.path.exists(SEED_DATA_PATH), f"种子数据文件不存在: {SEED_DATA_PATH}"

    def test_json_valid_and_has_enough_entries(self):
        """JSON 格式合法且 ≥10 条"""
        with open(SEED_DATA_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert isinstance(data, list)
        assert len(data) >= 10, f"种子数据不足 10 条: {len(data)}"

    def test_each_entry_has_content(self):
        """每条记录都有非空 content 字段"""
        with open(SEED_DATA_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        for i, item in enumerate(data):
            assert "content" in item, f"第 {i} 条缺少 content 字段"
            assert isinstance(item["content"], str) and len(item["content"].strip()) >= 5, \
                f"第 {i} 条 content 过短或为空"

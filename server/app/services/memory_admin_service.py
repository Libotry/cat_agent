"""记忆管理服务 — 供 REST API 使用的查询/统计功能"""
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from ..models import Memory, MemoryReference


async def list_memories(
    agent_id: int | None, memory_type: str | None,
    page: int, page_size: int, db: AsyncSession,
) -> dict:
    """分页查询记忆列表"""
    q = select(Memory)
    if agent_id is not None:
        q = q.where(Memory.agent_id == agent_id)
    if memory_type is not None:
        q = q.where(Memory.memory_type == memory_type)
    q = q.order_by(Memory.created_at.desc())

    # 总数
    count_q = select(func.count()).select_from(q.subquery())
    total = (await db.execute(count_q)).scalar() or 0

    # 分页
    q = q.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(q)
    items = [
        {
            "id": m.id, "agent_id": m.agent_id,
            "memory_type": m.memory_type, "content": m.content,
            "access_count": m.access_count,
            "expires_at": str(m.expires_at) if m.expires_at else None,
            "created_at": str(m.created_at),
        }
        for m in result.scalars().all()
    ]
    return {"total": total, "page": page, "page_size": page_size, "items": items}


async def get_memory_detail(memory_id: int, db: AsyncSession) -> dict | None:
    """获取单条记忆详情"""
    m = await db.get(Memory, memory_id)
    if not m:
        return None
    return {
        "id": m.id, "agent_id": m.agent_id,
        "memory_type": m.memory_type, "content": m.content,
        "access_count": m.access_count,
        "expires_at": str(m.expires_at) if m.expires_at else None,
        "created_at": str(m.created_at),
    }


async def get_message_memory_refs(message_id: int, db: AsyncSession) -> list[dict]:
    """获取某条消息引用的记忆列表"""
    result = await db.execute(
        select(MemoryReference, Memory)
        .join(Memory, MemoryReference.memory_id == Memory.id)
        .where(MemoryReference.message_id == message_id)
    )
    return [
        {
            "memory_id": ref.memory_id,
            "content": mem.content,
            "memory_type": mem.memory_type,
            "created_at": str(ref.created_at),
        }
        for ref, mem in result.all()
    ]


async def get_agent_memory_stats(agent_id: int, db: AsyncSession) -> dict:
    """获取 Agent 记忆统计"""
    result = await db.execute(
        select(Memory.memory_type, func.count())
        .where(Memory.agent_id == agent_id)
        .group_by(Memory.memory_type)
    )
    stats = {row[0]: row[1] for row in result.all()}
    total = sum(stats.values())
    return {"agent_id": agent_id, "total": total, "by_type": stats}

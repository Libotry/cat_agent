"""记忆管理 REST API"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from ..core import get_db
from ..services.memory_admin_service import (
    list_memories, get_memory_detail, get_agent_memory_stats, get_message_memory_refs,
)

router = APIRouter(prefix="/memories", tags=["memory"])


@router.get("")
async def api_list_memories(
    agent_id: int | None = Query(None),
    memory_type: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    return await list_memories(agent_id, memory_type, page, page_size, db)


@router.get("/stats")
async def api_memory_stats(
    agent_id: int = Query(...),
    db: AsyncSession = Depends(get_db),
):
    return await get_agent_memory_stats(agent_id, db)


@router.get("/{memory_id}")
async def api_memory_detail(
    memory_id: int,
    db: AsyncSession = Depends(get_db),
):
    result = await get_memory_detail(memory_id, db)
    if not result:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Memory not found")
    return result


@router.get("/messages/{message_id}/memory-refs")
async def api_message_memory_refs(
    message_id: int,
    db: AsyncSession = Depends(get_db),
):
    return await get_message_memory_refs(message_id, db)

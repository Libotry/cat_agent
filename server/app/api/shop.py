"""
商店 REST API

GET  /shop/items                       — 商品列表
POST /shop/purchase                    — 购买
GET  /shop/agents/{agent_id}/items     — Agent 物品列表
"""
from datetime import datetime
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from ..core import get_db
from ..models import Agent
from ..services.shop_service import shop_service
from .schemas import ItemOut, PurchaseRequest, PurchaseResult, AgentItemOut
from .chat import broadcast

router = APIRouter(prefix="/shop", tags=["shop"])


@router.get("/items", response_model=list[ItemOut])
async def list_items(db: AsyncSession = Depends(get_db)):
    """商品列表"""
    return await shop_service.get_items(db)


@router.post("/purchase", response_model=PurchaseResult)
async def purchase(req: PurchaseRequest, db: AsyncSession = Depends(get_db)):
    """购买：先 commit 再 broadcast"""
    result = await shop_service.purchase(req.agent_id, req.item_id, db)
    if result["ok"]:
        await db.commit()
        agent = await db.get(Agent, req.agent_id)
        await broadcast({
            "type": "system_event",
            "data": {
                "event": "purchase",
                "agent_id": req.agent_id,
                "agent_name": agent.name if agent else "unknown",
                "item_name": result.get("item_name", ""),
                "price": result.get("price", 0),
                "timestamp": datetime.now().isoformat(sep=" ", timespec="seconds"),
            }
        })
    return result


@router.get("/agents/{agent_id}/items", response_model=list[AgentItemOut])
async def agent_items(agent_id: int, db: AsyncSession = Depends(get_db)):
    """Agent 物品列表"""
    return await shop_service.get_agent_items(agent_id, db)

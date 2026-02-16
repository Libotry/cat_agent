from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from ..models import Agent, VirtualItem, AgentItem


class ShopService:

    async def get_items(self, db: AsyncSession) -> list[dict]:
        """商品列表"""
        result = await db.execute(select(VirtualItem))
        return [
            {
                "id": item.id,
                "name": item.name,
                "description": item.description,
                "item_type": item.item_type,
                "price": item.price,
            }
            for item in result.scalars().all()
        ]

    async def purchase(
        self, agent_id: int, item_id: int, db: AsyncSession
    ) -> dict:
        """
        购买逻辑。
        校验：Agent 存在 → 商品存在 → 未重复购买 → 余额充足
        成功：写 AgentItem + Agent.credits -= price
        返回：{"ok": True/False, "reason": str}

        flush 后 IntegrityError 兜底：
        - UNIQUE 约束 → already_owned（并发重复购买）
        - CHECK 约束 → insufficient_credits（并发购买不同商品导致余额为负）
        """
        agent = await db.get(Agent, agent_id)
        if not agent:
            return {"ok": False, "reason": "agent_not_found"}

        item = await db.get(VirtualItem, item_id)
        if not item:
            return {"ok": False, "reason": "item_not_found"}

        # 重复购买检查
        existing = await db.execute(
            select(AgentItem)
            .where(AgentItem.agent_id == agent_id, AgentItem.item_id == item_id)
            .limit(1)
        )
        if existing.scalar_one_or_none():
            return {"ok": False, "reason": "already_owned"}

        # 余额检查
        if agent.credits < item.price:
            return {"ok": False, "reason": "insufficient_credits"}

        # 扣费 + 写入库存
        agent.credits -= item.price
        agent_item = AgentItem(agent_id=agent_id, item_id=item_id)
        db.add(agent_item)
        try:
            await db.flush()
        except IntegrityError as e:
            await db.rollback()
            err = str(e).lower()
            if "unique" in err or "uq_agent_item" in err:
                return {"ok": False, "reason": "already_owned"}
            # CHECK 约束 (credits >= 0) 或其他
            return {"ok": False, "reason": "insufficient_credits"}

        return {
            "ok": True,
            "reason": "success",
            "item_name": item.name,
            "price": item.price,
            "remaining_credits": agent.credits,
        }

    async def get_agent_items(
        self, agent_id: int, db: AsyncSession
    ) -> list[dict]:
        """Agent 拥有的物品列表"""
        result = await db.execute(
            select(AgentItem, VirtualItem)
            .join(VirtualItem, AgentItem.item_id == VirtualItem.id)
            .where(AgentItem.agent_id == agent_id)
        )
        return [
            {
                "item_id": vi.id,
                "name": vi.name,
                "item_type": vi.item_type,
                "purchased_at": str(ai.purchased_at),
            }
            for ai, vi in result.all()
        ]


shop_service = ShopService()

"""Agent 状态变更 + WebSocket 广播（F35）"""
import logging
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from ..models import AgentStatus

logger = logging.getLogger(__name__)


async def set_agent_status(
    agent, status: AgentStatus, activity: str, db: AsyncSession
):
    """更新 Agent 状态 + activity，写入 DB 并广播 WebSocket 事件。"""
    agent.status = status.value
    agent.activity = activity
    await db.commit()

    from ..api.chat import broadcast
    await broadcast({
        "type": "system_event",
        "data": {
            "event": "agent_status_change",
            "agent_id": agent.id,
            "agent_name": agent.name,
            "status": status.value,
            "activity": activity,
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        },
    })

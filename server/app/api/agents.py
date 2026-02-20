from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import logging
import secrets
from ..core import get_db
from ..models import Agent
from .schemas import AgentCreate, AgentUpdate, AgentOut, SoulPersonality

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/agents", tags=["agents"])


def generate_bot_token() -> str:
    """生成 oc_ 前缀的 bot token"""
    return f"oc_{secrets.token_hex(24)}"


def _validate_personality_json(raw: dict | None) -> dict | None:
    """校验并清洗 personality_json，返回清洗后的 dict 或 None"""
    if raw is None:
        return None
    if not raw:  # 空 dict {} → 等同无 personality
        return None
    try:
        soul = SoulPersonality(**raw)
        result = soul.model_dump(exclude_none=True)
        return result if result else None
    except Exception as e:
        logger.warning("SoulPersonality validation failed: %s, ignoring personality_json", e)
        return None


@router.get("/", response_model=list[AgentOut])
async def list_agents(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Agent).where(Agent.id != 0))
    return result.scalars().all()


@router.post("/", response_model=AgentOut, status_code=201)
async def create_agent(data: AgentCreate, db: AsyncSession = Depends(get_db)):
    # 检查名称唯一性
    existing = await db.execute(select(Agent).where(Agent.name == data.name))
    if existing.scalar_one_or_none():
        raise HTTPException(409, f"Agent name '{data.name}' already exists")

    validated_pj = _validate_personality_json(data.personality_json)
    agent = Agent(name=data.name, persona=data.persona, model=data.model, avatar=data.avatar,
                  bot_token=generate_bot_token(), personality_json=validated_pj)
    db.add(agent)
    await db.commit()
    await db.refresh(agent)
    return agent


@router.get("/{agent_id}", response_model=AgentOut)
async def get_agent(agent_id: int, db: AsyncSession = Depends(get_db)):
    agent = await db.get(Agent, agent_id)
    if not agent:
        raise HTTPException(404, "Agent not found")
    return agent


@router.put("/{agent_id}", response_model=AgentOut)
async def update_agent(agent_id: int, data: AgentUpdate, db: AsyncSession = Depends(get_db)):
    agent = await db.get(Agent, agent_id)
    if not agent:
        raise HTTPException(404, "Agent not found")
    if agent_id == 0:
        raise HTTPException(403, "Cannot modify the Human agent")

    update_data = data.model_dump(exclude_unset=True)

    # 如果改名，检查唯一性
    if "name" in update_data and update_data["name"] != agent.name:
        existing = await db.execute(select(Agent).where(Agent.name == update_data["name"]))
        if existing.scalar_one_or_none():
            raise HTTPException(409, f"Agent name '{update_data['name']}' already exists")

    # personality_json 校验
    if "personality_json" in update_data:
        update_data["personality_json"] = _validate_personality_json(update_data["personality_json"])

    for field, value in update_data.items():
        setattr(agent, field, value)

    await db.commit()
    await db.refresh(agent)
    return agent


@router.delete("/{agent_id}", status_code=204)
async def delete_agent(agent_id: int, db: AsyncSession = Depends(get_db)):
    if agent_id == 0:
        raise HTTPException(403, "Cannot delete the Human agent")
    agent = await db.get(Agent, agent_id)
    if not agent:
        raise HTTPException(404, "Agent not found")
    await db.delete(agent)
    await db.commit()


@router.post("/{agent_id}/regenerate-token", response_model=AgentOut)
async def regenerate_token(agent_id: int, db: AsyncSession = Depends(get_db)):
    if agent_id == 0:
        raise HTTPException(403, "Human agent does not have a bot token")
    agent = await db.get(Agent, agent_id)
    if not agent:
        raise HTTPException(404, "Agent not found")
    agent.bot_token = generate_bot_token()
    await db.commit()
    await db.refresh(agent)
    return agent


@router.get("/{agent_id}/strategies")
async def get_agent_strategies(agent_id: int, db: AsyncSession = Depends(get_db)):
    """获取 Agent 当前活跃策略（策略自动机观测接口）。"""
    agent = await db.get(Agent, agent_id)
    if not agent:
        raise HTTPException(404, "Agent not found")
    from ..services.strategy_engine import get_strategies
    strategies = get_strategies(agent_id)
    return [s.model_dump() for s in strategies]


@router.post("/{agent_id}/strategies")
async def set_agent_strategies(agent_id: int, strategies: list[dict], db: AsyncSession = Depends(get_db)):
    """设置 Agent 策略（全量替换）。"""
    agent = await db.get(Agent, agent_id)
    if not agent:
        raise HTTPException(404, "Agent not found")
    from ..services.strategy_engine import Strategy, update_strategies
    parsed = [Strategy(**s) for s in strategies]
    update_strategies(agent_id, parsed)
    return {"ok": True, "count": len(parsed)}


@router.delete("/{agent_id}/strategies")
async def clear_agent_strategies(agent_id: int, db: AsyncSession = Depends(get_db)):
    """清空 Agent 所有策略。"""
    agent = await db.get(Agent, agent_id)
    if not agent:
        raise HTTPException(404, "Agent not found")
    from ..services.strategy_engine import clear_strategies
    clear_strategies(agent_id)
    return {"ok": True}


@router.get("/strategies/all")
async def get_all_agent_strategies():
    """获取所有 Agent 的策略（调试用）。"""
    from ..services.strategy_engine import get_all_strategies
    all_s = get_all_strategies()
    return {str(aid): [s.model_dump() for s in ss] for aid, ss in all_s.items()}

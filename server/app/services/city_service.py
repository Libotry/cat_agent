"""城市经济服务"""
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from ..models import Agent, Building, BuildingWorker, Resource, AgentResource, ProductionLog

HUMAN_ID = 0


async def _get_or_create_agent_resource(agent_id: int, resource_type: str, db: AsyncSession) -> AgentResource:
    """获取或创建 agent 个人资源记录"""
    result = await db.execute(
        select(AgentResource)
        .where(AgentResource.agent_id == agent_id, AgentResource.resource_type == resource_type)
    )
    ar = result.scalar()
    if not ar:
        ar = AgentResource(agent_id=agent_id, resource_type=resource_type, quantity=0)
        db.add(ar)
        await db.flush()
    return ar


async def get_agent_resources(agent_id: int, db: AsyncSession) -> list[dict]:
    """返回 agent 个人资源列表"""
    result = await db.execute(
        select(AgentResource).where(AgentResource.agent_id == agent_id)
    )
    return [
        {"resource_type": ar.resource_type, "quantity": ar.quantity}
        for ar in result.scalars().all()
    ]


async def transfer_resource(from_agent_id: int, to_agent_id: int, resource_type: str, quantity: int, db: AsyncSession) -> dict:
    """在两个 agent 之间转移资源"""
    if quantity <= 0:
        return {"ok": False, "reason": "数量必须大于 0"}

    from_res = await _get_or_create_agent_resource(from_agent_id, resource_type, db)
    if from_res.quantity < quantity:
        return {"ok": False, "reason": f"{resource_type} 不足，当前 {from_res.quantity}，需要 {quantity}"}

    to_res = await _get_or_create_agent_resource(to_agent_id, resource_type, db)
    from_res.quantity -= quantity
    to_res.quantity += quantity
    await db.commit()
    return {"ok": True, "reason": f"转移 {quantity} {resource_type} 成功"}


async def get_city_overview(city: str, db: AsyncSession) -> dict:
    """返回城市总览：公共资源 + 建筑（含工人）+ agent 列表（含个人资源）"""
    resources = await get_resources(city, db)
    buildings = await get_buildings(city, db)

    agents_result = await db.execute(
        select(Agent).where(Agent.id != HUMAN_ID)
    )
    agents = []
    for a in agents_result.scalars().all():
        agent_res = await get_agent_resources(a.id, db)
        agents.append({
            "id": a.id, "name": a.name, "satiety": a.satiety, "mood": a.mood,
            "resources": agent_res,
        })
    return {"city": city, "resources": resources, "buildings": buildings, "agents": agents}


async def get_buildings(city: str, db: AsyncSession) -> list[dict]:
    """返回城市所有建筑（含工人列表）"""
    result = await db.execute(
        select(Building).where(Building.city == city)
    )
    buildings = []
    for b in result.scalars().all():
        workers_result = await db.execute(
            select(BuildingWorker, Agent)
            .join(Agent, BuildingWorker.agent_id == Agent.id)
            .where(BuildingWorker.building_id == b.id)
        )
        workers = [
            {"agent_id": w.agent_id, "agent_name": a.name, "assigned_at": str(w.assigned_at)}
            for w, a in workers_result.all()
        ]
        buildings.append({
            "id": b.id, "name": b.name, "building_type": b.building_type,
            "city": b.city, "owner": b.owner, "max_workers": b.max_workers,
            "description": b.description, "workers": workers,
        })
    return buildings


async def get_building_detail(city: str, building_id: int, db: AsyncSession) -> dict | None:
    """返回单个建筑详情"""
    b = await db.get(Building, building_id)
    if not b or b.city != city:
        return None
    workers_result = await db.execute(
        select(BuildingWorker, Agent)
        .join(Agent, BuildingWorker.agent_id == Agent.id)
        .where(BuildingWorker.building_id == b.id)
    )
    workers = [
        {"agent_id": w.agent_id, "agent_name": a.name, "assigned_at": str(w.assigned_at)}
        for w, a in workers_result.all()
    ]
    return {
        "id": b.id, "name": b.name, "building_type": b.building_type,
        "city": b.city, "owner": b.owner, "max_workers": b.max_workers,
        "description": b.description, "workers": workers,
    }


async def assign_worker(city: str, building_id: int, agent_id: int, db: AsyncSession) -> dict:
    """分配工人到建筑"""
    b = await db.get(Building, building_id)
    if not b or b.city != city:
        return {"ok": False, "reason": "建筑不存在"}

    # 检查工位是否已满
    count_result = await db.execute(
        select(BuildingWorker).where(BuildingWorker.building_id == building_id)
    )
    current_workers = len(count_result.scalars().all())
    if current_workers >= b.max_workers:
        return {"ok": False, "reason": "工位已满"}

    # 检查 agent 是否已在该建筑工作
    existing = await db.execute(
        select(BuildingWorker)
        .where(BuildingWorker.building_id == building_id, BuildingWorker.agent_id == agent_id)
    )
    if existing.scalar():
        return {"ok": False, "reason": "该 Agent 已在此建筑工作"}

    db.add(BuildingWorker(building_id=building_id, agent_id=agent_id))
    await db.commit()
    return {"ok": True, "reason": "分配成功"}


async def remove_worker(city: str, building_id: int, agent_id: int, db: AsyncSession) -> dict:
    """移除建筑工人"""
    result = await db.execute(
        select(BuildingWorker)
        .where(BuildingWorker.building_id == building_id, BuildingWorker.agent_id == agent_id)
    )
    bw = result.scalar()
    if not bw:
        return {"ok": False, "reason": "该工人不在此建筑"}
    await db.delete(bw)
    await db.commit()
    return {"ok": True, "reason": "移除成功"}


async def get_resources(city: str, db: AsyncSession) -> list[dict]:
    """返回城市公共资源列表"""
    result = await db.execute(
        select(Resource).where(Resource.city == city)
    )
    return [
        {"resource_type": r.resource_type, "quantity": r.quantity}
        for r in result.scalars().all()
    ]


async def eat_food(agent_id: int, db: AsyncSession) -> dict:
    """Agent 吃饭：消耗个人 1 面粉，饱腹度+30，心情+10"""
    agent = await db.get(Agent, agent_id)
    if not agent:
        return {"ok": False, "reason": "Agent 不存在", "satiety": 0, "mood": 0}

    # 从 agent 个人面粉扣除
    flour = await _get_or_create_agent_resource(agent_id, "flour", db)
    if flour.quantity < 1:
        return {"ok": False, "reason": "面粉不足", "satiety": agent.satiety, "mood": agent.mood}

    flour.quantity -= 1
    agent.satiety = min(100, agent.satiety + 30)
    agent.mood = min(100, agent.mood + 10)
    await db.commit()
    return {"ok": True, "reason": "吃饱了", "satiety": agent.satiety, "mood": agent.mood}


async def production_tick(city: str, db: AsyncSession):
    """每天执行一次的生产循环（在 scheduler_loop 中调用）

    - 农田：每个工人产出 10 小麦（加到工人个人资源）
    - 磨坊：每个工人消耗个人 5 小麦，产出 3 面粉（加到工人个人资源）
    - 饱腹度衰减：所有 agent -15/天
    - 心情衰减：饱腹度<30 时 -10/天；饱腹度=0 时 -20/天
    """
    import logging
    logger = logging.getLogger(__name__)

    # 1. 农田生产 → 小麦加到工人个人资源
    farm_result = await db.execute(
        select(Building, BuildingWorker)
        .join(BuildingWorker, BuildingWorker.building_id == Building.id)
        .where(Building.city == city, Building.building_type == "farm")
    )
    for building, worker in farm_result.all():
        wheat = await _get_or_create_agent_resource(worker.agent_id, "wheat", db)
        wheat.quantity += 10
        db.add(ProductionLog(
            building_id=building.id, agent_id=worker.agent_id,
            input_type=None, input_qty=0,
            output_type="wheat", output_qty=10,
        ))
        logger.info("生产: 农田 %s 工人 %d 产出 10 小麦", building.name, worker.agent_id)

    # 2. 磨坊加工 → 从工人个人小麦扣，面粉加到工人个人
    mill_result = await db.execute(
        select(Building, BuildingWorker)
        .join(BuildingWorker, BuildingWorker.building_id == Building.id)
        .where(Building.city == city, Building.building_type == "mill")
    )
    for building, worker in mill_result.all():
        wheat = await _get_or_create_agent_resource(worker.agent_id, "wheat", db)
        if wheat.quantity >= 5:
            wheat.quantity -= 5
            flour = await _get_or_create_agent_resource(worker.agent_id, "flour", db)
            flour.quantity += 3
            db.add(ProductionLog(
                building_id=building.id, agent_id=worker.agent_id,
                input_type="wheat", input_qty=5,
                output_type="flour", output_qty=3,
            ))
            logger.info("生产: 磨坊 %s 工人 %d 消耗5小麦产出3面粉", building.name, worker.agent_id)
        else:
            logger.info("生产: 磨坊 %s 工人 %d 小麦不足，跳过", building.name, worker.agent_id)

    # 3. 饱腹度/心情衰减（所有非人类 agent）
    agents_result = await db.execute(
        select(Agent).where(Agent.id != HUMAN_ID)
    )
    for agent in agents_result.scalars().all():
        agent.satiety = max(0, agent.satiety - 15)
        if agent.satiety == 0:
            agent.mood = max(0, agent.mood - 20)
        elif agent.satiety < 30:
            agent.mood = max(0, agent.mood - 10)

    await db.commit()
    logger.info("生产循环完成: %s", city)


async def get_production_logs(city: str, limit: int, db: AsyncSession) -> list[dict]:
    """返回最近的生产日志"""
    result = await db.execute(
        select(ProductionLog, Building)
        .join(Building, ProductionLog.building_id == Building.id)
        .where(Building.city == city)
        .order_by(ProductionLog.tick_time.desc())
        .limit(limit)
    )
    return [
        {
            "id": log.id, "building_id": log.building_id,
            "agent_id": log.agent_id,
            "input_type": log.input_type, "input_qty": log.input_qty,
            "output_type": log.output_type, "output_qty": log.output_qty,
            "tick_time": str(log.tick_time),
        }
        for log, _ in result.all()
    ]

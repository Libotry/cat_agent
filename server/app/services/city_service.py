"""城市经济服务"""
import logging
from datetime import datetime, timezone
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from ..models import Agent, Building, BuildingWorker, Resource, AgentResource, ProductionLog

HUMAN_ID = 0
logger = logging.getLogger(__name__)

# M6.1 建造配方
BUILDING_RECIPES = {
    "farm": {
        "cost": {"wood": 10, "stone": 5},
        "construction_days": 3,
        "max_workers": 3,
        "description": "农田，每日每工人产出 10 小麦",
    },
    "mill": {
        "cost": {"wood": 15, "stone": 10},
        "construction_days": 5,
        "max_workers": 2,
        "description": "磨坊，每日每工人消耗 5 小麦产出 3 面粉",
    },
}


async def _broadcast_city_event(event: str, data: dict):
    """广播城市经济相关的 WS 事件"""
    from ..api.chat import broadcast
    from datetime import datetime, timezone
    await broadcast({
        "type": "system_event",
        "data": {"event": event, "timestamp": datetime.now(timezone.utc).isoformat(), **data},
    })


async def construct_building(
    builder_id: int, building_type: str, name: str, city: str, *, db: AsyncSession
) -> dict:
    """发起建造：校验配方 → 扣资源 → 创建 constructing 状态建筑"""
    recipe = BUILDING_RECIPES.get(building_type)
    if not recipe:
        return {"ok": False, "reason": f"不支持建造 {building_type}，可建造: {', '.join(BUILDING_RECIPES)}"}

    # 校验建造者个人资源
    for res_type, needed in recipe["cost"].items():
        ar = await _get_or_create_agent_resource(builder_id, res_type, db)
        available = ar.quantity - ar.frozen_amount
        if available < needed:
            return {"ok": False, "reason": f"{res_type} 不足，需要 {needed}，可用 {available}"}

    # 扣除资源
    for res_type, needed in recipe["cost"].items():
        ar = await _get_or_create_agent_resource(builder_id, res_type, db)
        ar.quantity -= needed

    # 创建建筑
    now = datetime.now(timezone.utc)
    builder = await db.get(Agent, builder_id)
    building = Building(
        name=name,
        building_type=building_type,
        city=city,
        owner=builder.name if builder else f"Agent#{builder_id}",
        max_workers=recipe["max_workers"],
        description=recipe["description"],
        status="constructing",
        construction_started_at=now,
        construction_days=recipe["construction_days"],
        builder_id=builder_id,
    )
    db.add(building)
    await db.flush()

    estimated = recipe["construction_days"]
    await db.commit()

    await _broadcast_city_event("building_construction_started", {
        "building_id": building.id,
        "building_type": building_type,
        "name": name,
        "builder_id": builder_id,
        "construction_days": estimated,
    })

    return {
        "ok": True,
        "building_id": building.id,
        "estimated_completion_days": estimated,
        "reason": f"开始建造 {name}，工期 {estimated} 天",
    }


async def check_construction_progress(city: str, db: AsyncSession):
    """检查 constructing 建筑，工期到了改为 active"""
    now = datetime.now(timezone.utc)
    result = await db.execute(
        select(Building).where(Building.city == city, Building.status == "constructing")
    )
    for building in result.scalars().all():
        if not building.construction_started_at:
            continue
        started = building.construction_started_at
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        elapsed_days = (now - started).days
        if elapsed_days >= building.construction_days:
            building.status = "active"
            logger.info("建造完成: %s (ID=%d)，工期 %d 天", building.name, building.id, building.construction_days)
            await _broadcast_city_event("building_completed", {
                "building_id": building.id,
                "name": building.name,
                "building_type": building.building_type,
                "builder_id": building.builder_id,
            })
    await db.flush()


async def _get_or_create_agent_resource(agent_id: int, resource_type: str, db: AsyncSession) -> AgentResource:
    """获取或创建 agent 个人资源记录"""
    result = await db.execute(
        select(AgentResource)
        .where(AgentResource.agent_id == agent_id, AgentResource.resource_type == resource_type)
    )
    ar = result.scalar()
    if not ar:
        ar = AgentResource(agent_id=agent_id, resource_type=resource_type, quantity=0.0, frozen_amount=0.0)
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


async def transfer_resource(from_agent_id: int, to_agent_id: int, resource_type: str, quantity: float, db: AsyncSession) -> dict:
    """在两个 agent 之间转移资源"""
    if quantity <= 0:
        return {"ok": False, "reason": "数量必须大于 0"}

    from_res = await _get_or_create_agent_resource(from_agent_id, resource_type, db)
    available = from_res.quantity - from_res.frozen_amount
    if available < quantity:
        return {"ok": False, "reason": f"{resource_type} 可用不足，当前可用 {available}，需要 {quantity}"}

    to_res = await _get_or_create_agent_resource(to_agent_id, resource_type, db)
    from_res.quantity -= quantity
    to_res.quantity += quantity
    await db.commit()

    # M5.1: 广播转赠事件
    from_agent = await db.get(Agent, from_agent_id)
    to_agent = await db.get(Agent, to_agent_id)
    await _broadcast_city_event("resource_transferred", {
        "from_agent_id": from_agent_id,
        "from_agent_name": from_agent.name if from_agent else f"Agent#{from_agent_id}",
        "to_agent_id": to_agent_id,
        "to_agent_name": to_agent.name if to_agent else f"Agent#{to_agent_id}",
        "resource_type": resource_type,
        "quantity": quantity,
    })

    return {"ok": True, "reason": f"转移 {quantity} {resource_type} 成功"}


async def get_city_overview(city: str, db: AsyncSession) -> dict:
    """返回城市总览：公共资源 + 建筑（含工人）+ agent 列表（含个人资源+三维属性）"""
    resources = await get_resources(city, db)
    buildings = await get_buildings(city, db)

    agents_result = await db.execute(
        select(Agent).where(Agent.id != HUMAN_ID)
    )
    agents = []
    for a in agents_result.scalars().all():
        agent_res = await get_agent_resources(a.id, db)
        agents.append({
            "id": a.id, "name": a.name,
            "satiety": a.satiety, "mood": a.mood, "stamina": a.stamina,
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
            "status": b.status,
            "construction_started_at": str(b.construction_started_at) if b.construction_started_at else None,
            "construction_days": b.construction_days,
            "builder_id": b.builder_id,
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
        "status": b.status,
        "construction_started_at": str(b.construction_started_at) if b.construction_started_at else None,
        "construction_days": b.construction_days,
        "builder_id": b.builder_id,
    }


async def assign_worker(city: str, building_id: int, agent_id: int, db: AsyncSession) -> dict:
    """分配工人到建筑"""
    b = await db.get(Building, building_id)
    if not b or b.city != city:
        return {"ok": False, "reason": "建筑不存在"}

    # M6.1: 拒绝分配工人到建造中的建筑
    if b.status != "active":
        return {"ok": False, "reason": "建筑尚未建成，无法分配工人"}

    # 检查工位是否已满
    count_result = await db.execute(
        select(BuildingWorker).where(BuildingWorker.building_id == building_id)
    )
    current_workers = len(count_result.scalars().all())
    if current_workers >= b.max_workers:
        return {"ok": False, "reason": "工位已满"}

    # 检查 agent 是否已在任何建筑工作（跨建筑检查）
    any_existing = await db.execute(
        select(BuildingWorker).where(BuildingWorker.agent_id == agent_id)
    )
    if any_existing.scalar():
        return {"ok": False, "reason": "已在其他建筑工作，请先离职"}

    db.add(BuildingWorker(building_id=building_id, agent_id=agent_id))
    await db.commit()
    await _broadcast_city_event("worker_assigned", {
        "agent_id": agent_id, "building_id": building_id,
    })
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
    await _broadcast_city_event("worker_unassigned", {
        "agent_id": agent_id, "building_id": building_id,
    })
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
    """Agent 吃饭：消耗个人 1 面粉，饱腹度+30，心情+10，体力+20"""
    agent = await db.get(Agent, agent_id)
    if not agent:
        return {"ok": False, "reason": "Agent 不存在", "satiety": 0, "mood": 0, "stamina": 0}

    flour = await _get_or_create_agent_resource(agent_id, "flour", db)
    if flour.quantity < 1:
        return {"ok": False, "reason": "面粉不足", "satiety": agent.satiety, "mood": agent.mood, "stamina": agent.stamina}

    flour.quantity -= 1
    agent.satiety = min(100, agent.satiety + 30)
    agent.mood = min(100, agent.mood + 10)
    agent.stamina = min(100, agent.stamina + 20)
    await db.commit()
    await _broadcast_city_event("agent_ate", {
        "agent_id": agent_id, "satiety": agent.satiety, "mood": agent.mood, "stamina": agent.stamina,
    })
    return {"ok": True, "reason": "吃饱了", "satiety": agent.satiety, "mood": agent.mood, "stamina": agent.stamina}


async def daily_attribute_decay(db: AsyncSession):
    """每日属性结算（从 production_tick 拆出）。
    - satiety -= 15（下限 0）
    - stamina += 15（上限 100）
    - mood: 饱腹度=0 时 -20，饱腹度<30 时 -10，否则不变（下限 0）
    """
    agents_result = await db.execute(
        select(Agent).where(Agent.id != HUMAN_ID)
    )
    for agent in agents_result.scalars().all():
        agent.satiety = max(0, agent.satiety - 15)
        agent.stamina = min(100, agent.stamina + 15)
        if agent.satiety == 0:
            agent.mood = max(0, agent.mood - 20)
        elif agent.satiety < 30:
            agent.mood = max(0, agent.mood - 10)
    await db.commit()
    logger.info("每日属性结算完成")
    await _broadcast_city_event("attribute_changed", {"reason": "daily_decay"})


async def production_tick(city: str, db: AsyncSession):
    """每天执行一次的生产循环（不再做属性衰减）

    - 农田：每个工人产出 10 小麦（加到工人个人资源）
    - 磨坊：每个工人消耗个人 5 小麦，产出 3 面粉（加到工人个人资源）
    - 官府田：每个工人直接产出 5 面粉（虚空造币，无需原料）
    - 体力检查：stamina < 20 跳过生产；生产后 stamina -= 15
    """
    # M6.1: 先检查建造进度
    await check_construction_progress(city, db)

    # 1. 农田生产
    farm_result = await db.execute(
        select(Building, BuildingWorker)
        .join(BuildingWorker, BuildingWorker.building_id == Building.id)
        .where(Building.city == city, Building.building_type == "farm", Building.status == "active")
    )
    for building, worker in farm_result.all():
        agent = await db.get(Agent, worker.agent_id)
        if agent.stamina < 20:
            logger.info("生产: 农田 %s 工人 %d 体力不足(%d)，跳过", building.name, worker.agent_id, agent.stamina)
            continue
        wheat = await _get_or_create_agent_resource(worker.agent_id, "wheat", db)
        wheat.quantity += 10
        agent.stamina = max(0, agent.stamina - 15)
        db.add(ProductionLog(
            building_id=building.id, agent_id=worker.agent_id,
            input_type=None, input_qty=0,
            output_type="wheat", output_qty=10,
        ))
        logger.info("生产: 农田 %s 工人 %d 产出 10 小麦", building.name, worker.agent_id)

    # 2. 磨坊加工
    mill_result = await db.execute(
        select(Building, BuildingWorker)
        .join(BuildingWorker, BuildingWorker.building_id == Building.id)
        .where(Building.city == city, Building.building_type == "mill", Building.status == "active")
    )
    for building, worker in mill_result.all():
        agent = await db.get(Agent, worker.agent_id)
        if agent.stamina < 20:
            logger.info("生产: 磨坊 %s 工人 %d 体力不足(%d)，跳过", building.name, worker.agent_id, agent.stamina)
            continue
        wheat = await _get_or_create_agent_resource(worker.agent_id, "wheat", db)
        if wheat.quantity >= 5:
            wheat.quantity -= 5
            flour = await _get_or_create_agent_resource(worker.agent_id, "flour", db)
            flour.quantity += 3
            agent.stamina = max(0, agent.stamina - 15)
            db.add(ProductionLog(
                building_id=building.id, agent_id=worker.agent_id,
                input_type="wheat", input_qty=5,
                output_type="flour", output_qty=3,
            ))
            logger.info("生产: 磨坊 %s 工人 %d 消耗5小麦产出3面粉", building.name, worker.agent_id)
        else:
            logger.info("生产: 磨坊 %s 工人 %d 小麦不足，跳过", building.name, worker.agent_id)

    # 3. 官府田生产（虚空造币）
    gov_farm_result = await db.execute(
        select(Building, BuildingWorker)
        .join(BuildingWorker, BuildingWorker.building_id == Building.id)
        .where(Building.city == city, Building.building_type == "gov_farm", Building.status == "active")
    )
    for building, worker in gov_farm_result.all():
        agent = await db.get(Agent, worker.agent_id)
        if agent.stamina < 20:
            logger.info("生产: 官府田 %s 工人 %d 体力不足(%d)，跳过", building.name, worker.agent_id, agent.stamina)
            continue
        flour = await _get_or_create_agent_resource(worker.agent_id, "flour", db)
        flour.quantity += 5
        agent.stamina = max(0, agent.stamina - 15)
        db.add(ProductionLog(
            building_id=building.id, agent_id=worker.agent_id,
            input_type=None, input_qty=0,
            output_type="flour", output_qty=5,
        ))
        logger.info("生产: 官府田 %s 工人 %d 产出 5 面粉", building.name, worker.agent_id)

    await db.commit()
    logger.info("生产循环完成: %s", city)
    await _broadcast_city_event("production_settled", {"city": city})


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

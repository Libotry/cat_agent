# TDD-M3: 城市经济闭环 技术设计

> M3 里程碑技术设计文档。基于 02-需求拆分.md 中的任务分解，定义具体实现方案。
> IR: 01-需求原型.md §M3 (US-M3-1~6, F8~F10, AC-M3-01~11)
> SR: 02-需求拆分.md §M3 (M3-1~M3-10)

---

## 1. 架构总览

```
                    Frontend (React + Vite)
  +----------+  +-----------+  +-----------+
  | JobBoard |  | LifePanel |  | ItemShop  |
  +----+-----+  +-----+-----+  +-----+-----+
       +--------------+--------------+
                      | REST + WebSocket
                 Server (FastAPI)
  +-------------------v----------------------------+
  |           Existing WebSocket Hub (chat.py)      |
  |    + system_event broadcast (checkin/purchase)  |
  +------+----------------+----------------+-------+
  +------v------+  +------v------+  +------v------+
  | WorkService |  | ShopService |  | EconomySvc  |
  | (新建)       |  | (新建)       |  | (已有)       |
  +------+------+  +------+------+  +------+------+
  +------v-----------------------------------------+
  |           SQLite (WAL mode)                     |
  |  agents | jobs | checkins | virtual_items |     |
  |  agent_items | messages | memories | ...        |
  +------------------------------------------------+
```

### 新增模块清单

| 文件 | 职责 | 任务 ID |
|------|------|---------|
| `app/services/work_service.py` | 岗位查询 + 打卡逻辑 + 预置岗位 seed | M3-2 |
| `app/services/shop_service.py` | 商品查询 + 购买逻辑 + 预置商品 seed | M3-3 |
| `app/api/work.py` | 工作系统 REST API | M3-4 |
| `app/api/shop.py` | 商店 REST API | M3-4 |

### 修改模块清单

| 文件 | 修改内容 | 任务 ID |
|------|----------|---------|
| `app/models/tables.py` | 新增 VirtualItem + AgentItem 模型 | M3-1 |
| `app/api/schemas.py` | 新增 Job/CheckIn/Item/Purchase 相关 schema | M3-4 |
| `app/api/chat.py` | broadcast 函数复用，新增 system_event 类型 | M3-9 |
| `server/main.py` | 注册 work_router + shop_router，lifespan 中 seed 数据 | M3-4 |
| `app/services/scheduler.py` | 无修改（打卡由 Agent 手动触发，不自动发薪） | — |

---

## 2. 数据模型

### 2.1 新增表 (M3-1)

**VirtualItem** — 虚拟商品定义

```python
class ItemType(str, enum.Enum):
    AVATAR_FRAME = "avatar_frame"
    TITLE = "title"
    DECORATION = "decoration"

class VirtualItem(Base):
    __tablename__ = "virtual_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(64), unique=True, nullable=False)
    description = Column(Text, default="")
    item_type = Column(String(16), nullable=False)  # avatar_frame / title / decoration
    price = Column(Integer, nullable=False)
    created_at = Column(DateTime, server_default=func.now())
```

**AgentItem** — Agent 物品库存

```python
class AgentItem(Base):
    __tablename__ = "agent_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    agent_id = Column(Integer, ForeignKey("agents.id"), nullable=False)
    item_id = Column(Integer, ForeignKey("virtual_items.id"), nullable=False)
    purchased_at = Column(DateTime, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("agent_id", "item_id", name="uq_agent_item"),
    )
```

### 2.2 已有表修改

- `Agent`：新增 `CheckConstraint("credits >= 0", name="ck_agent_credits_non_negative")`，防止并发购买不同商品导致 credits 为负（串讲遗漏点 #2）
- `Job`（id, title, description, daily_reward, max_workers）— 无修改
- `CheckIn`（id, agent_id, job_id, reward, checked_at）— 无修改

### 2.3 预置数据 Seed

**岗位 seed**（lifespan 启动时，仅在表为空时插入）:

| title | description | daily_reward | max_workers |
|-------|-------------|-------------|-------------|
| 矿工 | 在矿山挖掘矿石 | 8 | 5 |
| 农夫 | 在农场种植作物 | 6 | 5 |
| 程序员 | 编写代码和修复 bug | 15 | 3 |
| 教师 | 教授知识和技能 | 10 | 3 |
| 商人 | 经营贸易和买卖 | 12 | 4 |

**商品 seed**:

| name | item_type | price | description |
|------|-----------|-------|-------------|
| 金色头像框 | avatar_frame | 20 | 闪闪发光的金色边框 |
| 银色头像框 | avatar_frame | 10 | 低调优雅的银色边框 |
| 城市先锋 | title | 30 | 城市建设先驱者称号 |
| 勤劳之星 | title | 15 | 每日打卡不间断 |
| 彩虹徽章 | decoration | 25 | 七彩缤纷的个人徽章 |

---

## 3. 工作系统服务 (M3-2)

**文件**: `app/services/work_service.py`

```python
from datetime import date, datetime
from sqlalchemy import select, func as sa_func
from sqlalchemy.ext.asyncio import AsyncSession
from ..models import Agent, Job, CheckIn

class WorkService:

    async def get_jobs(self, db: AsyncSession) -> list[dict]:
        """岗位列表，含当日在岗人数"""
        today = date.today()
        # 子查询：当日每个岗位的打卡人数
        checkin_counts = (
            select(
                CheckIn.job_id,
                sa_func.count(CheckIn.id).label("today_workers")
            )
            .where(sa_func.date(CheckIn.checked_at) == today)
            .group_by(CheckIn.job_id)
            .subquery()
        )
        result = await db.execute(
            select(Job, checkin_counts.c.today_workers)
            .outerjoin(checkin_counts, Job.id == checkin_counts.c.job_id)
        )
        jobs = []
        for job, today_workers in result.all():
            jobs.append({
                "id": job.id,
                "title": job.title,
                "description": job.description,
                "daily_reward": job.daily_reward,
                "max_workers": job.max_workers,
                "today_workers": today_workers or 0,
            })
        return jobs

    async def check_in(
        self, agent_id: int, job_id: int, db: AsyncSession
    ) -> dict:
        """
        打卡逻辑。
        校验：Agent 存在 → 岗位存在 → 今日未打卡 → 岗位未满员
        成功：写 CheckIn + Agent.credits += daily_reward
        返回：{"ok": True/False, "reason": str, "reward": int}
        """
        agent = await db.get(Agent, agent_id)
        if not agent:
            return {"ok": False, "reason": "agent_not_found", "reward": 0}

        job = await db.get(Job, job_id)
        if not job:
            return {"ok": False, "reason": "job_not_found", "reward": 0}

        # 今日是否已打卡（任意岗位）
        today = date.today()
        existing = await db.execute(
            select(CheckIn)
            .where(
                CheckIn.agent_id == agent_id,
                sa_func.date(CheckIn.checked_at) == today,
            )
            .limit(1)
        )
        if existing.scalar_one_or_none():
            return {"ok": False, "reason": "already_checked_in", "reward": 0}

        # 岗位容量检查（max_workers=0 表示无限制）
        if job.max_workers > 0:
            today_count = await db.execute(
                select(sa_func.count(CheckIn.id))
                .where(
                    CheckIn.job_id == job_id,
                    sa_func.date(CheckIn.checked_at) == today,
                )
            )
            if today_count.scalar() >= job.max_workers:
                return {"ok": False, "reason": "job_full", "reward": 0}

        # 写入打卡记录 + 发薪
        checkin = CheckIn(
            agent_id=agent_id,
            job_id=job_id,
            reward=job.daily_reward,
        )
        db.add(checkin)
        agent.credits += job.daily_reward
        await db.flush()
        await db.refresh(checkin)

        return {
            "ok": True,
            "reason": "success",
            "reward": job.daily_reward,
            "checkin_id": checkin.id,
        }

    async def get_today_checkin(
        self, agent_id: int, db: AsyncSession
    ) -> dict | None:
        """查询 Agent 今日打卡记录，无则返回 None"""
        today = date.today()
        result = await db.execute(
            select(CheckIn)
            .where(
                CheckIn.agent_id == agent_id,
                sa_func.date(CheckIn.checked_at) == today,
            )
            .limit(1)
        )
        checkin = result.scalar_one_or_none()
        if not checkin:
            return None
        return {
            "checkin_id": checkin.id,
            "job_id": checkin.job_id,
            "reward": checkin.reward,
            "checked_at": str(checkin.checked_at),
        }

    async def get_work_history(
        self, agent_id: int, db: AsyncSession, days: int = 7
    ) -> list[dict]:
        """最近 N 天打卡记录"""
        from datetime import timedelta
        since = datetime.now() - timedelta(days=days)
        result = await db.execute(
            select(CheckIn)
            .where(CheckIn.agent_id == agent_id, CheckIn.checked_at >= since)
            .order_by(CheckIn.checked_at.desc())
        )
        return [
            {
                "checkin_id": c.id,
                "job_id": c.job_id,
                "reward": c.reward,
                "checked_at": str(c.checked_at),
            }
            for c in result.scalars().all()
        ]

work_service = WorkService()
```

---

## 4. 商店服务 (M3-3)

**文件**: `app/services/shop_service.py`

```python
from sqlalchemy import select
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
        await db.flush()

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
```

---

## 5. REST API (M3-4)

### 5.1 工作 API

**文件**: `app/api/work.py`

```python
router = APIRouter(prefix="/work", tags=["work"])

# GET  /api/work/jobs                    — 岗位列表（含当日在岗人数）
# POST /api/work/jobs/{job_id}/checkin   — 打卡（body: {"agent_id": int}）
# GET  /api/work/agents/{agent_id}/today — 今日打卡状态
# GET  /api/work/agents/{agent_id}/history?days=7 — 打卡记录
```

打卡成功后广播 system_event（见 §7）。

**⚠️ handler 时序约定**（串讲遗漏点 #3）：操作成功后，必须先 `await db.commit()` 再 `await broadcast(...)`。不依赖 dependency 的自动 commit，避免事件推送了但数据未落盘。

```python
# work.py handler 示例
result = await work_service.check_in(req.agent_id, job_id, db)
if result["ok"]:
    await db.commit()  # 先提交
    await broadcast({...})  # 再广播
    return result
```

### 5.2 商店 API

**文件**: `app/api/shop.py`

```python
router = APIRouter(prefix="/shop", tags=["shop"])

# GET  /api/shop/items                        — 商品列表
# POST /api/shop/purchase                     — 购买（body: {"agent_id": int, "item_id": int}）
# GET  /api/shop/agents/{agent_id}/items      — Agent 物品列表
```

购买成功后广播 system_event（见 §7）。

### 5.3 Schema 新增

**文件**: `app/api/schemas.py` 追加

```python
# --- Job ---
class JobOut(BaseModel):
    model_config = {"from_attributes": True}
    id: int
    title: str
    description: str
    daily_reward: int
    max_workers: int
    today_workers: int = 0

# --- CheckIn ---
class CheckInRequest(BaseModel):
    agent_id: int

class CheckInOut(BaseModel):
    checkin_id: int
    job_id: int
    reward: int
    checked_at: str

class CheckInResult(BaseModel):
    ok: bool
    reason: str
    reward: int = 0
    checkin_id: int | None = None

# --- Shop ---
class ItemOut(BaseModel):
    model_config = {"from_attributes": True}
    id: int
    name: str
    description: str
    item_type: str
    price: int

class PurchaseRequest(BaseModel):
    agent_id: int
    item_id: int

class PurchaseResult(BaseModel):
    ok: bool
    reason: str
    item_name: str | None = None
    price: int | None = None
    remaining_credits: int | None = None

class AgentItemOut(BaseModel):
    item_id: int
    name: str
    item_type: str
    purchased_at: str
```

### 5.4 路由注册

**修改**: `server/main.py`

```python
from app.api.work import router as work_router
from app.api.shop import router as shop_router

app.include_router(work_router, prefix="/api")
app.include_router(shop_router, prefix="/api")
```

---

## 6. 数据 Seed (M3-2, M3-3)

在 `main.py` 的 lifespan 中，数据库初始化后执行：

```python
async def seed_jobs_and_items(db: AsyncSession):
    """仅在表为空时插入预置数据"""
    job_count = await db.execute(select(sa_func.count(Job.id)))
    if job_count.scalar() == 0:
        db.add_all([
            Job(title="矿工", description="在矿山挖掘矿石", daily_reward=8, max_workers=5),
            Job(title="农夫", description="在农场种植作物", daily_reward=6, max_workers=5),
            Job(title="程序员", description="编写代码和修复bug", daily_reward=15, max_workers=3),
            Job(title="教师", description="教授知识和技能", daily_reward=10, max_workers=3),
            Job(title="商人", description="经营贸易和买卖", daily_reward=12, max_workers=4),
        ])

    item_count = await db.execute(select(sa_func.count(VirtualItem.id)))
    if item_count.scalar() == 0:
        db.add_all([
            VirtualItem(name="金色头像框", item_type="avatar_frame", price=20, description="闪闪发光的金色边框"),
            VirtualItem(name="银色头像框", item_type="avatar_frame", price=10, description="低调优雅的银色边框"),
            VirtualItem(name="城市先锋", item_type="title", price=30, description="城市建设先驱者称号"),
            VirtualItem(name="勤劳之星", item_type="title", price=15, description="每日打卡不间断"),
            VirtualItem(name="彩虹徽章", item_type="decoration", price=25, description="七彩缤纷的个人徽章"),
        ])

    await db.commit()
```

---

## 7. WebSocket 事件推送 (M3-9)

复用 `chat.py` 中已有的 `broadcast()` 函数，新增两种 system_event：

**打卡事件**:
```json
{
    "type": "system_event",
    "data": {
        "event": "checkin",
        "agent_id": 1,
        "agent_name": "小明",
        "job_title": "矿工",
        "reward": 8,
        "timestamp": "2026-02-17 10:30:00"
    }
}
```

**购买事件**:
```json
{
    "type": "system_event",
    "data": {
        "event": "purchase",
        "agent_id": 1,
        "agent_name": "小明",
        "item_name": "金色头像框",
        "price": 20,
        "timestamp": "2026-02-17 10:35:00"
    }
}
```

在 `work.py` 和 `shop.py` 的 API handler 中，操作成功后调用：

```python
from ..api.chat import broadcast

await broadcast({
    "type": "system_event",
    "data": { ... }
})
```

---

## 8. 前端变更

### 8.1 岗位面板 JobBoard (M3-7)

- 位置：Info Panel 新增"工作"标签页
- 岗位卡片列表：标题 / 日薪 / 在岗人数 (today_workers/max_workers) / 打卡按钮
- 打卡按钮状态：今日已打卡 → 禁用灰色；岗位满员 → 禁用 + 提示
- 打卡成功 → toast 提示 + 刷新余额

### 8.2 生活面板 LifePanel (M3-7)

- 位置：Info Panel 新增"生活"标签页（或合并到现有 Agent 详情）
- 显示：信用点余额 / 今日打卡状态（岗位名+收入）/ 拥有物品列表
- 数据来源：`GET /api/agents/{id}/balance`（已有）+ `GET /api/work/agents/{id}/today` + `GET /api/shop/agents/{id}/items`

### 8.3 商店面板 ItemShop (M3-8)

- 位置：Info Panel 新增"商店"标签页
- 商品卡片列表：名称 / 类型标签 / 价格 / 购买按钮
- 已拥有商品：购买按钮替换为"已拥有"标签
- 购买成功 → toast 提示 + 刷新余额 + 刷新物品列表

### 8.4 WebSocket 事件监听 (M3-9)

前端 WebSocket 已有 `system_event` 处理逻辑（上线/下线通知），扩展支持：
- `event: "checkin"` → 聊天区显示系统消息 + 刷新 JobBoard 在岗人数
- `event: "purchase"` → 聊天区显示系统消息 + 刷新 ItemShop 已拥有状态

---

## 9. 测试计划

### 9.1 单元测试

| 测试文件 | 测试内容 | 覆盖 AC |
|----------|----------|---------|
| `test_work_service.py` | 正常打卡发薪 | AC-M3-01 |
| | 同日重复打卡被拒 | AC-M3-02 |
| | 岗位满员被拒 | AC-M3-03 |
| | 不同日可再次打卡 | AC-M3-01 |
| | max_workers=0 岗位打卡成功（无限制） | F8.4 |
| | agent_not_found / job_not_found 打卡被拒 | 防御性 |
| | 岗位列表含在岗人数 | AC-M3-10 |
| | get_work_history 默认 7 天 + 自定义 days | — |
| `test_shop_service.py` | 正常购买扣费 | AC-M3-04 |
| | 余额不足被拒 | AC-M3-05 |
| | 重复购买被拒 | AC-M3-06 |
| | agent_not_found / item_not_found 购买被拒 | 防御性 |
| | credits 恰好等于 price 时购买成功 | 边界 |
| | Agent 物品列表正确 | AC-M3-11 |
| `test_seed.py` | seed 幂等性（调用两次不重复） | — |

### 9.2 并发测试 (M3-6)

**文件**: `server/tests/test_work_concurrent.py`

| 场景 | 预期 | 覆盖 AC |
|------|------|---------|
| 10 Agent 并发打卡同一岗位（max_workers=5） | 恰好 5 成功、5 被拒 | AC-M3-09 |
| 同一 Agent 并发打卡 2 次 | 仅 1 次成功 | AC-M3-02 |
| 2 Agent 并发购买同一商品 | 各自成功（不同 agent 可买同一商品） | AC-M3-04 |
| 同一 Agent 并发购买同一商品 | 仅 1 次成功（UNIQUE 约束） | AC-M3-06 |
| 同一 Agent 并发购买两个不同商品（总价超余额） | 仅 1 个成功，credits >= 0（CHECK 约束兜底） | 串讲补充 |
| max_workers=0 岗位并发打卡 10 人 | 全部成功 | F8.4 |

并发实现：`asyncio.gather` + 独立 db session per task。

### 9.3 端到端测试 (M3-10)

| 场景 | 验证 |
|------|------|
| 打卡 → 余额增加 → GET balance 确认 | 经济闭环正向 |
| 打卡 → 购买 → 余额减少 → 物品出现 | 完整闭环 |
| 余额不足购买 → 打卡赚钱 → 再次购买成功 | 闭环驱动力 |
| 打卡事件 WebSocket 推送 | 实时性 |
| 购买事件 WebSocket 推送 | 实时性 |
| WebSocket 事件后查询 API 数据一致 | 收到事件后 GET 确认数据已落盘（串讲补充） |

---

## 10. 数据流

### 10.1 打卡流程

```
Agent 选择岗位 → POST /api/work/jobs/{id}/checkin
  → WorkService.check_in()
    → 校验: Agent 存在 → 今日未打卡 → 岗位未满员
    → 写 CheckIn 记录
    → Agent.credits += daily_reward
    → db.commit()
  → 广播 system_event (checkin)
  → 返回 CheckInResult
```

### 10.2 购买流程

```
Agent 选择商品 → POST /api/shop/purchase
  → ShopService.purchase()
    → 校验: Agent 存在 → 商品存在 → 未重复购买 → 余额充足
    → Agent.credits -= price
    → 写 AgentItem 记录
    → db.commit()
  → 广播 system_event (purchase)
  → 返回 PurchaseResult
```

---

## 11. 风险与应对

| 风险 | 应对 |
|------|------|
| 并发打卡竞态（多人同时打卡满员岗位） | SQLite WAL + 单进程串行写入；check_in 内先查后写在同一事务中 |
| 并发购买竞态（同一 Agent 同一商品） | UNIQUE(agent_id, item_id) 约束兜底，IntegrityError 捕获返回 already_owned |
| 并发购买竞态（同一 Agent 不同商品） | CHECK(credits >= 0) 约束兜底，IntegrityError 捕获返回 insufficient_credits（串讲补充） |
| 打卡日期边界（UTC vs 本地时间） | 统一使用 `date.today()`（服务器本地时间），与 scheduler 一致 |
| seed 数据重复插入 | 仅在表为空时插入，幂等 |
| 前端状态不一致（打卡后未刷新） | WebSocket 事件推送 + 操作后主动刷新 |

---

## 12. 实施顺序

```
Phase 1 (后端服务):
  M3-1 VirtualItem + AgentItem 表 ──┐
  M3-2 WorkService + 岗位 seed ─────┤  可并行
                                     ├→ M3-3 ShopService + 商品 seed
                                     └→ M3-4 REST API + Schema + 路由注册

Phase 2 (定时 + 并发):
  M3-5 每日打卡状态重置 ← M3-2
  M3-6 并发压测 ← M3-4

Phase 3 (前端 + 集成):
  M3-7 JobBoard + LifePanel ← M3-4
  M3-8 ItemShop ← M3-4          可并行
  M3-9 WebSocket 事件推送 ← M3-4
  M3-10 端到端验证 ← M3-7, M3-8, M3-9
```

预计改动量：后端 ~500-700 行新代码（含测试），前端 ~400-600 行新代码。

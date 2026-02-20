# SR — M6 P1.2：策略持久化 + 前端策略面板

> 状态：草稿，待用户确认
> 前置：M6 P1.1（策略扩展）— priority/TTL/4 种策略类型
> 可与 P1.1 并行开发（后端持久化不依赖新策略类型，前端展示等 P1.1 合并后集成测试）

---

## 1. 目标

策略从内存 dict 迁移到 SQLite，重启不丢失。前端新增策略面板，展示每个 Agent 当前活跃策略和执行状态。

## 2. 范围

### 做

- 后端：新建 `AgentStrategy` 表，替换内存 `_strategy_store`
- 后端：策略 CRUD 改为数据库操作（update_strategies / get_strategies / clear_strategies）
- 后端：策略执行日志表 `StrategyLog`（记录每次执行/跳过/完成）
- 前端：Agent 详情区新增"策略"标签页，展示当前策略列表 + 最近执行日志
- API：现有 GET/POST/DELETE `/api/agents/{id}/strategies` 改为读写数据库
- 单元测试 + ST

### 不做

- 事件驱动执行（仍在 hourly tick 内）
- 策略历史回溯（只保留当前活跃策略 + 最近 50 条日志）
- 策略编辑 UI（前端只展示，不提供手动创建/修改策略的表单）

## 3. 任务拆分

### T1：数据库模型 + 迁移

**改动文件：**
- `E:\a3\server\app\models\tables.py`（281 行）— 末尾追加 2 个表
- `E:\a3\server\app\models\__init__.py` — 追加导出

**新增表 1 — AgentStrategy：**
```python
class AgentStrategy(Base):
    __tablename__ = "agent_strategies"

    id = Column(Integer, primary_key=True, autoincrement=True)
    agent_id = Column(Integer, ForeignKey("agents.id"), nullable=False, index=True)
    strategy = Column(String(32), nullable=False)       # keep_working / opportunistic_buy / price_target / stockpile
    # keep_working
    building_id = Column(Integer, nullable=True)
    stop_when_resource = Column(String(32), nullable=True)
    stop_when_amount = Column(Float, nullable=True)
    # opportunistic_buy
    resource = Column(String(32), nullable=True)
    price_below = Column(Float, nullable=True)
    # price_target
    target_price = Column(Float, nullable=True)
    direction = Column(String(8), nullable=True)         # "up" / "down"
    # stockpile
    target_amount = Column(Float, nullable=True)
    buy_price_limit = Column(Float, nullable=True)
    # 通用
    priority = Column(Integer, default=0)
    ttl = Column(Integer, default=3600)
    created_at = Column(DateTime, server_default=func.now())
```

**新增表 2 — StrategyLog：**
```python
class StrategyLog(Base):
    __tablename__ = "strategy_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    agent_id = Column(Integer, ForeignKey("agents.id"), nullable=False, index=True)
    strategy = Column(String(32), nullable=False)
    action = Column(String(16), nullable=False)          # "executed" / "skipped" / "completed" / "expired"
    detail = Column(String(256), nullable=True)           # 可读描述
    created_at = Column(DateTime, server_default=func.now())
```

**`__init__.py` 追加：**
```python
from .tables import AgentStrategy, StrategyLog
```

**验收：**
- [ ] 服务启动后 `agent_strategies` 和 `strategy_logs` 表自动创建
- [ ] 现有表不受影响

---

### T2：strategy_engine.py 改为数据库存储

**改动文件：**
- `E:\a3\server\app\services\strategy_engine.py`（87 行）— 重写存储层

**具体改动：**

删除内存存储（L60-86 的 `_strategy_store` 及相关函数），替换为数据库操作：

```python
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from ..models import AgentStrategy

async def update_strategies(agent_id: int, strategies: list[Strategy], db: AsyncSession):
    """全量覆盖：删除旧策略 → 插入新策略。"""
    await db.execute(delete(AgentStrategy).where(AgentStrategy.agent_id == agent_id))
    for s in strategies:
        if s.agent_id != agent_id:
            continue
        row = AgentStrategy(
            agent_id=agent_id,
            strategy=s.strategy.value,
            building_id=s.building_id,
            stop_when_resource=s.stop_when_resource,
            stop_when_amount=s.stop_when_amount,
            resource=s.resource,
            price_below=s.price_below,
            target_price=s.target_price,
            direction=s.direction,
            target_amount=s.target_amount,
            buy_price_limit=s.buy_price_limit,
            priority=s.priority,
            ttl=s.ttl,
        )
        db.add(row)
    await db.flush()

async def get_strategies(agent_id: int, db: AsyncSession) -> list[Strategy]:
    """从数据库读取某 Agent 当前策略，转为 Strategy 对象。"""
    result = await db.execute(
        select(AgentStrategy).where(AgentStrategy.agent_id == agent_id)
    )
    return [_row_to_strategy(row) for row in result.scalars().all()]

async def get_all_strategies(db: AsyncSession) -> dict[int, list[Strategy]]:
    """读取所有 Agent 策略。"""
    result = await db.execute(select(AgentStrategy))
    by_agent: dict[int, list[Strategy]] = {}
    for row in result.scalars().all():
        by_agent.setdefault(row.agent_id, []).append(_row_to_strategy(row))
    return by_agent

async def clear_strategies(agent_id: int | None = None, db: AsyncSession = None):
    """清空策略。"""
    if agent_id is None:
        await db.execute(delete(AgentStrategy))
    else:
        await db.execute(delete(AgentStrategy).where(AgentStrategy.agent_id == agent_id))
    await db.flush()

def _row_to_strategy(row: AgentStrategy) -> Strategy:
    """ORM 行 → Strategy pydantic 对象。"""
    return Strategy(
        agent_id=row.agent_id,
        strategy=row.strategy,
        building_id=row.building_id,
        stop_when_resource=row.stop_when_resource,
        stop_when_amount=row.stop_when_amount,
        resource=row.resource,
        price_below=row.price_below,
        target_price=row.target_price,
        direction=row.direction,
        target_amount=row.target_amount,
        buy_price_limit=row.buy_price_limit,
        priority=row.priority,
        ttl=row.ttl,
    )
```

**⚠️ 关键：函数签名变了（新增 db 参数），所有调用方需要同步改。**

**验收：**
- [ ] `update_strategies` / `get_strategies` / `clear_strategies` 改为 async + db 参数
- [ ] 内存 `_strategy_store` 完全删除
- [ ] `parse_strategies()` 不变（仍是纯函数，解析 LLM 输出）

---

### T3：调用方适配（autonomy_service + agents API）

**改动文件：**
- `E:\a3\server\app\services\autonomy_service.py` — tick() 函数（L811-853）+ execute_strategies()（L693-808）
- `E:\a3\server\app\api\agents.py` — 策略 API 路由（L94-133）

**autonomy_service.py 改动：**

1. `tick()` 函数（L827-834）策略存储部分：
```python
# 旧：update_strategies(aid, ss)
# 新：await update_strategies(aid, ss, db)
# 需要在 async with async_session() as db: 块内调用
```

2. `execute_strategies()` 函数（L699-702）：
```python
# 旧：all_strategies = get_all_strategies()
# 新：all_strategies = await get_all_strategies(db)
# db 已经是参数，无需额外改动
```

3. `execute_strategies()` 内新增日志写入：每次 executed/skipped/completed 时写 StrategyLog：
```python
from ..models import StrategyLog

# 在每个 stats["executed"] += 1 之后追加：
db.add(StrategyLog(agent_id=aid, strategy=s.strategy.value, action="executed", detail="..."))

# 在每个 stats["completed"] += 1 之后追加：
db.add(StrategyLog(agent_id=aid, strategy=s.strategy.value, action="completed", detail="..."))
```

**agents.py 改动（L94-133）：**

所有策略路由改为 async 调用 + 传 db：
```python
# 旧：strategies = get_strategies(agent_id)
# 新：strategies = await get_strategies(agent_id, db)

# 旧：update_strategies(agent_id, parsed)
# 新：await update_strategies(agent_id, parsed, db); await db.commit()

# 旧：clear_strategies(agent_id)
# 新：await clear_strategies(agent_id, db=db); await db.commit()

# 旧：all_s = get_all_strategies()
# 新：all_s = await get_all_strategies(db)
```

**验收：**
- [ ] tick() 策略存储写入数据库
- [ ] execute_strategies() 从数据库读取策略
- [ ] 策略 API 路由读写数据库
- [ ] StrategyLog 记录每次执行
- [ ] 现有 pytest 全绿（需要更新 test fixture 中的 clear_strategies 调用）

---

### T4：新增策略日志 API

**改动文件：**
- `E:\a3\server\app\api\agents.py`（L133 之后追加）

**新增路由：**
```python
@router.get("/{agent_id}/strategy-logs")
async def get_strategy_logs(agent_id: int, limit: int = 50, db: AsyncSession = Depends(get_db)):
    """获取 Agent 最近策略执行日志。"""
    result = await db.execute(
        select(StrategyLog)
        .where(StrategyLog.agent_id == agent_id)
        .order_by(StrategyLog.created_at.desc())
        .limit(limit)
    )
    return [{"id": r.id, "strategy": r.strategy, "action": r.action,
             "detail": r.detail, "created_at": r.created_at.isoformat()} for r in result.scalars().all()]
```

**验收：**
- [ ] `GET /api/agents/1/strategy-logs` 返回日志列表
- [ ] 默认最多 50 条，按时间倒序

---

### T5：前端策略面板

**改动文件：**
- `E:\a3\web\src\types.ts` — 新增类型
- `E:\a3\web\src\api.ts` — 新增 API 函数
- `E:\a3\web\src\components\AgentStatusPanel.tsx`（43 行）— 扩展展示策略

**types.ts 追加：**
```typescript
export interface AgentStrategy {
  agent_id: number
  strategy: 'keep_working' | 'opportunistic_buy' | 'price_target' | 'stockpile'
  building_id?: number
  stop_when_resource?: string
  stop_when_amount?: number
  resource?: string
  price_below?: number
  target_price?: number
  direction?: 'up' | 'down'
  target_amount?: number
  buy_price_limit?: number
  priority: number
  ttl: number
}

export interface StrategyLog {
  id: number
  strategy: string
  action: 'executed' | 'skipped' | 'completed' | 'expired'
  detail?: string
  created_at: string
}
```

**api.ts 追加：**
```typescript
export async function fetchAgentStrategies(agentId: number): Promise<AgentStrategy[]> {
  const res = await fetch(`${BASE}/agents/${agentId}/strategies`)
  if (!res.ok) throw new Error(`fetchAgentStrategies: ${res.status}`)
  return res.json()
}

export async function fetchStrategyLogs(agentId: number, limit = 20): Promise<StrategyLog[]> {
  const res = await fetch(`${BASE}/agents/${agentId}/strategy-logs?limit=${limit}`)
  if (!res.ok) throw new Error(`fetchStrategyLogs: ${res.status}`)
  return res.json()
}
```

**AgentStatusPanel.tsx 改动：**

在每个 agent-status-item 下方，展开时显示策略列表：
- 点击 agent 名字展开/收起
- 展开后显示：当前策略（类型 + 关键参数 + 进度）+ 最近 5 条执行日志
- 策略类型用中文标签：keep_working=持续工作 / opportunistic_buy=低价扫货 / price_target=价格操控 / stockpile=囤积资源
- 日志用小字灰色显示

**验收：**
- [ ] 前端类型与后端 API 返回字段一致
- [ ] 点击 Agent 展开策略面板
- [ ] 策略列表正确显示类型和参数
- [ ] 执行日志按时间倒序显示

---

### T6：测试

**改动文件：**
- `E:\a3\server\tests\test_m6_strategy.py` — 更新现有测试（内存→数据库）
- `E:\a3\server\tests\test_m6_strategy.py` — 追加持久化测试

**现有测试适配：**
所有调用 `update_strategies` / `get_strategies` / `clear_strategies` 的测试需要改为 async + 传 db fixture。

**新增测试用例：**
```
test_strategy_persists_after_session_close  — 写入策略 → 关闭 session → 新 session 读取 → 策略仍在
test_strategy_log_recorded_on_execute       — execute_strategies 后 strategy_logs 表有记录
test_strategy_log_api_returns_recent        — GET /api/agents/1/strategy-logs 返回正确日志
test_clear_strategies_deletes_from_db       — clear 后数据库无记录
test_update_strategies_overwrites           — 第二次 update 覆盖第一次
```

**验收：**
- [ ] 现有 20+ 测试适配后全绿
- [ ] 新增 ≥5 个持久化测试
- [ ] `pytest server/tests/test_m6_strategy.py` 全绿

---

## 4. 阶段门禁

| 门禁 | 条件 |
|------|------|
| T1 → T2 | 表创建成功，服务启动不报错 |
| T2 → T3 | strategy_engine 新函数单独测试通过 |
| T3 → T4 | tick() + execute_strategies + API 路由全部适配，pytest 全绿 |
| T4 → T5 | 日志 API 测试通过 |
| T5 → T6 | 前端编译通过，手动验证策略面板显示 |
| T6 → 完成 | pytest 全绿 + 现有 ST 不回归 + Code Review P0/P1 归零 |

## 5. 不改动的文件（确认）

| 文件 | 原因 |
|------|------|
| `scheduler.py` | tick 调度不变 |
| `config.py` | 无新配置项 |
| `market_service.py` | 不涉及 |
| `work_service.py` | 不涉及 |
| `web_tools.py` | P1.2 不涉及上网工具 |

## 6. 文件路径速查

| 文件 | 路径 | 操作 |
|------|------|------|
| tables.py | `E:\a3\server\app\models\tables.py` | 改：追加 2 个表 ~30 行 |
| __init__.py | `E:\a3\server\app\models\__init__.py` | 改：追加 2 个导出 |
| strategy_engine.py | `E:\a3\server\app\services\strategy_engine.py` | 改：重写存储层 ~80 行 |
| autonomy_service.py | `E:\a3\server\app\services\autonomy_service.py` | 改：tick() + execute_strategies 适配 ~20 行 |
| agents.py | `E:\a3\server\app\api\agents.py` | 改：策略路由适配 + 新增日志路由 ~30 行 |
| types.ts | `E:\a3\web\src\types.ts` | 改：追加 2 个接口 ~20 行 |
| api.ts | `E:\a3\web\src\api.ts` | 改：追加 2 个函数 ~15 行 |
| AgentStatusPanel.tsx | `E:\a3\web\src\components\AgentStatusPanel.tsx` | 改：扩展策略展示 ~50 行 |
| test_m6_strategy.py | `E:\a3\server\tests\test_m6_strategy.py` | 改：适配 + 新增 ~60 行 |

**参考文件（只读，用于对齐格式）：**

| 文件 | 路径 | 参考什么 |
|------|------|----------|
| tables.py | `E:\a3\server\app\models\tables.py` | 现有表定义格式（MarketOrder L253-265） |
| agents.py | `E:\a3\server\app\api\agents.py` | 现有策略路由格式（L94-133） |
| AgentStatusPanel.tsx | `E:\a3\web\src\components\AgentStatusPanel.tsx` | 现有 Agent 状态展示格式 |
| types.ts | `E:\a3\web\src\types.ts` | 现有类型定义风格 |
| api.ts | `E:\a3\web\src\api.ts` | 现有 API 函数风格 |
| test_m6_strategy.py | `E:\a3\server\tests\test_m6_strategy.py` | 现有测试 fixture（L19-38） |

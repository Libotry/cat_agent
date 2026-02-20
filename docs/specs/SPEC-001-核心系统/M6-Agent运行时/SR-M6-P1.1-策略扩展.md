# SR — M6 P1.1：策略类型扩展 + 模型补全

> 状态：草稿，待用户确认
> 前置：M6 Phase 1（策略自动机）✅ 已完成（keep_working + opportunistic_buy）

---

## 1. 目标

在 P1 的 2 种策略基础上，补全 IR 规划的 4 种策略类型 + priority/TTL 字段，让策略自动机具备完整的决策表达能力。

## 2. 范围

### 做

- 新增策略类型：`price_target`（价格目标）+ `stockpile`（囤积资源）
- Strategy 模型新增 `priority: int` + `ttl: int` 字段
- 执行引擎：priority 排序 + TTL 过期跳过 + 两种新策略的条件匹配/执行逻辑
- SYSTEM_PROMPT 补充新策略 few-shot 示例
- 单元测试 + 现有 ST 不回归

### 不做

- 策略持久化（P1.2 做）
- 前端展示（P1.2 做）
- 事件驱动执行（仍在 hourly tick 内执行）

## 3. 设计决策（已从 IR 继承，无需再确认）

| 决策 | 结论 | 来源 |
|------|------|------|
| 策略类型枚举 | keep_working / opportunistic_buy / price_target / stockpile | IR 议题 2b |
| priority | int，数字越小优先级越高，默认 0 | IR 共识 |
| TTL | 秒，默认 3600（下次 tick 前过期），LLM 可续期 | IR 共识 |
| 策略格式 | 极简扁平，不嵌套 | IR + SR-P1 |

## 4. 新增策略类型定义

### price_target — 价格目标

Agent 说"把小麦粉价格拉到 2.0"，自动机持续挂单直到市场均价达标。

```json
{"agent_id": 1, "strategy": "price_target", "resource": "flour", "target_price": 2.0, "direction": "up", "stop_when_amount": 0}
```

执行逻辑：
- `direction = "up"`：挂卖单，价格 = target_price，直到市场最低卖价 >= target_price
- `direction = "down"`：挂买单，价格 = target_price，直到市场最高买价 <= target_price
- 终止条件：市场价达标 或 TTL 过期 或 自身资源耗尽

### stockpile — 囤积资源

Agent 说"囤积 100 小麦，工作+购买都行"，自动机同时尝试 checkin 和接低价单。

```json
{"agent_id": 1, "strategy": "stockpile", "resource": "wheat", "target_amount": 100, "building_id": 1, "buy_price_limit": 1.5}
```

执行逻辑：
- 如果在目标建筑 → checkin 生产
- 同时扫描市场低价单 → 接单购买
- 终止条件：资源 >= target_amount

## 5. 任务拆分

### T1：Strategy 模型扩展

**改动文件：**
- `E:\a3\server\app\services\strategy_engine.py`（87 行）

**AR — 完整改动代码：**

**改动 1**：StrategyType 枚举（替换 L16-18）：
```python
class StrategyType(str, Enum):
    KEEP_WORKING = "keep_working"
    OPPORTUNISTIC_BUY = "opportunistic_buy"
    PRICE_TARGET = "price_target"
    STOCKPILE = "stockpile"
```

**改动 2**：Strategy BaseModel（替换 L21-45），保留现有字段，追加新字段：
```python
class Strategy(BaseModel):
    """极简扁平策略，LLM 输出一条 = 一个 Strategy。"""
    agent_id: int
    strategy: StrategyType
    # keep_working 字段
    building_id: Optional[int] = None
    stop_when_resource: Optional[str] = None
    stop_when_amount: Optional[float] = None
    # opportunistic_buy 字段
    resource: Optional[str] = None
    price_below: Optional[float] = None
    # price_target 字段（P1.1 新增）
    target_price: Optional[float] = None
    direction: Optional[str] = None       # "up" | "down"
    # stockpile 字段（P1.1 新增）
    target_amount: Optional[float] = None
    buy_price_limit: Optional[float] = None
    # 通用字段（P1.1 新增）
    priority: int = 0                     # 越小越优先
    ttl: int = 3600                       # 秒，默认 1 小时
    created_at: Optional[float] = None    # time.time()，用于 TTL 计算

    @field_validator("building_id", mode="before")
    @classmethod
    def coerce_building_id(cls, v):
        if v is None:
            return v
        return int(v)

    @field_validator("price_below", "stop_when_amount", "target_price", "target_amount", "buy_price_limit", mode="before")
    @classmethod
    def coerce_float(cls, v):
        if v is None:
            return v
        return float(v)
```

**改动 3**：parse_strategies（替换 L48-57），自动填充 created_at：
```python
import time

def parse_strategies(raw_list: list[dict]) -> list[Strategy]:
    """从 LLM 输出的 JSON 列表解析策略，跳过不合法的条目。"""
    valid = []
    now = time.time()
    for item in raw_list:
        try:
            s = Strategy(**item)
            if s.created_at is None:
                s.created_at = now
            valid.append(s)
        except Exception as e:
            logger.warning("Strategy parse failed: %s, item=%s", e, item)
    return valid
```

**验收：**
- [ ] `Strategy(strategy="price_target", agent_id=1, resource="flour", target_price=2.0, direction="up")` 解析成功
- [ ] `Strategy(strategy="stockpile", agent_id=1, resource="wheat", target_amount=100, building_id=1, buy_price_limit=1.5)` 解析成功
- [ ] `priority` 默认 0，`ttl` 默认 3600
- [ ] `parse_strategies([...])` 自动填充 `created_at`
- [ ] 现有 keep_working / opportunistic_buy 解析不受影响

---

### T2：执行引擎扩展

**改动文件：**
- `E:\a3\server\app\services\autonomy_service.py` — `execute_strategies()` 函数（L693-808）

**AR — 完整改动代码：**

**改动 1**：在 L698 追加 import：
```python
from .market_service import list_orders, accept_order, create_order
```
（现有只 import 了 `list_orders, accept_order`，需要加 `create_order`）

**改动 2**：在 L731（`for aid, strategies in all_strategies.items():` 内部），L737 `for s in strategies:` 之前，插入 priority 排序 + TTL 过滤：
```python
        # P1.1: priority 排序（小的先执行）+ TTL 过期过滤
        import time as _time
        _now = _time.time()
        strategies = sorted(strategies, key=lambda s: s.priority)
        strategies = [s for s in strategies if s.created_at is None or (_now - s.created_at) < s.ttl]
```

**改动 3**：在 L801（`if not bought: stats["skipped"] += 1` 之后，`except` 之前），追加两个完整分支：

```python
                elif s.strategy == StrategyType.PRICE_TARGET:
                    # 终止条件：检查市场价是否达标
                    if s.resource and s.target_price is not None and s.direction:
                        relevant = [o for o in open_orders if o["sell_type"] == s.resource
                                    and o["remain_sell_amount"] > 0 and o["seller_id"] != aid]
                        if s.direction == "up":
                            # 目标：市场最低卖价 >= target_price
                            if relevant:
                                min_price = min(o["remain_buy_amount"] / o["remain_sell_amount"] for o in relevant)
                                if min_price >= s.target_price:
                                    logger.info("Strategy completed: agent %s price_target up, %s price %.2f >= %.2f",
                                                agent_name, s.resource, min_price, s.target_price)
                                    stats["completed"] += 1
                                    continue
                            else:
                                # 无卖单 = 价格无穷高，视为达标
                                stats["completed"] += 1
                                continue
                            # 执行：挂高价卖单（把自己的资源以 target_price 挂出）
                            my_amount = my_resources.get(s.resource, 0)
                            if my_amount >= 1.0:
                                sell_qty = min(my_amount, 10.0)  # 每轮最多挂 10 单位
                                buy_qty = sell_qty * s.target_price  # 以 credits 计价
                                res = await create_order(aid, s.resource, sell_qty, "credits", buy_qty, db=db)
                                if res["ok"]:
                                    stats["executed"] += 1
                                    my_resources[s.resource] = my_amount - sell_qty
                                    await _broadcast_action(agent_name, aid, "create_market_order",
                                                            f"策略自动执行: 挂卖 {s.resource} @{s.target_price}")
                                else:
                                    stats["skipped"] += 1
                            else:
                                stats["skipped"] += 1

                        elif s.direction == "down":
                            # 目标：市场最低卖价 <= target_price（压低价格）
                            if relevant:
                                min_price = min(o["remain_buy_amount"] / o["remain_sell_amount"] for o in relevant)
                                if min_price <= s.target_price:
                                    stats["completed"] += 1
                                    continue
                            # 执行：挂低价卖单
                            my_amount = my_resources.get(s.resource, 0)
                            if my_amount >= 1.0:
                                sell_qty = min(my_amount, 10.0)
                                buy_qty = sell_qty * s.target_price
                                res = await create_order(aid, s.resource, sell_qty, "credits", buy_qty, db=db)
                                if res["ok"]:
                                    stats["executed"] += 1
                                    my_resources[s.resource] = my_amount - sell_qty
                                    await _broadcast_action(agent_name, aid, "create_market_order",
                                                            f"策略自动执行: 低价挂卖 {s.resource} @{s.target_price}")
                                else:
                                    stats["skipped"] += 1
                            else:
                                stats["skipped"] += 1
                        else:
                            stats["skipped"] += 1
                    else:
                        stats["skipped"] += 1

                elif s.strategy == StrategyType.STOCKPILE:
                    # 终止条件：资源达标
                    if s.resource and s.target_amount is not None:
                        current = my_resources.get(s.resource, 0)
                        if current >= s.target_amount:
                            logger.info("Strategy completed: agent %s stockpile, %s reached %.1f",
                                        agent_name, s.resource, current)
                            stats["completed"] += 1
                            continue

                    acted = False
                    # 执行 1：如果在目标建筑 → checkin（生产资源）
                    if s.building_id and agent_building.get(aid) == s.building_id:
                        jobs = await work_service.get_jobs(db)
                        available = [j for j in jobs if j["max_workers"] == 0 or j["today_workers"] < j["max_workers"]]
                        if available:
                            res = await work_service.check_in(aid, random.choice(available)["id"], db)
                            if res["ok"]:
                                stats["executed"] += 1
                                await _broadcast_action(agent_name, aid, "checkin", f"策略自动执行: 囤积 {s.resource} — 生产")
                                acted = True

                    # 执行 2：扫描市场低价单 → 接单购买
                    if s.resource and s.buy_price_limit is not None:
                        for order in open_orders:
                            if (order["sell_type"] == s.resource
                                    and order["remain_sell_amount"] > 0
                                    and order["remain_buy_amount"] > 0
                                    and order["seller_id"] != aid):
                                unit_price = order["remain_buy_amount"] / order["remain_sell_amount"]
                                if unit_price <= s.buy_price_limit:
                                    pay_resource = order["buy_type"]
                                    pay_amount = order["remain_buy_amount"]
                                    my_pay = my_resources.get(pay_resource, 0)
                                    if my_pay >= pay_amount:
                                        res = await accept_order(aid, order["id"], 1.0, db=db)
                                        if res["ok"]:
                                            stats["executed"] += 1
                                            my_resources[s.resource] = my_resources.get(s.resource, 0) + order["remain_sell_amount"]
                                            my_resources[pay_resource] = my_pay - pay_amount
                                            await _broadcast_action(agent_name, aid, "accept_market_order",
                                                                    f"策略自动执行: 囤积 {s.resource} — 买入")
                                            acted = True
                                            break  # 每轮只买一单

                    if not acted:
                        stats["skipped"] += 1
```

**验收：**
- [ ] 策略按 priority 排序执行（priority=0 先于 priority=1）
- [ ] TTL 过期的策略被跳过（created_at + ttl < now）
- [ ] price_target direction="up"：挂卖单，sell_type=resource, buy_type="credits", 单价=target_price
- [ ] price_target direction="up"：市场最低卖价 >= target_price → completed
- [ ] price_target direction="down"：挂低价卖单压低市场价
- [ ] stockpile：在目标建筑时 checkin 生产
- [ ] stockpile：同时扫描市场低价单接单购买
- [ ] stockpile：资源 >= target_amount → completed
- [ ] 现有 keep_working / opportunistic_buy 行为不变（代码未修改）

---

### T3：SYSTEM_PROMPT 更新

**改动文件：**
- `E:\a3\server\app\services\autonomy_service.py` — `SYSTEM_PROMPT`（L35-85）

**AR — 完整改动代码：**

**改动 1**：在 L54-56（策略类型定义 `- opportunistic_buy：...` 之后）追加两行：
```
- price_target：操控市场价格，持续挂单直到市场均价达到目标价
- stockpile：囤积资源，同时通过工作生产和市场低价购买来积累
```

**改动 2**：在 L72（opportunistic_buy 强制规则之后）追加：
```
★ price_target 触发条件（全部满足时必须设置）：
  1. 居民拥有某资源数量 > 30（有富余可操作市场）
  2. 市场该资源当前最低卖价与居民期望价差距 > 20%
  → 必须设 price_target 策略
  → 示例：Charlie 资源=[flour=50]，市场 flour 最低卖价=1.0，期望拉到 2.0 →
    {"agent_id":3, "strategy":"price_target", "resource":"flour", "target_price":2.0, "direction":"up", "priority":1, "ttl":7200}

★ stockpile 触发条件（全部满足时必须设置）：
  1. 居民某资源 < 10 且 在岗某建筑（可生产）
  2. 市场有该资源挂单（可购买）
  → 必须设 stockpile 策略（同时工作+买入，比单一 keep_working 或 opportunistic_buy 更高效）
  → 示例：Dave 在农场[在岗]，wheat=5，市场有卖 wheat 挂单 →
    {"agent_id":4, "strategy":"stockpile", "resource":"wheat", "target_amount":100, "building_id":1, "buy_price_limit":1.5}
```

**改动 3**：在 L83（strategy 格式示例末尾）追加两行示例：
```
{"agent_id": 3, "strategy": "price_target", "resource": "flour", "target_price": 2.0, "direction": "up", "priority": 1, "ttl": 7200}
{"agent_id": 4, "strategy": "stockpile", "resource": "wheat", "target_amount": 100, "building_id": 1, "buy_price_limit": 1.5}
```

**改动 4**：在 L75（`每个居民最多 2 条策略` 之后）追加 priority/ttl 说明：
```
策略可带 priority（默认 0，越小越优先）和 ttl（默认 3600 秒，过期自动失效）
```

**验收：**
- [ ] SYSTEM_PROMPT 包含 4 种策略类型定义（keep_working / opportunistic_buy / price_target / stockpile）
- [ ] 每种策略有明确的触发条件 + 完整示例 JSON
- [ ] 示例 JSON 包含 priority 和 ttl 字段

---

### T4：单元测试

**改动文件：**
- `E:\a3\server\tests\test_m6_strategy.py`（422 行）— 追加测试

**新增测试用例：**

```
# T1 Schema 测试
test_parse_price_target          — price_target 解析成功，字段正确
test_parse_stockpile             — stockpile 解析成功，字段正确
test_priority_default_zero       — 不传 priority 默认 0
test_ttl_default_3600            — 不传 ttl 默认 3600
test_created_at_auto_filled      — parse_strategies 自动填充 created_at

# T2 执行引擎测试
test_priority_ordering           — priority=1 的策略在 priority=0 之后执行
test_ttl_expired_skipped         — created_at 超过 ttl 的策略被跳过
test_price_target_creates_sell_order  — direction="up" 挂卖单
test_price_target_completes_when_price_reached — 市场价达标 → completed
test_stockpile_checkin_and_buy   — 同时 checkin + 接低价单
test_stockpile_completes_when_enough — 资源达标 → completed

# 回归测试
test_keep_working_still_works    — 现有 keep_working 行为不变
test_opportunistic_buy_still_works — 现有 opportunistic_buy 行为不变
```

**验收：**
- [ ] 新增 ≥10 个测试用例
- [ ] `pytest server/tests/test_m6_strategy.py` 全绿
- [ ] 现有 20 个测试不回归

---

## 6. 阶段门禁

| 门禁 | 条件 |
|------|------|
| T1 → T2 | Schema 测试全绿 |
| T2 → T3 | 执行引擎测试全绿（含 priority/TTL） |
| T3 → T4 | SYSTEM_PROMPT 改完，手动检查格式 |
| T4 → 完成 | pytest 全绿 + 现有 ST 不回归 |

## 7. 不改动的文件（确认）

| 文件 | 原因 |
|------|------|
| `agents.py`（API 路由） | 观测 API 已支持任意策略类型，无需改 |
| `scheduler.py` | tick 调度不变 |
| `config.py` | 无新配置项 |
| `前端所有文件` | P1.1 不涉及前端 |
| `strategy_engine.py` 的存储函数 | update/get/clear 逻辑不变，只是 Strategy 模型变了 |

## 8. 文件路径速查

| 文件 | 路径 | 操作 |
|------|------|------|
| strategy_engine.py | `E:\a3\server\app\services\strategy_engine.py` | 改：模型扩展 ~30 行 |
| autonomy_service.py | `E:\a3\server\app\services\autonomy_service.py` | 改：execute_strategies ~60 行 + SYSTEM_PROMPT ~20 行 |
| test_m6_strategy.py | `E:\a3\server\tests\test_m6_strategy.py` | 改：追加 ~120 行测试 |

**参考文件（只读，用于对齐格式）：**

| 文件 | 路径 | 参考什么 |
|------|------|----------|
| strategy_engine.py | `E:\a3\server\app\services\strategy_engine.py` | 现有 Strategy 模型结构（L21-45） |
| autonomy_service.py | `E:\a3\server\app\services\autonomy_service.py` | execute_strategies 现有分支格式（L739-801） |
| autonomy_service.py | `E:\a3\server\app\services\autonomy_service.py` | SYSTEM_PROMPT 现有格式（L35-85） |
| test_m6_strategy.py | `E:\a3\server\tests\test_m6_strategy.py` | 测试 fixture 和 mock 模式（L19-38） |
| market_service.py | `E:\a3\server\app\services\market_service.py` | create_order / list_orders 函数签名（price_target 需要调用） |

# TEST-M3: 城市经济闭环 测试用例文档

**关联设计**: TDD-M3-城市经济
**关联需求**: 01-需求原型.md §M3 (US-M3-1~6, F8~F10, AC-M3-01~11)
**编写角色**: QA Lead
**编写日期**: 2026-02-17

---

## 测试范围

按 TDD-M3 模块划分测试范围：

| 层级 | 功能 | 测试类型 | 用例数 |
|------|------|----------|--------|
| UT | WorkService 打卡逻辑 + ShopService 购买逻辑 + seed 幂等 | 单元测试 | 18 |
| 并发 | 打卡/购买竞态条件 | 并发测试 | 6 |
| E2E | 打卡→余额→购买 完整闭环 + WebSocket 事件 | 端到端测试 | 6 |

---

## UT 层：单元测试（18 个用例）

### U1: 正常打卡发薪

- **覆盖 AC**: AC-M3-01
- **优先级**: P0
- **Given**: Agent(id=1, credits=100) 存在；Job(id=1, title="矿工", daily_reward=8, max_workers=5) 存在；今日无打卡记录
- **When**: 调用 `work_service.check_in(agent_id=1, job_id=1, db)`
- **Then**:
  - 返回 `{"ok": True, "reason": "success", "reward": 8, "checkin_id": <int>}`
  - Agent.credits 变为 108
  - CheckIn 表新增一条记录（agent_id=1, job_id=1, reward=8）
- **测试数据**: Agent(credits=100), Job(daily_reward=8, max_workers=5)

### U2: 同日重复打卡被拒

- **覆盖 AC**: AC-M3-02
- **优先级**: P0
- **Given**: Agent(id=1) 今日已在 Job(id=1) 打卡
- **When**: 调用 `work_service.check_in(agent_id=1, job_id=2, db)`（尝试打卡另一个岗位）
- **Then**:
  - 返回 `{"ok": False, "reason": "already_checked_in", "reward": 0}`
  - Agent.credits 不变
- **测试数据**: Agent(credits=100), 今日已有 CheckIn 记录

### U3: 岗位满员被拒

- **覆盖 AC**: AC-M3-03
- **优先级**: P0
- **Given**: Job(id=1, max_workers=2) 今日已有 2 个不同 Agent 打卡
- **When**: Agent(id=3) 调用 `work_service.check_in(agent_id=3, job_id=1, db)`
- **Then**:
  - 返回 `{"ok": False, "reason": "job_full", "reward": 0}`
  - Agent(id=3).credits 不变
- **测试数据**: Job(max_workers=2), 2 条今日 CheckIn 记录

### U4: 不同日再次打卡

- **覆盖 AC**: AC-M3-01
- **优先级**: P1
- **Given**: Agent(id=1) 昨日已打卡 Job(id=1)；今日无打卡记录
- **When**: 调用 `work_service.check_in(agent_id=1, job_id=1, db)`
- **Then**:
  - 返回 `{"ok": True, "reason": "success", "reward": 8}`
  - Agent.credits 增加 8
- **测试数据**: Agent(credits=100), 昨日 CheckIn 记录（通过手动设置 checked_at）

### U5: max_workers=0 岗位打卡成功

- **覆盖 AC**: F8.4
- **优先级**: P1
- **Given**: Job(id=1, max_workers=0, daily_reward=10) 存在；Agent(id=1) 今日未打卡
- **When**: 调用 `work_service.check_in(agent_id=1, job_id=1, db)`
- **Then**:
  - 返回 `{"ok": True, "reason": "success", "reward": 10}`
  - 不执行容量检查（max_workers=0 跳过）
- **测试数据**: Job(max_workers=0, daily_reward=10)

### U6: max_workers=0 多人打卡全部成功

- **覆盖 AC**: F8.4
- **优先级**: P1
- **Given**: Job(id=1, max_workers=0) 存在；Agent(id=1~10) 共 10 个 Agent，今日均未打卡
- **When**: 依次调用 `work_service.check_in(agent_id=i, job_id=1, db)` (i=1..10)
- **Then**:
  - 10 次调用全部返回 `{"ok": True}`
  - 10 个 Agent 的 credits 均增加 daily_reward
- **测试数据**: Job(max_workers=0), 10 个 Agent

### U7: 岗位列表含 today_workers

- **覆盖 AC**: AC-M3-10
- **优先级**: P1
- **Given**: Job(id=1, max_workers=5) 今日有 3 个 Agent 打卡；Job(id=2) 今日无人打卡
- **When**: 调用 `work_service.get_jobs(db)`
- **Then**:
  - Job(id=1) 的 today_workers=3
  - Job(id=2) 的 today_workers=0
- **测试数据**: 2 个 Job, 3 条今日 CheckIn 记录

### U8: agent_not_found 打卡被拒

- **覆盖 AC**: 防御性
- **优先级**: P1
- **Given**: 数据库中不存在 agent_id=999
- **When**: 调用 `work_service.check_in(agent_id=999, job_id=1, db)`
- **Then**: 返回 `{"ok": False, "reason": "agent_not_found", "reward": 0}`
- **测试数据**: 不创建 Agent, Job(id=1) 存在

### U9: job_not_found 打卡被拒

- **覆盖 AC**: 防御性
- **优先级**: P1
- **Given**: Agent(id=1) 存在；数据库中不存在 job_id=999
- **When**: 调用 `work_service.check_in(agent_id=1, job_id=999, db)`
- **Then**: 返回 `{"ok": False, "reason": "job_not_found", "reward": 0}`
- **测试数据**: Agent(id=1) 存在, 不创建对应 Job

### U10: 正常购买扣费

- **覆盖 AC**: AC-M3-04
- **优先级**: P0
- **Given**: Agent(id=1, credits=50) 存在；VirtualItem(id=1, name="金色头像框", price=20) 存在；Agent 未拥有该商品
- **When**: 调用 `shop_service.purchase(agent_id=1, item_id=1, db)`
- **Then**:
  - 返回 `{"ok": True, "reason": "success", "item_name": "金色头像框", "price": 20, "remaining_credits": 30}`
  - Agent.credits 变为 30
  - AgentItem 表新增一条记录（agent_id=1, item_id=1）
- **测试数据**: Agent(credits=50), VirtualItem(price=20)

### U11: 余额不足被拒

- **覆盖 AC**: AC-M3-05
- **优先级**: P0
- **Given**: Agent(id=1, credits=10) 存在；VirtualItem(id=1, price=20) 存在
- **When**: 调用 `shop_service.purchase(agent_id=1, item_id=1, db)`
- **Then**:
  - 返回 `{"ok": False, "reason": "insufficient_credits"}`
  - Agent.credits 仍为 10
- **测试数据**: Agent(credits=10), VirtualItem(price=20)

### U12: 重复购买被拒

- **覆盖 AC**: AC-M3-06
- **优先级**: P0
- **Given**: Agent(id=1, credits=100) 已拥有 VirtualItem(id=1)（AgentItem 记录已存在）
- **When**: 调用 `shop_service.purchase(agent_id=1, item_id=1, db)`
- **Then**:
  - 返回 `{"ok": False, "reason": "already_owned"}`
  - Agent.credits 不变
- **测试数据**: Agent(credits=100), 已有 AgentItem(agent_id=1, item_id=1)

### U13: Agent 物品列表正确

- **覆盖 AC**: AC-M3-11
- **优先级**: P1
- **Given**: Agent(id=1) 拥有 VirtualItem(id=1, name="金色头像框", item_type="avatar_frame") 和 VirtualItem(id=2, name="勤劳之星", item_type="title")
- **When**: 调用 `shop_service.get_agent_items(agent_id=1, db)`
- **Then**:
  - 返回列表长度为 2
  - 包含 `{"item_id": 1, "name": "金色头像框", "item_type": "avatar_frame", "purchased_at": <str>}`
  - 包含 `{"item_id": 2, "name": "勤劳之星", "item_type": "title", "purchased_at": <str>}`
- **测试数据**: 2 个 VirtualItem, 2 条 AgentItem 记录

### U14: agent_not_found 购买被拒

- **覆盖 AC**: 防御性
- **优先级**: P1
- **Given**: 数据库中不存在 agent_id=999；VirtualItem(id=1) 存在
- **When**: 调用 `shop_service.purchase(agent_id=999, item_id=1, db)`
- **Then**: 返回 `{"ok": False, "reason": "agent_not_found"}`
- **测试数据**: 不创建 Agent, VirtualItem(id=1) 存在

### U15: item_not_found 购买被拒

- **覆盖 AC**: 防御性
- **优先级**: P1
- **Given**: Agent(id=1) 存在；数据库中不存在 item_id=999
- **When**: 调用 `shop_service.purchase(agent_id=1, item_id=999, db)`
- **Then**: 返回 `{"ok": False, "reason": "item_not_found"}`
- **测试数据**: Agent(id=1) 存在, 不创建对应 VirtualItem

### U16: get_work_history 默认 7 天

- **覆盖 AC**: --
- **优先级**: P2
- **Given**: Agent(id=1) 有 10 天内的打卡记录：3 条在最近 7 天内，2 条在 8~10 天前
- **When**: 调用 `work_service.get_work_history(agent_id=1, db)`（不传 days 参数）
- **Then**:
  - 返回列表长度为 3（仅最近 7 天）
  - 按 checked_at 降序排列
- **测试数据**: 5 条 CheckIn 记录，手动设置 checked_at 跨越 10 天

### U17: get_work_history 自定义 days

- **覆盖 AC**: --
- **优先级**: P2
- **Given**: Agent(id=1) 有 10 天内的打卡记录：3 条在最近 3 天内，2 条在 4~10 天前
- **When**: 调用 `work_service.get_work_history(agent_id=1, db, days=3)`
- **Then**:
  - 返回列表长度为 3（仅最近 3 天）
  - 按 checked_at 降序排列
- **测试数据**: 5 条 CheckIn 记录，手动设置 checked_at

### U18: seed 幂等性

- **覆盖 AC**: --
- **优先级**: P1
- **Given**: 空数据库
- **When**: 调用 `seed_jobs_and_items(db)` 两次
- **Then**:
  - Job 表记录数 = 5（不重复插入）
  - VirtualItem 表记录数 = 5（不重复插入）
  - 第二次调用不抛异常
- **测试数据**: 空数据库，seed 函数调用两次

---

## 并发层：并发测试（6 个用例）

> 并发实现方式：`asyncio.gather` + 每个任务独立 db session。

### C1: 10 Agent 并发打卡 max_workers=5

- **覆盖 AC**: AC-M3-09
- **优先级**: P0
- **Given**: Job(id=1, max_workers=5) 存在；Agent(id=1~10) 共 10 个 Agent，今日均未打卡
- **When**: 10 个协程并发调用 `work_service.check_in(agent_id=i, job_id=1, db_i)` (i=1..10)
- **Then**:
  - 恰好 5 个返回 `{"ok": True}`
  - 恰好 5 个返回 `{"ok": False, "reason": "job_full"}`
  - CheckIn 表中 job_id=1 的今日记录恰好 5 条
  - 无死锁、无异常
- **测试数据**: Job(max_workers=5), 10 个 Agent, 10 个独立 session

### C2: 同一 Agent 并发打卡 2 次

- **覆盖 AC**: AC-M3-02
- **优先级**: P0
- **Given**: Agent(id=1) 存在；Job(id=1) 存在；今日未打卡
- **When**: 2 个协程并发调用 `work_service.check_in(agent_id=1, job_id=1, db_i)` (i=1,2)
- **Then**:
  - 恰好 1 个返回 `{"ok": True}`
  - 恰好 1 个返回 `{"ok": False, "reason": "already_checked_in"}`
  - CheckIn 表中 agent_id=1 的今日记录恰好 1 条
- **测试数据**: 1 个 Agent, 1 个 Job, 2 个独立 session

### C3: 2 不同 Agent 并发购买同一商品

- **覆盖 AC**: AC-M3-04
- **优先级**: P1
- **Given**: Agent(id=1, credits=50) 和 Agent(id=2, credits=50) 存在；VirtualItem(id=1, price=20) 存在
- **When**: 2 个协程并发调用 `shop_service.purchase(agent_id=i, item_id=1, db_i)` (i=1,2)
- **Then**:
  - 2 个均返回 `{"ok": True}`（不同 Agent 可买同一商品）
  - AgentItem 表有 2 条记录
  - 两个 Agent 的 credits 各减少 20
- **测试数据**: 2 个 Agent(credits=50), 1 个 VirtualItem(price=20), 2 个独立 session

### C4: 同一 Agent 并发购买同一商品

- **覆盖 AC**: AC-M3-06
- **优先级**: P0
- **Given**: Agent(id=1, credits=100) 存在；VirtualItem(id=1, price=20) 存在；Agent 未拥有该商品
- **When**: 2 个协程并发调用 `shop_service.purchase(agent_id=1, item_id=1, db_i)` (i=1,2)
- **Then**:
  - 恰好 1 个返回 `{"ok": True}`
  - 恰好 1 个返回 `{"ok": False, "reason": "already_owned"}`（或 IntegrityError 被捕获后返回 already_owned）
  - AgentItem 表中 (agent_id=1, item_id=1) 恰好 1 条（UNIQUE 约束兜底）
  - Agent.credits 仅扣减一次
- **测试数据**: 1 个 Agent(credits=100), 1 个 VirtualItem(price=20), 2 个独立 session

### C5: 同一 Agent 并发购买两个不同商品（总价超余额）

- **覆盖 AC**: 串讲补充（credits >= 0 CHECK 约束）
- **优先级**: P1
- **Given**: Agent(id=1, credits=30) 存在；VirtualItem(id=1, price=20) 和 VirtualItem(id=2, price=25) 存在
- **When**: 2 个协程并发调用 `shop_service.purchase(agent_id=1, item_id=i, db_i)` (i=1,2)
- **Then**:
  - 至多 1 个返回 `{"ok": True}`（余额只够买一件）
  - 另一个返回 `{"ok": False, "reason": "insufficient_credits"}`（或 IntegrityError 被 CHECK 约束拦截）
  - Agent.credits >= 0（CHECK 约束兜底，不会出现负数）
- **测试数据**: 1 个 Agent(credits=30), 2 个 VirtualItem(price=20, price=25), 2 个独立 session

### C6: max_workers=0 并发打卡 10 人

- **覆盖 AC**: F8.4
- **优先级**: P1
- **Given**: Job(id=1, max_workers=0, daily_reward=5) 存在；Agent(id=1~10) 共 10 个 Agent，今日均未打卡
- **When**: 10 个协程并发调用 `work_service.check_in(agent_id=i, job_id=1, db_i)` (i=1..10)
- **Then**:
  - 10 个全部返回 `{"ok": True}`
  - CheckIn 表中 job_id=1 的今日记录恰好 10 条
  - 10 个 Agent 的 credits 各增加 5
- **测试数据**: Job(max_workers=0, daily_reward=5), 10 个 Agent, 10 个独立 session

---

## E2E 层：端到端测试（6 个用例）

> 测试方式：拉起真实 FastAPI 服务器，通过 HTTP + WebSocket 客户端调用真实 API，检查真实数据库。

### E1: 打卡 -> 余额增加

- **覆盖 AC**: AC-M3-01
- **优先级**: P0
- **Given**: 服务器已启动，seed 数据已加载；Agent(id=1, credits=100) 存在；Job(id=1, daily_reward=8) 存在
- **When**:
  1. `GET /api/agents/1` 记录初始 credits
  2. `POST /api/work/jobs/1/checkin` body=`{"agent_id": 1}`
  3. `GET /api/agents/1` 查询最新 credits
- **Then**:
  - POST 返回 200，body 含 `{"ok": true, "reward": 8}`
  - 最新 credits = 初始 credits + 8
- **测试数据**: seed 数据中的 Agent 和 Job

### E2: 打卡 -> 购买 -> 余额减少 + 物品出现

- **覆盖 AC**: AC-M3-01, AC-M3-04
- **优先级**: P0
- **Given**: 服务器已启动；Agent(id=1, credits=100) 存在；Job(id=1, daily_reward=8) 存在；VirtualItem(id=1, price=20) 存在
- **When**:
  1. `POST /api/work/jobs/1/checkin` body=`{"agent_id": 1}` — 打卡赚钱
  2. `POST /api/shop/purchase` body=`{"agent_id": 1, "item_id": 1}` — 购买商品
  3. `GET /api/agents/1` — 查询余额
  4. `GET /api/shop/agents/1/items` — 查询物品列表
- **Then**:
  - 打卡返回 `{"ok": true, "reward": 8}`
  - 购买返回 `{"ok": true, "price": 20}`
  - 最终 credits = 100 + 8 - 20 = 88
  - 物品列表包含 item_id=1
- **测试数据**: seed 数据

### E3: 余额不足 -> 打卡赚钱 -> 再次购买成功

- **覆盖 AC**: AC-M3-05, AC-M3-01, AC-M3-04
- **优先级**: P0
- **Given**: 服务器已启动；Agent(id=1, credits=5) 存在；Job(id=1, daily_reward=15) 存在；VirtualItem(id=1, price=10) 存在
- **When**:
  1. `POST /api/shop/purchase` body=`{"agent_id": 1, "item_id": 1}` — 余额不足
  2. `POST /api/work/jobs/1/checkin` body=`{"agent_id": 1}` — 打卡赚钱
  3. `POST /api/shop/purchase` body=`{"agent_id": 1, "item_id": 1}` — 再次购买
- **Then**:
  - 第 1 次购买返回 `{"ok": false, "reason": "insufficient_credits"}`
  - 打卡返回 `{"ok": true, "reward": 15}`
  - 第 2 次购买返回 `{"ok": true}`
  - 最终 credits = 5 + 15 - 10 = 10
- **测试数据**: Agent(credits=5), Job(daily_reward=15), VirtualItem(price=10)

### E4: 打卡事件 WebSocket 推送

- **覆盖 AC**: AC-M3-07
- **优先级**: P1
- **Given**: 服务器已启动；WebSocket 客户端已连接 `/ws/0`；Agent(id=1) 和 Job(id=1) 存在
- **When**: `POST /api/work/jobs/1/checkin` body=`{"agent_id": 1}`
- **Then**:
  - WebSocket 客户端收到消息：`{"type": "system_event", "data": {"event": "checkin", "agent_id": 1, "job_title": "矿工", "reward": 8, ...}}`
  - 事件中包含 agent_name、job_title、reward、timestamp 字段
- **测试数据**: seed 数据, WebSocket 连接

### E5: 购买事件 WebSocket 推送

- **覆盖 AC**: AC-M3-08
- **优先级**: P1
- **Given**: 服务器已启动；WebSocket 客户端已连接 `/ws/0`；Agent(id=1, credits=50) 和 VirtualItem(id=1, price=20) 存在
- **When**: `POST /api/shop/purchase` body=`{"agent_id": 1, "item_id": 1}`
- **Then**:
  - WebSocket 客户端收到消息：`{"type": "system_event", "data": {"event": "purchase", "agent_id": 1, "item_name": "金色头像框", "price": 20, ...}}`
  - 事件中包含 agent_name、item_name、price、timestamp 字段
- **测试数据**: seed 数据, WebSocket 连接

### E6: WebSocket 事件后查询 API 数据一致

- **覆盖 AC**: 串讲补充（先 commit 再 broadcast）
- **优先级**: P1
- **Given**: 服务器已启动；WebSocket 客户端已连接 `/ws/0`；Agent(id=1, credits=100) 和 Job(id=1, daily_reward=8) 存在
- **When**:
  1. `POST /api/work/jobs/1/checkin` body=`{"agent_id": 1}`
  2. WebSocket 客户端收到 checkin 事件
  3. 收到事件后立即 `GET /api/agents/1` 查询余额
  4. 收到事件后立即 `GET /api/work/agents/1/today` 查询今日打卡
- **Then**:
  - GET 返回的 credits = 108（数据已落盘，不会出现事件推送了但数据未持久化的情况）
  - GET 返回的今日打卡记录存在且 reward=8
  - 验证 handler 时序：先 commit 再 broadcast
- **测试数据**: seed 数据, WebSocket 连接

---

## 测试环境要求

- 后端：FastAPI 测试客户端（httpx + pytest-asyncio）
- WebSocket 测试：`websockets` 库或 FastAPI TestClient
- 数据库：每个测试用例使用独立的 SQLite 内存数据库（`:memory:`）
- 并发测试：`asyncio.gather` + 独立 db session per task
- E2E 测试：拉起真实 FastAPI 服务器进程，使用 httpx + websockets 客户端

---

## 测试优先级

| 优先级 | 用例范围 | 原因 |
|--------|----------|------|
| P0 | U1(打卡发薪), U2(重复打卡), U3(满员), U10(购买扣费), U11(余额不足), U12(重复购买), C1(并发打卡), C2(并发重复打卡), E1(打卡余额), E2(完整闭环), E3(闭环驱动力) | 核心经济逻辑，阻塞 M3 验收 |
| P1 | U4~U9, U13~U15, U18, C3~C6, E4~E6 | 边界场景 + 并发安全 + 实时推送 |
| P2 | U16, U17 | 辅助查询功能 |

---

## AC 覆盖矩阵

| AC ID | 场景 | 覆盖用例 |
|-------|------|----------|
| AC-M3-01 | 正常打卡发薪 | U1, U4, E1, E2, E3 |
| AC-M3-02 | 同日重复打卡被拒 | U2, C2 |
| AC-M3-03 | 岗位满员被拒 | U3, C1 |
| AC-M3-04 | 正常购买扣费 | U10, C3, E2, E3 |
| AC-M3-05 | 余额不足被拒 | U11, E3 |
| AC-M3-06 | 重复购买被拒 | U12, C4 |
| AC-M3-07 | 打卡事件推送 | E4 |
| AC-M3-08 | 购买事件推送 | E5 |
| AC-M3-09 | 并发打卡竞态 | C1 |
| AC-M3-10 | 岗位列表含在岗人数 | U7 |
| AC-M3-11 | Agent 物品列表正确 | U13 |

---

## 审核记录

- [x] QA Lead 完成初稿（2026-02-17）
- [ ] Developer 确认可测试性
- [ ] Architect 确认覆盖率

---

**编写日期**：2026-02-17
**编写角色**：QA Lead
**基于设计**：TDD-M3-城市经济
**串讲补充项**：已纳入（max_workers=0 无限制、credits >= 0 CHECK 约束、先 commit 再 broadcast 时序）

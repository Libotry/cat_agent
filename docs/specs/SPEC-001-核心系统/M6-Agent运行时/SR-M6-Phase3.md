# SR — M6 Phase 3：Agent 状态可视化（F35）

> 状态：已确认（DC-1~DC-3 全部拍板，2026-02-20）
> 前置：M6 Phase 1（策略自动机）✅ 已完成

---

## 1. 目标

让用户在前端实时看到每个 Agent 的细粒度运行状态（idle / thinking / executing / planning）、当前正在做什么、最近的行动日志，消除"Agent 在黑盒里运行"的感觉。

## 2. 现状分析

| 项目 | 现状 | 缺口 |
|------|------|------|
| 后端状态字段 | `AgentStatus` 枚举：IDLE/CHATTING/WORKING/RESTING | 缺 THINKING/EXECUTING/PLANNING |
| 前端状态展示 | AgentStatusPanel 三色圆点（idle/busy/offline） | 粒度太粗，busy 不知道在干嘛 |
| activity 字段 | `Agent.activity?: string` 已定义 | 没有被实时更新 |
| 行动日志 | ActivityFeed 已有，显示最近 50 条 | 只有 autonomy 动作，缺 tool_call/聊天状态 |
| 状态变更推送 | 无专门事件，只有 `agent_action` | 缺 `agent_status_change` 事件 |

## 3. 范围

### 做

- F35.1 后端状态字段扩展：idle / thinking / executing / planning（4 个状态）
- F35.2 状态变更时实时广播 `agent_status_change` WebSocket 事件
- F35.3 `activity` 字段实时更新（thinking 时写"正在思考…"，executing 时写具体动作）
- F35.4 前端状态徽章升级：4 色圆点 + 状态文字 + activity 描述
- F35.5 行动日志扩展：tool_call 调用也记录到 ActivityFeed
- 单元测试 + ST 脚本

### 不做

- 行动日志持久化到数据库 — 继续用内存（`_last_round_log`），重启丢失可接受
- 前端行动日志独立页面 — 继续用 InfoPanel 内的 ActivityFeed
- Agent 历史状态时间线 — 只展示当前状态，不做历史回溯

## 4. 阶段拆分

### T1：后端状态字段扩展 + WebSocket 广播

**改动文件：**
- `server/app/models/tables.py` — `AgentStatus` 枚举扩展
- `server/app/services/autonomy_service.py` — 状态变更 + 广播
- `server/app/services/agent_runner.py` — 聊天时状态变更

**验收：**
- [ ] `AgentStatus` 枚举包含 IDLE / THINKING / EXECUTING / PLANNING
- [ ] Agent 开始 LLM 调用前状态变为 THINKING
- [ ] Agent 执行 tool_call 时状态变为 EXECUTING + activity 更新
- [ ] Agent 完成后状态回到 IDLE + activity 清空
- [ ] 每次状态变更广播 `agent_status_change` 事件
- [ ] 单元测试覆盖：状态流转、广播消息格式

### T2：前端状态徽章升级 + ActivityFeed 扩展

**改动文件：**
- `web/src/types.ts` — Agent.status 类型扩展
- `web/src/components/AgentStatusPanel.tsx` — 4 色徽章 + activity 展示
- `web/src/components/DiscordLayout.tsx` — 处理 `agent_status_change` 事件
- `web/src/components/ActivityFeed.tsx` — 新增 tool_call 动作类型
- `web/src/App.css` — 新增状态颜色

**验收：**
- [ ] 4 个状态各有独立颜色和文字标签
- [ ] busy 时显示具体 activity（如"正在搜索天气…"）
- [ ] tool_call 动作出现在 ActivityFeed
- [ ] 状态变更实时更新（无需刷新页面）
- [ ] 双主题验证（DEV-8）

### T3：ST 端到端验证

**改动文件：**
- `server/e2e_m6_p3.py`（新建）— ST 脚本
- `server/tests/test_agent_status.py`（新建）— 单元测试

**验收：**
- [ ] ST-1：Agent 被 @ 后，前端收到 thinking → executing → idle 状态变更序列
- [ ] ST-2：Agent 执行 tool_call 时，activity 字段包含工具名称
- [ ] ST-3：ActivityFeed 显示 tool_call 类型的动作记录
- [ ] ST-4：多个 Agent 同时活动时，状态互不干扰

## 5. 阶段门禁

| 门禁 | 条件 |
|------|------|
| T1 → T2 | 后端单元测试全绿（状态流转 + 广播格式） |
| T2 → T3 | 前端构建通过 + 双主题验证 |
| T3 → 完成 | ST 全绿 + pytest 全绿 + Code Review P0/P1 归零 |

## 6. 设计决策

### DC-1：状态枚举值

| 状态 | 含义 | 触发时机 |
|------|------|----------|
| `idle` | 空闲 | 默认状态，完成任务后回到此状态 |
| `thinking` | 思考中 | LLM 调用开始时（聊天回复 / autonomy decide） |
| `executing` | 执行中 | tool_call 执行时 / autonomy action 执行时 |
| `planning` | 规划中 | 预留给 Phase 4（长任务编排），Phase 3 暂不触发 |

> 去掉现有的 CHATTING/WORKING/RESTING，统一为上述 4 个。前端 `offline` 保留，由 online_ids 集合判断，不存入数据库。

### DC-2：WebSocket 事件格式

```json
{
  "type": "system_event",
  "data": {
    "event": "agent_status_change",
    "agent_id": 1,
    "agent_name": "Agent1",
    "status": "thinking",
    "activity": "正在思考回复…",
    "timestamp": "2026-02-20 12:00:00+00:00"
  }
}
```

> 复用现有 `system_event` 类型，新增 `event: "agent_status_change"`，不新增顶层 type。

### DC-3：状态颜色方案

| 状态 | 颜色 | CSS 变量 |
|------|------|----------|
| idle | 灰色 | `--status-idle` |
| thinking | 蓝色 | `--status-thinking` |
| executing | 绿色 | `--status-executing` |
| planning | 紫色 | `--status-planning` |
| offline | 暗灰 | `--status-offline`（已有） |

---

## 7. AR 级别实施细节

> 以下为 Sonnet 终端可直接执行的详细指引。

### 7.1 修改文件：`server/app/models/tables.py`

**位置**：`E:\a3\server\app\models\tables.py`

**改动点**：替换 `AgentStatus` 枚举。

**改动前：**
```python
class AgentStatus(str, enum.Enum):
    IDLE = "idle"
    CHATTING = "chatting"
    WORKING = "working"
    RESTING = "resting"
```

**改动后：**
```python
class AgentStatus(str, enum.Enum):
    IDLE = "idle"
    THINKING = "thinking"
    EXECUTING = "executing"
    PLANNING = "planning"      # Phase 4 预留，Phase 3 暂不触发
```

**注意**：需要全局搜索 `CHATTING`、`WORKING`、`RESTING` 的引用，全部替换为对应的新状态。

### 7.2 修改文件：`server/app/services/agent_runner.py`

**位置**：`E:\a3\server\app\services\agent_runner.py`（246 行）

**改动点**：在 `generate_reply()` 函数中，LLM 调用前后插入状态变更。

**改动位置**：行 113-146 附近（tool_call 循环）

**伪代码：**
```python
async def generate_reply(agent, message, db):
    # --- 新增：状态 → THINKING ---
    await _set_agent_status(agent, AgentStatus.THINKING, "正在思考回复…", db)

    response = await llm_client.chat(...)  # 现有 LLM 调用

    # tool_call 循环
    while response.tool_calls:
        for tool_call in response.tool_calls:
            # --- 新增：状态 → EXECUTING ---
            await _set_agent_status(agent, AgentStatus.EXECUTING, f"执行 {tool_call.function.name}…", db)

            result = await tool_registry.execute(tool_call, context)

        response = await llm_client.chat(...)  # 继续对话

    # --- 新增：状态 → IDLE ---
    await _set_agent_status(agent, AgentStatus.IDLE, "", db)

    return response.content
```

**新增辅助函数**（在 agent_runner.py 顶部或底部）：
```python
async def _set_agent_status(agent, status: AgentStatus, activity: str, db: AsyncSession):
    """更新 Agent 状态 + activity，写入 DB 并广播 WebSocket 事件。"""
    agent.status = status.value
    agent.activity = activity
    await db.commit()
    await broadcast({
        "type": "system_event",
        "data": {
            "event": "agent_status_change",
            "agent_id": agent.id,
            "agent_name": agent.name,
            "status": status.value,
            "activity": activity,
            "timestamp": datetime.now(timezone.utc).isoformat(sep=" ", timespec="seconds"),
        }
    })
```

### 7.3 修改文件：`server/app/services/autonomy_service.py`

**位置**：`E:\a3\server\app\services\autonomy_service.py`（854 行）

**改动点**：在 `tick()` → `decide()` → `execute_decisions()` 流程中插入状态变更。

**改动位置 1**：`decide()` 函数开头（LLM 决策前）
```python
async def decide(self, agent, snapshot, db):
    await _set_agent_status(agent, AgentStatus.THINKING, "正在分析环境…", db)
    # ... 现有 LLM 调用 ...
```

**改动位置 2**：`execute_decisions()` 中每个 action 执行前
```python
for decision in decisions:
    await _set_agent_status(agent, AgentStatus.EXECUTING, f"执行 {decision['action']}…", db)
    # ... 现有 action 执行 ...
```

**改动位置 3**：`tick()` 函数末尾（所有 Agent 处理完后）
```python
# 每个 agent 处理完后
await _set_agent_status(agent, AgentStatus.IDLE, "", db)
```

**注意**：`_set_agent_status` 函数从 `agent_runner.py` 导入，或提取到公共模块 `server/app/services/status_helper.py`（推荐，避免循环导入）。

### 7.4 修改文件：`web/src/types.ts`

**位置**：`E:\a3\web\src\types.ts`（244 行）

**改动点 1**：Agent 接口的 `status` 字段类型扩展（行 7）。

**改动前：**
```typescript
status: 'idle' | 'busy' | 'offline'
```

**改动后：**
```typescript
status: 'idle' | 'thinking' | 'executing' | 'planning' | 'offline'
```

**改动点 2**：`WsSystemEvent` 的 `event` 联合类型扩展（行 49）。

**改动前：**
```typescript
event: 'agent_online' | 'agent_offline' | 'checkin' | 'purchase' | 'agent_action' | 'resource_transferred' | 'building_construction_started' | 'building_completed'
```

**改动后：**
```typescript
event: 'agent_online' | 'agent_offline' | 'checkin' | 'purchase' | 'agent_action' | 'agent_status_change' | 'resource_transferred' | 'building_construction_started' | 'building_completed'
```

**改动点 3**：`WsSystemEvent.data` 新增可选字段（行 57 附近，已有 `action?: string`）。

**追加字段：**
```typescript
// F35: 状态变更事件字段
status?: string
activity?: string
```

### 7.5 修改文件：`web/src/components/AgentStatusPanel.tsx`

**位置**：`E:\a3\web\src\components\AgentStatusPanel.tsx`（42 行）

**改动点**：排序逻辑 + 状态文字展示，从 3 状态升级到 5 状态。

**改动前（行 9-11）：**
```typescript
const sorted = [...agents].sort((a, b) => {
  const order = { busy: 0, idle: 1, offline: 2 }
  return (order[a.status] ?? 3) - (order[b.status] ?? 3)
})
```

**改动后：**
```typescript
const sorted = [...agents].sort((a, b) => {
  const order: Record<string, number> = { executing: 0, thinking: 1, planning: 2, idle: 3, offline: 4 }
  return (order[a.status] ?? 5) - (order[b.status] ?? 5)
})
```

**改动前（行 26-32，状态文字）：**
```tsx
{agent.status === 'busy' && agent.activity
  ? agent.activity
  : agent.status === 'idle'
    ? '空闲'
    : agent.status === 'offline'
      ? '离线'
      : ''}
```

**改动后：**
```tsx
{(() => {
  const labels: Record<string, string> = {
    idle: '空闲', thinking: '思考中', executing: '执行中', planning: '规划中', offline: '离线'
  }
  // thinking/executing/planning 时优先显示 activity
  if (['thinking', 'executing', 'planning'].includes(agent.status) && agent.activity) {
    return agent.activity
  }
  return labels[agent.status] || ''
})()}
```

### 7.6 修改文件：`web/src/components/DiscordLayout.tsx`

**位置**：`E:\a3\web\src\components\DiscordLayout.tsx`（145 行）

**改动点**：在 `handleWsMessage` 回调中，新增 `agent_status_change` 事件处理（行 56 附近，`agent_action` 处理块之后）。

**在行 90（`agent_action` 块的 `}` 之后）插入：**
```typescript
// F35: agent_status_change 事件 → 更新 agent 状态 + activity
if (msg.data.event === 'agent_status_change') {
  setAgents(prev => prev.map(a =>
    a.id === msg.data.agent_id
      ? {
          ...a,
          status: (msg.data.status as Agent['status']) || a.status,
          activity: msg.data.activity || '',
        }
      : a
  ))
}
```

**注意**：不需要 `fetchAgents()` 全量刷新，直接本地更新 status + activity 即可，减少 API 调用。

### 7.7 修改文件：`web/src/components/ActivityFeed.tsx` + `web/src/App.css` + `web/src/themes.css`

#### 7.7.1 ActivityFeed.tsx

**位置**：`E:\a3\web\src\components\ActivityFeed.tsx`（83 行）

**改动点**：`action` 联合类型新增 `tool_call`，`ACTION_LABELS` 新增对应标签。

**改动前（行 6）：**
```typescript
action: 'checkin' | 'purchase' | 'chat' | 'rest' | 'assign_building' | 'unassign_building' | 'eat'
```

**改动后：**
```typescript
action: 'checkin' | 'purchase' | 'chat' | 'rest' | 'assign_building' | 'unassign_building' | 'eat' | 'tool_call'
```

**改动前（行 13-21，ACTION_LABELS）追加一行：**
```typescript
tool_call: '调用工具',
```

#### 7.7.2 themes.css

**位置**：`E:\a3\web\src\themes.css`（102 行）

**改动点**：在 `/* Status */` 区块（行 47-54）追加新状态颜色变量。

**在行 54（`--status-error` 之后）追加：**
```css
/* F35: 细粒度状态颜色 */
--status-thinking: #2196f3;
--status-thinking-bg: #e3f2fd;
--status-executing: #4caf50;
--status-executing-bg: #e8f5e9;
--status-planning: #9c27b0;
--status-planning-bg: #f3e5f5;
```

> `--status-executing` 复用 `--status-online` 的绿色值，语义更清晰。

#### 7.7.3 App.css

**位置**：`E:\a3\web\src\App.css`

**改动点 1**：`.agent-status-dot` 新增 4 个状态类（行 518-528 附近，现有 idle/busy/offline 之后）。

**替换现有 3 个状态类为 5 个：**
```css
.agent-status-dot.idle {
  background: var(--status-offline);  /* 灰色，空闲 */
}

.agent-status-dot.thinking {
  background: var(--status-thinking);
}

.agent-status-dot.executing {
  background: var(--status-executing);
}

.agent-status-dot.planning {
  background: var(--status-planning);
}

.agent-status-dot.offline {
  background: var(--status-offline);
}
```

**改动点 2**：`.ac-status` 同步更新（行 635-648），替换 idle/busy/offline 为 5 个状态。

**改动点 4**：`.mention-status` 同步更新（行 381-383），替换 idle/busy/offline 为 5 个状态。

### 7.8 新建文件：`server/tests/test_agent_status.py`

**位置**：`E:\a3\server\tests\test_agent_status.py`

**测试用例：**

```
test_status_enum_values           — AgentStatus 包含 IDLE/THINKING/EXECUTING/PLANNING 四个值
test_set_agent_status_updates_db  — 调用 _set_agent_status 后 agent.status 和 agent.activity 正确更新
test_set_agent_status_broadcasts  — 调用后广播消息格式正确（type=system_event, event=agent_status_change）
test_status_flow_thinking_to_idle — THINKING → IDLE 流转正确
test_status_flow_executing        — THINKING → EXECUTING → IDLE 流转正确
test_broadcast_contains_agent_info — 广播消息包含 agent_id, agent_name, status, activity, timestamp
test_old_status_removed           — CHATTING/WORKING/RESTING 不在 AgentStatus 枚举中
```

### 7.9 新建文件：`server/e2e_m6_p3.py`

**位置**：`E:\a3\server\e2e_m6_p3.py`

**ST 场景：**

```
ST-1: 状态变更序列
  - WebSocket 连接监听
  - POST /api/dev/trigger 发送 "@Agent1 你好"
  - 收集 agent_status_change 事件
  - 验证收到 thinking → idle（或 thinking → executing → idle）序列

ST-2: activity 字段包含工具名称
  - POST /api/dev/trigger 发送触发 tool_call 的消息
  - 验证 executing 状态的 activity 字段包含工具名称

ST-3: ActivityFeed 显示 tool_call
  - 验证 agent_action 事件中 action=tool_call 的记录被推送

ST-4: 多 Agent 状态互不干扰
  - 同时触发 Agent1 和 Agent2
  - 验证各自的 status_change 事件 agent_id 正确，互不覆盖
```

### 7.10 不改动的文件（确认）

| 文件 | 原因 |
|------|------|
| `server/app/core/config.py` | 不改 — 状态可视化无新配置项 |
| `server/app/services/tool_registry.py` | 不改 — tool_call 状态变更在 agent_runner.py 的循环中处理 |
| `server/app/services/strategy_engine.py` | 不改 — 策略引擎不涉及状态展示 |
| `web/src/api.ts` | 不改 — 状态通过 WebSocket 推送，无新 REST API |
| `web/src/hooks/useWebSocket.ts` | 不改 — 现有 hook 已能处理 system_event |

---

## 8. 文件路径速查

| 文件 | 路径 | 操作 |
|------|------|------|
| tables.py | `E:\a3\server\app\models\tables.py` | 替换 AgentStatus 枚举 |
| agent_runner.py | `E:\a3\server\app\services\agent_runner.py` | 插入状态变更（~15 行） |
| autonomy_service.py | `E:\a3\server\app\services\autonomy_service.py` | 插入状态变更（~10 行） |
| types.ts | `E:\a3\web\src\types.ts` | 扩展 status 类型 + event 联合 |
| AgentStatusPanel.tsx | `E:\a3\web\src\components\AgentStatusPanel.tsx` | 排序 + 状态文字升级 |
| DiscordLayout.tsx | `E:\a3\web\src\components\DiscordLayout.tsx` | 新增 agent_status_change 处理 |
| ActivityFeed.tsx | `E:\a3\web\src\components\ActivityFeed.tsx` | 新增 tool_call 动作类型 |
| themes.css | `E:\a3\web\src\themes.css` | 新增 3 个状态颜色变量 |
| App.css | `E:\a3\web\src\App.css` | 状态圆点 + pulse 动画 |
| test_agent_status.py | `E:\a3\server\tests\test_agent_status.py` | 新建 |
| e2e_m6_p3.py | `E:\a3\server\e2e_m6_p3.py` | 新建 |

**参考文件（只读，用于对齐格式）：**

| 文件 | 路径 | 参考什么 |
|------|------|----------|
| agent_runner.py | `E:\a3\server\app\services\agent_runner.py` | tool_call 循环位置（行 113-146） |
| autonomy_service.py | `E:\a3\server\app\services\autonomy_service.py` | tick/decide/execute 流程 |
| DiscordLayout.tsx | `E:\a3\web\src\components\DiscordLayout.tsx` | WS 事件处理模式（行 36-91） |
| ActivityFeed.tsx | `E:\a3\web\src\components\ActivityFeed.tsx` | action 类型 + labels 格式 |
| themes.css | `E:\a3\web\src\themes.css` | CSS 变量命名规范 |
| e2e_m6.py | `E:\a3\server\e2e_m6.py` | ST 脚本结构、断言方式 |
| test_m6_strategy.py | `E:\a3\server\tests\test_m6_strategy.py` | 单元测试 fixture、mock 模式 |

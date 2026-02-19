# TDD-M5.1 — 资源转赠 + Agent Tool Use

> 对应 IR：`01-需求原型.md` §M5.1（US-M5.1-1 ~ US-M5.1-5, F21 ~ F24, AC-M5.1-01 ~ AC-M5.1-10）
> 对应 SR：`02-需求拆分.md` §M5.1（M5.1-1 ~ M5.1-9）

---

## 1. 架构概览

```
agent_runner.py (改造)
┌──────────────────────────────────────────────────┐
│ generate_reply(chat_history, db)                  │
│   1. 构建 messages                                │
│   2. LLM 调用（传入 tools 参数）                   │
│   3. 检查 tool_calls                              │
│   │   ├─ 无 → 返回纯文本（现有路径）               │
│   │   └─ 有 → tool_registry.execute()             │
│   │          → 结果追加到 messages                 │
│   │          → 再次调用 LLM → 返回最终回复          │
│   └──────────────────────────────────────────────│
└──────────────────────────────────────────────────┘
                    │
                    ▼
tool_registry.py (新建)
┌──────────────────────────────────────────────────┐
│ ToolRegistry (全局单例)                            │
│   register(ToolDefinition)                        │
│   get_tools_for_llm() → OpenAI tools 格式         │
│   execute(name, arguments, context) → dict        │
│                                                    │
│ 已注册工具：                                       │
│   transfer_resource → city_service.transfer_resource│
└──────────────────────────────────────────────────┘

autonomy_service.py (扩展)
┌──────────────────────────────────────────────────┐
│ SYSTEM_PROMPT 新增 transfer_resource action        │
│ execute_decisions() 新增 transfer_resource 分支    │
│   → city_service.transfer_resource()              │
└──────────────────────────────────────────────────┘

city_service.py (补全)
┌──────────────────────────────────────────────────┐
│ transfer_resource() 末尾补调                       │
│   _broadcast_city_event("resource_transferred",   │
│     {from_agent_id, from_agent_name,              │
│      to_agent_id, to_agent_name,                  │
│      resource_type, quantity})                     │
└──────────────────────────────────────────────────┘

前端
┌──────────────────────────────────────────────────┐
│ App.tsx → BrowserRouter + Routes                  │
│   / → DiscordLayout（不变）                        │
│   /trade → TradePage（新建）                       │
│                                                    │
│ types.ts → WsSystemEvent.event 新增               │
│            "resource_transferred"                  │
│ api.ts → transferResource() 新增                   │
└──────────────────────────────────────────────────┘
```

核心思路：
- Tool Use 框架与 agent_runner 解耦：tool_registry 负责工具注册/执行，agent_runner 只负责 LLM 调用 + tool_call 循环
- 转赠广播补全：city_service.transfer_resource() 成功后广播，前端交易面板监听
- 前端引入 React Router，交易面板为独立路由，不影响现有主界面

---

## 2. 数据模型变更

无。M5.1 不新增表或字段，复用现有 Agent、AgentResource 表。

---

## 3. 接口定义

### 3.1 tool_registry.py（新建）

```python
# server/app/services/tool_registry.py

from dataclasses import dataclass
from typing import Any, Callable, Awaitable

@dataclass
class ToolDefinition:
    name: str
    description: str
    parameters: dict          # JSON Schema
    handler: Callable[..., Awaitable[dict]]  # async (arguments, context) -> dict

class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, ToolDefinition] = {}

    def register(self, tool: ToolDefinition):
        self._tools[tool.name] = tool

    def get_tools_for_llm(self) -> list[dict]:
        """返回 OpenAI function calling 格式的工具列表。"""
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                },
            }
            for t in self._tools.values()
        ]

    async def execute(self, name: str, arguments: dict, context: dict) -> dict:
        """执行工具，返回 {"ok": bool, "result": str} 或 {"ok": false, "error": str}。"""
        tool = self._tools.get(name)
        if not tool:
            return {"ok": False, "error": f"未知工具: {name}"}
        try:
            result = await tool.handler(arguments, context)
            return {"ok": True, "result": result}
        except Exception as e:
            return {"ok": False, "error": str(e)}


# --- transfer_resource 工具 ---

async def _handle_transfer_resource(arguments: dict, context: dict) -> dict:
    """transfer_resource 工具的 handler。"""
    from .city_service import transfer_resource
    db = context["db"]
    from_agent_id = context["agent_id"]
    to_agent_id = arguments["to_agent_id"]
    resource_type = arguments["resource_type"]
    quantity = arguments["quantity"]
    return await transfer_resource(from_agent_id, to_agent_id, resource_type, quantity, db)


TRANSFER_RESOURCE_TOOL = ToolDefinition(
    name="transfer_resource",
    description="将自己的资源转赠给另一个居民",
    parameters={
        "type": "object",
        "properties": {
            "to_agent_id": {"type": "integer", "description": "接收方居民 ID"},
            "resource_type": {"type": "string", "description": "资源类型，如 flour"},
            "quantity": {"type": "number", "description": "转赠数量"},
        },
        "required": ["to_agent_id", "resource_type", "quantity"],
    },
    handler=_handle_transfer_resource,
)

# 全局单例
tool_registry = ToolRegistry()
tool_registry.register(TRANSFER_RESOURCE_TOOL)

# TODO: 假设所有模型支持 function calling，后续按需补降级逻辑
```

设计要点：
- `handler` 签名统一为 `async (arguments: dict, context: dict) -> dict`
- `context` 由 agent_runner 构建，包含 `agent_id` 和 `db`，Agent 不能伪造 `from_agent_id`
- `execute()` 捕获异常，返回结构化错误，不会让 agent_runner 崩溃
- `get_tools_for_llm()` 返回标准 OpenAI tools 格式，直接传入 `client.chat.completions.create(tools=...)`

### 3.2 agent_runner.py 改造

修改 `AgentRunner.generate_reply()` 方法，在现有 LLM 调用处增加 tool_call 处理：

```python
# 改动位置：agent_runner.py 第 101~142 行（try 块内）

# 现有代码：
#   response = await client.chat.completions.create(
#       model=model_id, messages=messages, max_tokens=800,
#   )

# 改为：
from .tool_registry import tool_registry

tools = tool_registry.get_tools_for_llm()
create_kwargs = {
    "model": model_id,
    "messages": messages,
    "max_tokens": 800,
}
if tools:
    create_kwargs["tools"] = tools

response = await client.chat.completions.create(**create_kwargs)

# tool_call 处理循环（最多 1 轮，防止无限循环）
msg = response.choices[0].message
if msg.tool_calls:
    # 追加 assistant message（含 tool_calls）
    messages.append(msg)

    for tc in msg.tool_calls:
        import json as _json
        try:
            args = _json.loads(tc.function.arguments)
        except _json.JSONDecodeError:
            args = {}

        context = {"agent_id": self.agent_id, "db": db}
        result = await tool_registry.execute(tc.function.name, args, context)

        messages.append({
            "role": "tool",
            "tool_call_id": tc.id,
            "content": _json.dumps(result, ensure_ascii=False),
        })

    # 第二次 LLM 调用：基于工具执行结果生成最终回复
    response = await client.chat.completions.create(
        model=model_id,
        messages=messages,
        max_tokens=800,
    )

# 后续取 reply 的逻辑不变
```

设计要点：
- tool_call 循环限制为 1 轮（只处理第一次 tool_calls，第二次调用不传 tools）。M5.1 只有 transfer_resource 一个工具，不需要多轮
- `generate_reply()` 签名不变：`(chat_history, db) -> (reply, usage_info, used_memory_ids)`，调用方无感知
- db 必须从外部传入（已有），tool handler 通过 context 获取
- 第二次 LLM 调用不传 tools 参数，确保不会再次触发 tool_call

### 3.3 city_service.py 补广播

修改 `transfer_resource()` 函数，在成功后补调广播：

```python
# 改动位置：city_service.py 第 46~59 行

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
```

注意：转赠是私人行为，不在聊天区显示系统消息。前端只在交易面板处理 `resource_transferred` 事件。

### 3.4 autonomy_service.py 扩展

修改 `SYSTEM_PROMPT` 和 `execute_decisions()`：

```python
# SYSTEM_PROMPT 改动（第 37 行 action 枚举 + 第 46 行 params）

SYSTEM_PROMPT = """你是虚拟城市模拟器。根据世界状态为每个居民决定行为。

规则：
1. 行为：checkin（打卡）、purchase（购买）、chat（聊天）、rest（休息）、assign_building（应聘建筑）、unassign_building（离职）、eat（吃饭）、transfer_resource（转赠资源）
2. 已打卡不能重复；余额不足不能购买；行为符合性格
3. rest 是合理选择，不必所有人都行动
4. 饱腹度低时优先 eat；体力低时优先 rest；无工作时考虑 assign_building
5. assign_building 需要 building_id；unassign_building 无需参数（自动查找当前建筑）
6. transfer_resource：当自己资源充裕且有居民资源匮乏时可考虑转赠

直接输出纯 JSON 数组，不要解释，不要 markdown，不要思考过程。示例：
[{"agent_id": 1, "action": "transfer_resource", "params": {"to_agent_id": 2, "resource_type": "flour", "quantity": 3}, "reason": "Bob 没有面粉，分一些给他"}]

params: checkin={}, purchase={"item_id": <int>}, chat={}, rest={}, assign_building={"building_id": <int>}, unassign_building={}, eat={}, transfer_resource={"to_agent_id": <int>, "resource_type": "<str>", "quantity": <number>}"""
```

```python
# execute_decisions() 新增分支（在 elif action == "eat" 之后）
# 同时在 decide() 的 valid action 列表中加入 "transfer_resource"

# decide() 第 241 行：
if d["action"] not in ("checkin", "purchase", "chat", "rest", "assign_building", "unassign_building", "eat", "transfer_resource"):
    d["action"] = "rest"

# execute_decisions() 新增分支：
elif action == "transfer_resource":
    to_id = params.get("to_agent_id")
    res_type = params.get("resource_type")
    qty = params.get("quantity")
    if to_id and res_type and qty:
        from .city_service import transfer_resource
        res = await transfer_resource(aid, to_id, res_type, qty, db)
        if res["ok"]:
            stats["success"] += 1
            await _broadcast_action(agent_name, aid, "transfer_resource", reason)
        else:
            logger.info("Autonomy transfer_resource failed for %s: %s", agent_name, res["reason"])
            stats["failed"] += 1
    else:
        stats["failed"] += 1
```

注意：`transfer_resource` 已在 `city_service` 的 import 列表中（第 24 行未导入），需补充导入。但由于 execute_decisions 内部用 lazy import，可以在分支内 `from .city_service import transfer_resource`。

### 3.5 REST API

无新增端点。`POST /agents/transfer-resource` 已存在（`server/app/api/city.py`），M5.1-4 补广播后自动生效。

### 3.6 WebSocket 事件格式

```json
// 资源转赠（新增）
{
  "type": "system_event",
  "data": {
    "event": "resource_transferred",
    "from_agent_id": 1,
    "from_agent_name": "Alice",
    "to_agent_id": 2,
    "to_agent_name": "Bob",
    "resource_type": "flour",
    "quantity": 5,
    "timestamp": "2026-02-20 10:00:00+00:00"
  }
}
```

### 3.7 前端类型扩展

```typescript
// web/src/types.ts — WsSystemEvent 改动

export interface WsSystemEvent {
  type: 'system_event'
  data: {
    event: 'agent_online' | 'agent_offline' | 'checkin' | 'purchase' | 'agent_action' | 'resource_transferred'
    agent_id: number
    agent_name: string
    timestamp: string
    // 现有可选字段...
    job_title?: string
    reward?: number
    item_name?: string
    price?: number
    action?: string
    reason?: string
    // M5.1 新增
    from_agent_id?: number
    from_agent_name?: string
    to_agent_id?: number
    to_agent_name?: string
    resource_type?: string
    quantity?: number
  }
}
```

```typescript
// web/src/types.ts — 新增

export interface TransferResult {
  ok: boolean
  reason: string
}
```

### 3.8 前端 API 扩展

```typescript
// web/src/api.ts — 新增

export async function transferResource(
  fromAgentId: number,
  toAgentId: number,
  resourceType: string,
  quantity: number,
): Promise<TransferResult> {
  if (await useMock()) return { ok: false, reason: 'mock_mode' }
  const res = await fetch(`${BASE}/agents/transfer-resource`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      from_agent_id: fromAgentId,
      to_agent_id: toAgentId,
      resource_type: resourceType,
      quantity,
    }),
  })
  if (!res.ok) throw new Error(`transferResource: ${res.status}`)
  return res.json()
}
```

---

## 4. 前端路由 + TradePage

### 4.1 React Router 引入

```typescript
// web/src/App.tsx

import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { DiscordLayout } from './components/DiscordLayout'
import { TradePage } from './pages/TradePage'
import './App.css'

function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<DiscordLayout />} />
        <Route path="/trade" element={<TradePage />} />
      </Routes>
    </BrowserRouter>
  )
}

export default App
```

### 4.2 TradePage 组件

新建 `web/src/pages/TradePage.tsx`：

```
┌─────────────────────────────────────────────────┐
│ ← 返回主界面                    资源交易面板      │
├─────────────────────────────────────────────────┤
│                                                   │
│ ┌─ Agent 资源概览 ─────────────────────────────┐ │
│ │ Alice: flour=10                               │ │
│ │ Bob:   flour=3                                │ │
│ │ Carol: flour=7                                │ │
│ └───────────────────────────────────────────────┘ │
│                                                   │
│ ┌─ 转赠表单 ───────────────────────────────────┐ │
│ │ 发送方: [Alice ▼]  接收方: [Bob ▼]           │ │
│ │ 资源:   [flour ▼]  数量:   [5    ]           │ │
│ │                          [转赠]               │ │
│ └───────────────────────────────────────────────┘ │
│                                                   │
│ ┌─ 转赠历史（实时） ───────────────────────────┐ │
│ │ 10:00 Alice → Bob: 5 flour                    │ │
│ │ 09:30 Carol → Alice: 3 flour                  │ │
│ └───────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────┘
```

实现要点：
- 资源概览：`useEffect` 调用 `fetchCityOverview("长安")`，展示每个 Agent 的资源
- 转赠表单：4 个字段（发送方、接收方、资源类型、数量），提交调用 `transferResource()`
- 转赠历史：`useWebSocket` hook 监听 `resource_transferred` 事件，`useState` 维护列表（最多 50 条 FIFO）
- 页面顶部 `<Link to="/">← 返回主界面</Link>`
- 转赠成功后刷新资源概览

---

## 5. 容错与边界

| 场景 | 处理 |
|------|------|
| LLM 不返回 tool_call | 走现有纯文本路径，不影响 |
| LLM 返回未注册的工具名 | tool_registry.execute() 返回 `{"ok": false, "error": "未知工具"}` |
| tool_call 参数缺失/类型错误 | handler 内部由 city_service 校验，返回错误 |
| transfer_resource 资源不足 | city_service 返回 `{"ok": false, "reason": "xxx 不足"}`，LLM 用自然语言解释 |
| transfer_resource 目标 Agent 不存在 | `_get_or_create_agent_resource` 会创建空记录，不会报错（但语义上不合理）— 可在 handler 中预检查 |
| tool_call 执行异常 | tool_registry.execute() 捕获异常，返回 `{"ok": false, "error": str(e)}` |
| 第二次 LLM 调用失败 | 与现有错误处理一致，返回 `(None, None, [])` |
| autonomy transfer_resource 参数不全 | stats["failed"] += 1，跳过 |
| 前端 WebSocket 收到未知 event | 现有逻辑忽略未处理的 event，不影响 |
| React Router 未匹配路由 | 无 fallback 路由，浏览器显示空白 — M5.1 不处理，后续可加 404 |

### 安全考虑

- Agent 不能伪造 `from_agent_id`：tool handler 从 context 取 `agent_id`，不从 LLM 参数取
- 前端 transferResource API 需要传 `from_agent_id`：这是管理员操作（人类通过交易面板手动转赠），不是 Agent 自主行为
- quantity 校验：city_service 已有 `quantity <= 0` 和余额不足检查

---

## 6. 文件清单

### 新建文件

| 文件 | 职责 | 预估行数 |
|------|------|---------|
| `server/app/services/tool_registry.py` | Tool Use 框架 + transfer_resource 工具注册 | ~80 |
| `web/src/pages/TradePage.tsx` | 交易面板（资源概览 + 转赠表单 + 转赠历史） | ~150 |

### 修改文件

| 文件 | 改动 | 预估增量 |
|------|------|---------|
| `server/app/services/agent_runner.py` | generate_reply 增加 tools 参数 + tool_call 处理循环 | +~40 |
| `server/app/services/city_service.py` | transfer_resource 末尾补广播 | +~10 |
| `server/app/services/autonomy_service.py` | SYSTEM_PROMPT 新增 transfer_resource + execute_decisions 新增分支 + decide valid action 列表 | +~20 |
| `web/src/App.tsx` | 引入 BrowserRouter + Routes + Route | +~10 |
| `web/src/types.ts` | WsSystemEvent.event 新增 resource_transferred + 新增 TransferResult | +~8 |
| `web/src/api.ts` | 新增 transferResource() | +~15 |

---

## 7. LLM Prompt 扩展

### agent_runner System Prompt

现有 `SYSTEM_PROMPT_TEMPLATE` 不改动。Tool Use 通过 OpenAI function calling 机制传递，不需要在 system prompt 中描述工具。LLM 会根据 `tools` 参数自动理解可用工具。

### autonomy_service System Prompt

见 §3.4，新增 `transfer_resource` action 描述和 params 说明。

---

## 8. 测试计划

### 单元测试

| 测试 | 覆盖 |
|------|------|
| `test_tool_registry_register` | 注册工具后 get_tools_for_llm 返回正确格式 |
| `test_tool_registry_execute_success` | 执行已注册工具，返回 `{"ok": true, "result": ...}` |
| `test_tool_registry_execute_unknown` | 执行未注册工具，返回 `{"ok": false, "error": "未知工具"}` |
| `test_tool_registry_execute_exception` | handler 抛异常，返回 `{"ok": false, "error": ...}` |
| `test_transfer_resource_broadcast` | 转赠成功后 _broadcast_city_event 被调用，参数正确 |
| `test_autonomy_transfer_resource_success` | execute_decisions 处理 transfer_resource action，调用 city_service |
| `test_autonomy_transfer_resource_missing_params` | 参数不全时 stats["failed"] += 1 |
| `test_autonomy_decide_valid_actions` | decide() 接受 transfer_resource，不降级为 rest |

### 集成测试（E2E）

| 场景 | 对应 AC | 验证 |
|------|---------|------|
| @Alice "把 5 flour 给 Bob" → Alice 调用工具 → 转赠成功 → 回复确认 | AC-01 | AgentResource 变化 + WS 事件 + 回复文本 |
| @Alice "把 5 flour 给 Bob"，Alice flour 不足 → 回复"不足" | AC-02 | AgentResource 不变 + 回复包含"不足" |
| @Alice "把 flour 给 Bob"（未指定数量）→ Alice 自主决定 | AC-03 | LLM 自行填充 quantity 或回复询问 |
| Bob @Alice "能给我点 flour 吗" → Alice 自主决定 | AC-04 | 可能调用工具或纯文本回复 |
| @Alice "去农田工作" → 只回复文本，不调用工具 | AC-05 | 无 tool_call |
| 转赠成功 → 所有在线客户端收到 resource_transferred 事件 | AC-06 | WS 广播验证 |
| autonomy_loop → Agent 决策 transfer_resource | AC-07 | execute_decisions 成功执行 |
| 前端交易面板手动转赠 → 成功 | AC-08 | API 调用 + 页面更新 |
| 前端收到 resource_transferred → 转赠历史更新 | AC-09 | TradePage 列表新增条目 |
| 代码中有 TODO 标记 function calling 降级假设 | AC-10 | grep 验证 |

---

## 9. 开发顺序

```
Phase 1: tool_registry.py 新建 + city_service 补广播（M5.1-1, M5.1-4）— 可并行
Phase 2: agent_runner 集成 Tool Use（M5.1-2）— 依赖 Phase 1 的 tool_registry
Phase 3: autonomy_service 扩展（M5.1-3）— 依赖 Phase 1 的广播
Phase 4: 前端 React Router + 类型/API + TradePage（M5.1-6, M5.1-7, M5.1-8）— 与 Phase 2/3 可并行
Phase 5: 端到端验证（M5.1-9）— 依赖全部
```

Phase 1 完成后跑 tool_registry UT + 转赠广播验证。Phase 2 完成后跑 agent_runner 集成测试（mock LLM）。Phase 3 完成后跑 autonomy UT。Phase 4 完成后跑前端手动验证。Phase 5 跑全链路 E2E（10 个 AC）。

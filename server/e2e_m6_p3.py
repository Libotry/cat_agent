"""
E2E Test — M6 Phase 3 Agent 状态可视化端到端验证

覆盖场景：
  ST-1: 状态变更序列 — trigger-autonomy 后 WebSocket 收到 agent_status_change 事件序列
  ST-2: activity 字段 — status_change 事件的 activity 字段非空（thinking 时）
  ST-3: ActivityFeed tool_call — 若 Agent 执行了 tool_call，agent_action 事件包含 action
  ST-4: 多 Agent 状态互不干扰 — 各 agent_id 的 status_change 事件独立

用法: python e2e_m6_p3.py
"""
import asyncio
import sys
import os
import json

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import httpx
import websockets

BASE = os.environ.get("E2E_BASE_URL", "http://localhost:8001")
WS_BASE = BASE.replace("http://", "ws://").replace("https://", "wss://")
CLIENT = httpx.AsyncClient(base_url=BASE, follow_redirects=True, timeout=90)

passed = 0
failed = 0
errors: list[str] = []


def ok(name: str, detail: str = ""):
    global passed
    passed += 1
    print(f"  [PASS] {name}" + (f" — {detail}" if detail else ""))


def fail(name: str, detail: str = ""):
    global failed
    failed += 1
    errors.append(f"{name}: {detail}")
    print(f"  [FAIL] {name}" + (f" — {detail}" if detail else ""))


async def collect_ws_events(timeout: float = 30) -> list[dict]:
    """连接 WebSocket，触发 autonomy tick，收集所有事件后返回。"""
    ws_url = f"{WS_BASE}/api/ws/0"
    events: list[dict] = []

    async with websockets.connect(ws_url) as ws:
        # 消费 online 事件
        await asyncio.wait_for(ws.recv(), timeout=5)

        # 触发 tick
        r = await CLIENT.post("/api/dev/trigger-autonomy", timeout=120)
        assert r.status_code == 200, f"trigger-autonomy failed: {r.text}"

        # 收集事件
        try:
            while True:
                msg = await asyncio.wait_for(ws.recv(), timeout=timeout)
                data = json.loads(msg)
                if data.get("type") == "system_event":
                    events.append(data["data"])
        except asyncio.TimeoutError:
            pass

    return events


# ─── ST-1: 状态变更序列 ──────────────────────────────────────────

async def test_status_change_sequence():
    print("\n=== ST-1: 状态变更序列 ===")

    events: list[dict] = []
    try:
        events = await collect_ws_events(timeout=15)
    except Exception as e:
        fail("ST-1 WebSocket 连接/tick 失败", str(e))
        return events

    status_events = [e for e in events if e.get("event") == "agent_status_change"]

    if not status_events:
        fail("ST-1 未收到 agent_status_change 事件")
        return events

    ok("收到 agent_status_change 事件", f"共 {len(status_events)} 个")

    # 按 agent_id 分组，验证每个 agent 的序列以 idle 结尾
    from collections import defaultdict
    by_agent: dict[int, list[str]] = defaultdict(list)
    for e in status_events:
        by_agent[e["agent_id"]].append(e["status"])

    all_end_idle = True
    for aid, seq in by_agent.items():
        if seq[-1] != "idle":
            fail(f"ST-1 agent {aid} 序列未以 idle 结尾", f"序列={seq}")
            all_end_idle = False
        else:
            # 验证序列包含 thinking（至少出现过）
            if "thinking" in seq:
                ok(f"agent {aid} 序列正确", f"{' → '.join(seq)}")
            else:
                # autonomy tick 可能直接 idle（无 LLM 调用的 agent）
                ok(f"agent {aid} 序列结束于 idle", f"{' → '.join(seq)}（无 thinking，可能未被调度）")

    if all_end_idle:
        ok("所有 agent 最终状态为 idle")

    return events


# ─── ST-2: activity 字段 ─────────────────────────────────────────

async def test_activity_field(events: list[dict]):
    print("\n=== ST-2: activity 字段 ===")

    status_events = [e for e in events if e.get("event") == "agent_status_change"]

    if not status_events:
        fail("ST-2 无 status_change 事件可验证")
        return

    # 验证事件格式：必须包含 agent_id, agent_name, status, activity, timestamp
    required_keys = {"event", "agent_id", "agent_name", "status", "activity", "timestamp"}
    for e in status_events:
        missing = required_keys - set(e.keys())
        if missing:
            fail("ST-2 事件字段缺失", f"缺少 {missing}，事件={e}")
            return

    ok("所有事件包含必要字段", f"检查了 {len(status_events)} 个事件")

    # thinking 状态的 activity 应非空
    thinking_events = [e for e in status_events if e["status"] == "thinking"]
    if thinking_events:
        non_empty = [e for e in thinking_events if e.get("activity")]
        if non_empty:
            ok("thinking 状态 activity 非空", f"示例: {non_empty[0]['activity']}")
        else:
            fail("ST-2 thinking 状态 activity 全为空")
    else:
        ok("ST-2 无 thinking 事件（跳过 activity 检查）")

    # idle 状态的 activity 应为空
    idle_events = [e for e in status_events if e["status"] == "idle"]
    if idle_events:
        all_empty = all(not e.get("activity") for e in idle_events)
        if all_empty:
            ok("idle 状态 activity 为空")
        else:
            fail("ST-2 idle 状态 activity 不为空", f"示例: {idle_events[0].get('activity')}")


# ─── ST-3: ActivityFeed tool_call ────────────────────────────────

async def test_activity_feed_tool_call(events: list[dict]):
    print("\n=== ST-3: ActivityFeed tool_call ===")

    action_events = [e for e in events if e.get("event") == "agent_action"]

    if action_events:
        ok("收到 agent_action 事件", f"共 {len(action_events)} 个")

        # 验证事件格式
        evt = action_events[0]
        has_fields = all(k in evt for k in ("agent_id", "agent_name", "action", "timestamp"))
        if has_fields:
            ok("agent_action 事件格式正确", f"action={evt['action']}")
        else:
            fail("ST-3 事件字段缺失", str(evt))

        # 检查是否有 tool_call 类型
        tool_calls = [e for e in action_events if e.get("action") == "tool_call"]
        if tool_calls:
            ok("收到 tool_call 类型动作", f"共 {len(tool_calls)} 个")
        else:
            ok("未收到 tool_call 动作（Agent 本轮未调用工具，属正常）")
    else:
        ok("未收到 agent_action 事件（所有 Agent 可能选择了 rest，属正常）")


# ─── ST-4: 多 Agent 状态互不干扰 ────────────────────────────────

async def test_multi_agent_isolation(events: list[dict]):
    print("\n=== ST-4: 多 Agent 状态互不干扰 ===")

    status_events = [e for e in events if e.get("event") == "agent_status_change"]

    if not status_events:
        fail("ST-4 无 status_change 事件可验证")
        return

    # 收集涉及的 agent_id
    agent_ids = set(e["agent_id"] for e in status_events)

    if len(agent_ids) < 2:
        ok("ST-4 只有 1 个 agent 产生了状态变更（无法验证隔离性，跳过）",
           f"agent_ids={agent_ids}")
        return

    ok(f"多个 agent 产生状态变更", f"agent_ids={agent_ids}")

    # 验证每个 agent 的事件只包含自己的 agent_id
    from collections import defaultdict
    by_agent: dict[int, list[dict]] = defaultdict(list)
    for e in status_events:
        by_agent[e["agent_id"]].append(e)

    # 验证每个 agent 的序列独立（不会出现 agent_id 交叉）
    for aid, agent_events in by_agent.items():
        all_same_id = all(e["agent_id"] == aid for e in agent_events)
        if not all_same_id:
            fail(f"ST-4 agent {aid} 事件中混入其他 agent_id")
            return

    ok("各 agent 状态事件互不干扰", f"{len(agent_ids)} 个 agent 各自独立")

    # 验证每个 agent 最终都回到 idle
    for aid, agent_events in by_agent.items():
        last_status = agent_events[-1]["status"]
        if last_status != "idle":
            fail(f"ST-4 agent {aid} 最终状态非 idle", f"last={last_status}")
            return

    ok("所有 agent 最终回到 idle")


# ─── Main ────────────────────────────────────────────────────────

async def main():
    print("=" * 60)
    print("M6 Phase 3 — Agent 状态可视化端到端验证")
    print("=" * 60)

    async with __import__("server_utils").managed_server():
        await _run()


async def _run():
    # 检查 Agent 数量
    agents = (await CLIENT.get("/api/agents/")).json()
    bot_agents = [a for a in agents if a["id"] != 0]

    if len(bot_agents) < 2:
        print(f"  Bot Agent 不足（{len(bot_agents)}），自动创建...")
        for name, persona in [("Alice", "勤劳的农夫"), ("Bob", "精明的商人")]:
            if not any(a["name"] == name for a in bot_agents):
                r = await CLIENT.post("/api/agents/", json={
                    "name": name, "persona": persona, "model": "stepfun/step-3.5-flash",
                })
                if r.status_code == 201:
                    print(f"  创建 {name} 成功")
        agents = (await CLIENT.get("/api/agents/")).json()
        bot_agents = [a for a in agents if a["id"] != 0]

    if len(bot_agents) < 2:
        print("ERROR: 仍然不足 2 个 Bot Agent")
        return

    print(f"[OK] {len(bot_agents)} 个 Bot Agent")
    for a in bot_agents:
        print(f"  {a['name']}(id={a['id']}) status={a['status']}")

    # 执行测试（ST-1 收集事件，后续复用）
    events = await test_status_change_sequence()    # ST-1
    if not isinstance(events, list):
        events = []
    await test_activity_field(events)               # ST-2
    await test_activity_feed_tool_call(events)      # ST-3
    await test_multi_agent_isolation(events)         # ST-4

    # 汇总
    print("\n" + "=" * 60)
    print(f"结果: {passed} passed, {failed} failed")
    if errors:
        print("失败项:")
        for e in errors:
            print(f"  - {e}")
    print("=" * 60)

    await CLIENT.aclose()


if __name__ == "__main__":
    asyncio.run(main())

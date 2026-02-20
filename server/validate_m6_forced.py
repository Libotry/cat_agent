"""
M6 Phase 1 T4 — 强制触发测试（排除看护问题）

目标：构造极端场景，LLM 看到后必须输出策略
- Alice: wheat=0, 在农田工作，体力100 → 必须 keep_working
- Bob: flour=0, credits=100, 市场有超低价 flour (单价 0.1) → 必须 opportunistic_buy

用法：python validate_m6_forced.py
"""
import asyncio
import sys
import os

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import httpx

BASE = os.environ.get("E2E_BASE_URL", "http://localhost:8001")
CLIENT = httpx.AsyncClient(base_url=BASE, follow_redirects=True, timeout=60)


async def setup_forced_scenario():
    """构造极端场景：资源为 0 + 超低价市场单"""
    print("[setup] 构造强制触发场景...")

    # 创建 agents
    agents = (await CLIENT.get("/api/agents/")).json()
    bot_agents = [a for a in agents if a["id"] != 0]

    if len(bot_agents) < 2:
        await CLIENT.post("/api/agents/", json={
            "name": "Alice",
            "persona": "农夫，急需囤积小麦过冬，目标 50 单位",
            "model": "stepfun/step-3.5-flash",
        })
        await CLIENT.post("/api/agents/", json={
            "name": "Bob",
            "persona": "商人，看到低价就买，flour 目标 20 单位",
            "model": "stepfun/step-3.5-flash",
        })
        agents = (await CLIENT.get("/api/agents/")).json()
        bot_agents = [a for a in agents if a["id"] != 0]

    agent1, agent2 = bot_agents[0], bot_agents[1]

    # 找 farm
    buildings = (await CLIENT.get("/api/cities/长安/buildings")).json()
    farm = next((b for b in buildings if b["building_type"] == "farm" and b.get("status") == "active"), None)
    if not farm:
        print("[setup] ERROR: 没有 active farm")
        return None, None, None

    # Alice: wheat=0（极端缺乏），在农田工作，体力 100
    await CLIENT.put(f"/api/agents/{agent1['id']}", json={"stamina": 100, "satiety": 100, "mood": 100})
    await CLIENT.post("/api/dev/set-resource",
                      params={"agent_id": agent1["id"], "resource_type": "wheat", "quantity": 0})
    await CLIENT.post("/api/dev/set-resource",
                      params={"agent_id": agent1["id"], "resource_type": "credits", "quantity": 10})

    # 确保 Alice 在农田工作
    r = await CLIENT.get(f"/api/cities/长安/buildings/{farm['id']}/workers")
    workers = r.json() if r.status_code == 200 else []
    if not any(w["agent_id"] == agent1["id"] for w in workers):
        await CLIENT.post(f"/api/cities/长安/buildings/{farm['id']}/workers",
                          json={"agent_id": agent1["id"]})

    # Bob: flour=0（极端缺乏），credits=100，市场有超低价 flour（单价 0.1）
    await CLIENT.put(f"/api/agents/{agent2['id']}", json={"stamina": 100, "satiety": 100, "mood": 100})
    await CLIENT.post("/api/dev/set-resource",
                      params={"agent_id": agent2["id"], "resource_type": "flour", "quantity": 0})
    await CLIENT.post("/api/dev/set-resource",
                      params={"agent_id": agent2["id"], "resource_type": "credits", "quantity": 100})

    # 清空旧挂单
    existing_orders = (await CLIENT.get("/api/market/orders")).json()
    for o in existing_orders:
        if o["status"] in ("open", "partial"):
            await CLIENT.post(f"/api/market/orders/{o['id']}/cancel",
                              json={"seller_id": o["seller_id"]})

    # 挂超低价 flour 单：30 flour for 3 credits（单价 0.1，正常价 2.0）
    await CLIENT.post("/api/dev/set-resource",
                      params={"agent_id": 0, "resource_type": "flour", "quantity": 100})
    r = await CLIENT.post("/api/market/orders", json={
        "seller_id": 0,
        "sell_type": "flour", "sell_amount": 30.0,
        "buy_type": "credits", "buy_amount": 3.0,
    })
    if r.status_code == 200 and r.json().get("ok"):
        print(f"  超低价 flour 挂单成功: 30 flour for 3 credits (单价 0.1)")
    else:
        print(f"  挂单失败: {r.text[:80]}")

    print(f"[setup] 完成:")
    print(f"  Alice(id={agent1['id']}): wheat=0, 在农田工作, 体力100 → 必须 keep_working")
    print(f"  Bob(id={agent2['id']}): flour=0, credits=100, 超低价单 → 必须 opportunistic_buy")
    return agent1["id"], agent2["id"], farm["id"]


async def test_forced_trigger():
    """单轮测试：调用 LLM，验证是否输出策略"""
    print("\n[test] 调用 LLM decide()...")

    r = await CLIENT.post("/api/dev/probe-llm-decide")
    if r.status_code != 200:
        print(f"  [FAIL] API 调用失败: {r.status_code}")
        return False

    data = r.json()
    if not data.get("ok"):
        print(f"  [FAIL] {data.get('reason')}")
        return False

    actions = data.get("actions", [])
    strategies = data.get("strategies", [])

    print(f"\n[result] actions: {len(actions)} 条, strategies: {len(strategies)} 条")

    if len(strategies) == 0:
        print("  ❌ FAIL: 没有输出策略")
        print("\n  actions:")
        for a in actions:
            print(f"    - agent={a.get('agent_id')} action={a.get('action')} reason={a.get('reason', '')[:50]}")
        return False

    # 检查策略类型
    has_keep_working = any(s.get("strategy") == "keep_working" for s in strategies)
    has_opportunistic_buy = any(s.get("strategy") == "opportunistic_buy" for s in strategies)

    print("\n  strategies:")
    for s in strategies:
        print(f"    - agent={s.get('agent_id')} strategy={s.get('strategy')}")
        print(f"      {s}")

    if has_keep_working and has_opportunistic_buy:
        print("\n  ✅ PASS: 两种策略都触发")
        return True
    elif has_keep_working:
        print("\n  ⚠️  PARTIAL: 只触发了 keep_working，缺少 opportunistic_buy")
        return False
    elif has_opportunistic_buy:
        print("\n  ⚠️  PARTIAL: 只触发了 opportunistic_buy，缺少 keep_working")
        return False
    else:
        print("\n  ❌ FAIL: 输出了策略但类型不对")
        return False


async def main():
    print("=" * 60)
    print("M6 Phase 1 T4 — 强制触发测试")
    print("=" * 60)

    async with __import__("server_utils").managed_server():
        await _run()


async def _run():
    try:
        r = await CLIENT.get("/api/health")
        if r.status_code != 200:
            print("ERROR: 服务器未启动")
            return
    except Exception:
        print("ERROR: 无法连接服务器")
        return

    print("[OK] 服务器在线\n")

    agent1_id, agent2_id, farm_id = await setup_forced_scenario()
    if not agent1_id:
        return

    success = await test_forced_trigger()

    print("\n" + "=" * 60)
    if success:
        print("✅ 结论: 强制触发成功，prompt 能正确识别极端场景")
    else:
        print("❌ 结论: 强制触发失败，prompt 需要进一步优化")
    print("=" * 60)

    await CLIENT.aclose()


if __name__ == "__main__":
    asyncio.run(main())

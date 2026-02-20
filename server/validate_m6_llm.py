"""
M6 Phase 1 T4 — LLM 输出质量验证（Go/No-Go 关卡）

目标：手动跑 5-10 轮 LLM，统计策略 JSON 解析成功率
成功标准：成功率 >= 70% → Go，继续 Phase 1；< 70% → 调整 prompt/schema

用法：python validate_m6_llm.py
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

ROUNDS = 10  # 验证轮数


async def setup_env():
    """准备测试环境：构造能触发策略的场景

    场景设计：
    - Alice（农夫）：在农田工作，wheat 只有 5，体力充足 → 应触发 keep_working
    - Bob（商人）：有 credits=100，flour=0，市场有低价 flour 挂单 → 应触发 opportunistic_buy
    """
    print("[setup] 准备测试环境...")

    # 创建 2 个 agents
    agents = (await CLIENT.get("/api/agents/")).json()
    bot_agents = [a for a in agents if a["id"] != 0]

    if len(bot_agents) < 2:
        for name, persona in [("Alice", "勤劳的农夫，目标是囤积足够的小麦过冬"), ("Bob", "精明的商人，善于发现市场低价机会")]:
            if not any(a["name"] == name for a in bot_agents):
                await CLIENT.post("/api/agents/", json={
                    "name": name, "persona": persona, "model": "stepfun/step-3.5-flash",
                })
        agents = (await CLIENT.get("/api/agents/")).json()
        bot_agents = [a for a in agents if a["id"] != 0]

    agent1, agent2 = bot_agents[0], bot_agents[1]

    # 确保有 farm 建筑
    buildings = (await CLIENT.get("/api/cities/长安/buildings")).json()
    farm = next((b for b in buildings if b["building_type"] == "farm" and b.get("status") == "active"), None)
    if not farm:
        print("[setup] ERROR: 没有 active farm 建筑")
        return None, None, None

    # Alice：在农田工作，wheat 只有 5（明显不够，应该持续生产）
    await CLIENT.put(f"/api/agents/{agent1['id']}", json={"stamina": 100})
    await CLIENT.post("/api/dev/set-resource",
                      params={"agent_id": agent1["id"], "resource_type": "wheat", "quantity": 5})
    await CLIENT.post("/api/dev/set-resource",
                      params={"agent_id": agent1["id"], "resource_type": "credits", "quantity": 10})
    # 确保 Alice 在农田工作
    r = await CLIENT.get(f"/api/cities/长安/buildings/{farm['id']}/workers")
    workers = r.json() if r.status_code == 200 else []
    if not any(w["agent_id"] == agent1["id"] for w in workers):
        await CLIENT.post(f"/api/cities/长安/buildings/{farm['id']}/workers",
                          json={"agent_id": agent1["id"]})

    # Bob：有 credits=100，flour=0，市场有低价 flour 挂单（单价 0.8，远低于正常价）
    await CLIENT.put(f"/api/agents/{agent2['id']}", json={"stamina": 100})
    await CLIENT.post("/api/dev/set-resource",
                      params={"agent_id": agent2["id"], "resource_type": "credits", "quantity": 100})
    await CLIENT.post("/api/dev/set-resource",
                      params={"agent_id": agent2["id"], "resource_type": "flour", "quantity": 0})

    # 清空旧挂单，挂一个明显低价的 flour 单
    existing_orders = (await CLIENT.get("/api/market/orders")).json()
    for o in existing_orders:
        if o["status"] in ("open", "partial"):
            await CLIENT.post(f"/api/market/orders/{o['id']}/cancel",
                              json={"seller_id": o["seller_id"]})

    # 用 Human(id=0) 挂单：20 flour for 16 credits（单价 0.8，市场正常价约 2.0）
    await CLIENT.post("/api/dev/set-resource",
                      params={"agent_id": 0, "resource_type": "flour", "quantity": 50})
    r = await CLIENT.post("/api/market/orders", json={
        "seller_id": 0,
        "sell_type": "flour", "sell_amount": 20.0,
        "buy_type": "credits", "buy_amount": 16.0,
    })
    if r.status_code == 200 and r.json().get("ok"):
        print(f"  [setup] 低价 flour 挂单成功: 20 flour for 16 credits (单价 0.8)")
    else:
        print(f"  [setup] 挂单失败: {r.text[:80]}")

    print(f"[setup] 完成:")
    print(f"  Alice(id={agent1['id']}): 在农田工作, wheat=5, credits=10 → 期望触发 keep_working")
    print(f"  Bob(id={agent2['id']}): flour=0, credits=100, 市场有低价单 → 期望触发 opportunistic_buy")
    return agent1["id"], agent2["id"], farm["id"]


async def trigger_hourly_tick() -> dict:
    """触发一次 hourly tick，返回 LLM 原始输出 + 解析结果"""
    r = await CLIENT.post("/api/dev/trigger-autonomy")
    if r.status_code != 200:
        return {"error": f"trigger failed: {r.status_code}"}

    # 等待 tick 完成（autonomy tick 是异步的，需要等一下）
    await asyncio.sleep(2)

    # 获取所有 agents 的策略（验证是否成功解析）
    r = await CLIENT.get("/api/agents/strategies/all")
    if r.status_code != 200:
        return {"error": f"get strategies failed: {r.status_code}"}

    strategies = r.json()
    return {"strategies": strategies}


async def reset_round(agent1_id: int, agent2_id: int):
    """每轮前重置状态，保持场景一致"""
    await CLIENT.post("/api/dev/set-resource",
                      params={"agent_id": agent1_id, "resource_type": "wheat", "quantity": 5})
    await CLIENT.post("/api/dev/set-resource",
                      params={"agent_id": agent2_id, "resource_type": "flour", "quantity": 0})
    await CLIENT.post("/api/dev/set-resource",
                      params={"agent_id": agent2_id, "resource_type": "credits", "quantity": 100})
    # 确保市场有低价单
    orders = (await CLIENT.get("/api/market/orders")).json()
    has_cheap = any(
        o["sell_type"] == "flour" and o["status"] in ("open", "partial")
        and o["remain_buy_amount"] / o["remain_sell_amount"] < 1.0
        for o in orders
    )
    if not has_cheap:
        await CLIENT.post("/api/dev/set-resource",
                          params={"agent_id": 0, "resource_type": "flour", "quantity": 50})
        await CLIENT.post("/api/market/orders", json={
            "seller_id": 0,
            "sell_type": "flour", "sell_amount": 20.0,
            "buy_type": "credits", "buy_amount": 16.0,
        })


async def validate_round(round_num: int, agent1_id: int, agent2_id: int) -> dict:
    """执行一轮验证，返回结果"""
    print(f"\n=== Round {round_num} ===")

    r = await CLIENT.post("/api/dev/probe-llm-decide")
    if r.status_code != 200:
        print(f"  [FAIL] API 调用失败: {r.status_code} {r.text[:100]}")
        return {"success": False, "reason": f"status={r.status_code}"}

    data = r.json()

    if not data.get("ok"):
        print(f"  [FAIL] {data.get('reason')}")
        return {"success": False, "reason": data.get("reason")}

    actions_count = data.get("actions_count", 0)
    strategies_count = data.get("strategies_count", 0)
    strategies = data.get("strategies", [])
    actions = data.get("actions", [])

    print(f"  actions: {actions_count} 条, strategies: {strategies_count} 条")

    if actions_count > 0 or strategies_count > 0:
        print(f"  [PASS] JSON 解析成功")
        if strategies:
            for s in strategies:
                print(f"    策略: {s.get('strategy')} agent={s.get('agent_id')} {s}")
        if actions:
            for a in actions[:3]:  # 只打印前 3 条
                print(f"    行为: {a.get('action')} agent={a.get('agent_id')} reason={a.get('reason', '')[:30]}")
        return {"success": True, "actions_count": actions_count, "strategies_count": strategies_count}
    else:
        # LLM 返回了空的 actions 和 strategies，可能是 JSON 解析失败或模型返回空
        print(f"  [WARN] actions=0, strategies=0（可能解析失败或模型返回空）")
        return {"success": False, "reason": "empty output"}


async def main():
    print("=" * 60)
    print("M6 Phase 1 T4 — LLM 输出质量验证")
    print("=" * 60)

    async with __import__("server_utils").managed_server():
        await _run()


async def _run():
    print("=" * 60)
    print("M6 Phase 1 T4 — LLM 输出质量验证")
    print("=" * 60)

async def _run():
    # 健康检查
    try:
        r = await CLIENT.get("/api/health")
        if r.status_code != 200:
            print("ERROR: 服务器未启动")
            return
    except Exception:
        print("ERROR: 无法连接服务器")
        return

    print("[OK] 服务器在线")

    # 环境准备
    agent1_id, agent2_id, farm_id = await setup_env()
    if not agent1_id:
        return

    # 执行 N 轮验证
    results = []
    for i in range(1, ROUNDS + 1):
        await reset_round(agent1_id, agent2_id)
        result = await validate_round(i, agent1_id, agent2_id)
        results.append(result)
        await asyncio.sleep(1)  # 避免 rate limit

    # 统计
    print("\n" + "=" * 60)
    print("验证结果汇总")
    print("=" * 60)

    success_count = sum(1 for r in results if r.get("success"))
    strategy_rounds = sum(1 for r in results if r.get("strategies_count", 0) > 0)
    total_strategies = sum(r.get("strategies_count", 0) for r in results)

    success_rate = success_count / len(results) * 100
    strategy_rate = strategy_rounds / len(results) * 100

    print(f"总轮数: {len(results)}")
    print(f"JSON 解析成功轮数: {success_count} ({success_rate:.1f}%)")
    print(f"输出策略轮数: {strategy_rounds} ({strategy_rate:.1f}%)")
    print(f"策略总数: {total_strategies}")

    print("\n" + "=" * 60)
    if success_rate >= 70:
        print(f"✅ Go/No-Go 结论: GO (JSON 解析成功率 {success_rate:.1f}% >= 70%)")
        if strategy_rate < 50:
            print(f"⚠️  注意: 策略输出率仅 {strategy_rate:.1f}%，模型倾向于只输出 actions")
    else:
        print(f"❌ Go/No-Go 结论: NO-GO (JSON 解析成功率 {success_rate:.1f}% < 70%)")
        print("需要调整 SYSTEM_PROMPT 或简化 schema")
    print("=" * 60)

    await CLIENT.aclose()


if __name__ == "__main__":
    asyncio.run(main())

"""
E2E Test — M6 Phase 1 策略自动机端到端验证

覆盖场景：
  ST-1: keep_working 策略 — 触发 hourly tick，验证策略执行 + 资源增加 + 达标后完成
  ST-2: opportunistic_buy 策略 — 挂低价单，验证自动接单 + 资源增加 + 达标后完成
  ST-3: opportunistic_buy 跳过高价单 — 市场只有高价单，验证策略跳过不执行
  ST-4: 策略观测 API — GET /api/agents/{id}/strategies 返回正确数据

用法: 先启动服务器 (uvicorn main:app --port 8001)，然后 python e2e_m6.py
"""
import asyncio
import sys
import os

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import httpx

BASE = os.environ.get("E2E_BASE_URL", "http://localhost:8001")
CLIENT = httpx.AsyncClient(base_url=BASE, follow_redirects=True, timeout=30)

passed = 0
failed = 0
errors: list[str] = []


def ok(name: str, detail: str = ""):
    global passed
    passed += 1
    print(f"  [PASS] {name}" + (f" — {detail}" if detail else ""))


def fail(name: str, detail: str = ""):
    global failed
    errors.append(f"{name}: {detail}")
    print(f"  [FAIL] {name}" + (f" — {detail}" if detail else ""))


async def get_agent_resources(agent_id: int) -> dict:
    r = await CLIENT.get(f"/api/agents/{agent_id}/resources")
    return {item["resource_type"]: item["quantity"] for item in r.json()}


async def reset_env(agent_id: int):
    """重置 agent 状态：恢复体力、补充 credits、清空策略"""
    await CLIENT.put(f"/api/agents/{agent_id}", json={"stamina": 100})
    await CLIENT.post("/api/dev/set-resource",
                      json={"agent_id": agent_id, "resource_type": "credits", "quantity": 200})
    await CLIENT.delete(f"/api/agents/{agent_id}/strategies")


async def ensure_farm_worker(agent_id: int, farm_id: int):
    """确保 agent 在农田工作（幂等）"""
    r = await CLIENT.get(f"/api/cities/长安/buildings/{farm_id}/workers")
    if r.status_code == 200:
        workers = r.json()
        if any(w["agent_id"] == agent_id for w in workers):
            return
    await CLIENT.post(f"/api/cities/长安/buildings/{farm_id}/workers",
                      json={"agent_id": agent_id})


async def get_or_create_farm(city: str = "长安") -> int | None:
    """获取或创建一个 farm 建筑，返回 building_id"""
    r = await CLIENT.get(f"/api/cities/{city}/buildings")
    if r.status_code == 200:
        farm = next((b for b in r.json()
                     if b["building_type"] == "farm" and b.get("status") == "active"), None)
        if farm:
            return farm["id"]
    # 没有 active farm，尝试创建（需要 wood/stone）
    return None


# ─── ST-1: keep_working 策略端到端 ──────────────────────────────

async def test_keep_working(agent_id: int, farm_id: int):
    print("\n=== ST-1: keep_working 策略端到端 ===")

    # 环境重置
    await reset_env(agent_id)

    # 清空 wheat（通过 dev API 设置资源）
    await CLIENT.post("/api/dev/set-resource",
                      json={"agent_id": agent_id, "resource_type": "wheat", "quantity": 0})

    # 确保 agent 在农田工作
    await ensure_farm_worker(agent_id, farm_id)

    # 设置 keep_working 策略：持续工作直到 wheat >= 30
    r = await CLIENT.post(f"/api/agents/{agent_id}/strategies", json=[{
        "agent_id": agent_id,
        "strategy": "keep_working",
        "building_id": farm_id,
        "stop_when_resource": "wheat",
        "stop_when_amount": 30
    }])
    if r.status_code != 200:
        fail("ST-1 设置策略", f"status={r.status_code}, body={r.text[:100]}")
        return

    ok("策略设置成功")

    # 触发 execute_strategies（通过 hourly tick dev API）
    r = await CLIENT.post("/api/dev/execute-strategies")
    if r.status_code != 200:
        fail("ST-1 执行策略", f"status={r.status_code}, body={r.text[:100]}")
        return

    stats = r.json()
    print(f"  执行结果: {stats}")

    # 触发生产（farm 每次 +10 wheat）
    await CLIENT.post("/api/cities/长安/production-tick")

    # 验证资源增加
    res = await get_agent_resources(agent_id)
    wheat = res.get("wheat", 0)
    if wheat > 0:
        ok("keep_working 触发生产", f"wheat={wheat}")
    else:
        fail("ST-1 资源", f"wheat 未增加，当前={wheat}")
        return

    # 设置 wheat 接近目标，再触发一次
    await CLIENT.post("/api/dev/set-resource",
                      json={"agent_id": agent_id, "resource_type": "wheat", "quantity": 25})
    await CLIENT.post("/api/cities/长安/production-tick")

    res = await get_agent_resources(agent_id)
    wheat = res.get("wheat", 0)
    if wheat >= 30:
        ok("wheat 达到目标", f"wheat={wheat}")
    else:
        fail("ST-1 达标", f"wheat={wheat} < 30")
        return

    # 再次执行策略，应该标记为 completed
    r = await CLIENT.post("/api/dev/execute-strategies")
    if r.status_code == 200:
        stats = r.json()
        if stats.get("completed", 0) >= 1:
            ok("策略达标后标记 completed", f"stats={stats}")
        else:
            fail("ST-1 completed", f"期望 completed>=1, 实际 stats={stats}")
    else:
        fail("ST-1 第二次执行", f"status={r.status_code}")


# ─── ST-2: opportunistic_buy 策略端到端 ─────────────────────────

async def test_opportunistic_buy(buyer_id: int, seller_id: int):
    print("\n=== ST-2: opportunistic_buy 策略端到端 ===")

    # 环境重置
    await reset_env(buyer_id)
    await reset_env(seller_id)

    # 清空 buyer 的 flour
    await CLIENT.post("/api/dev/set-resource",
                      json={"agent_id": buyer_id, "resource_type": "flour", "quantity": 0})

    # 确保 seller 有 flour 可以挂单
    await CLIENT.post("/api/dev/set-resource",
                      json={"agent_id": seller_id, "resource_type": "flour", "quantity": 50})

    # seller 挂低价单：30 flour for 24 credits（单价 0.8 < 1.5）
    r = await CLIENT.post("/api/market/orders", json={
        "seller_id": seller_id,
        "sell_type": "flour", "sell_amount": 30.0,
        "buy_type": "credits", "buy_amount": 24.0,
    })
    if r.status_code != 200 or not r.json().get("ok"):
        fail("ST-2 挂单", f"status={r.status_code}, body={r.text[:100]}")
        return
    order_id = r.json()["order_id"]
    ok("低价单挂单成功", f"order_id={order_id}, 单价=0.8")

    # 设置 opportunistic_buy 策略：flour 低于 1.5 就买，直到库存 >= 20
    r = await CLIENT.post(f"/api/agents/{buyer_id}/strategies", json=[{
        "agent_id": buyer_id,
        "strategy": "opportunistic_buy",
        "resource": "flour",
        "price_below": 1.5,
        "stop_when_amount": 20
    }])
    if r.status_code != 200:
        fail("ST-2 设置策略", f"status={r.status_code}, body={r.text[:100]}")
        return

    ok("策略设置成功")

    # 执行策略
    r = await CLIENT.post("/api/dev/execute-strategies")
    if r.status_code != 200:
        fail("ST-2 执行策略", f"status={r.status_code}, body={r.text[:100]}")
        return

    stats = r.json()
    print(f"  执行结果: {stats}")

    if stats.get("executed", 0) >= 1:
        ok("策略自动接单", f"executed={stats['executed']}")
    else:
        fail("ST-2 接单", f"期望 executed>=1, 实际 stats={stats}")
        return

    # 验证 buyer 资源增加
    res = await get_agent_resources(buyer_id)
    flour = res.get("flour", 0)
    if flour >= 20:
        ok("buyer flour 达标", f"flour={flour}")
    else:
        fail("ST-2 资源", f"flour={flour} < 20")
        return

    # 再次执行策略，应该标记为 completed
    r = await CLIENT.post("/api/dev/execute-strategies")
    if r.status_code == 200:
        stats = r.json()
        if stats.get("completed", 0) >= 1:
            ok("策略达标后标记 completed", f"stats={stats}")
        else:
            fail("ST-2 completed", f"期望 completed>=1, 实际 stats={stats}")
    else:
        fail("ST-2 第二次执行", f"status={r.status_code}")


# ─── ST-3: opportunistic_buy 跳过高价单 ─────────────────────────

async def test_opportunistic_buy_skips_expensive(buyer_id: int, seller_id: int):
    print("\n=== ST-3: opportunistic_buy 跳过高价单 ===")

    await reset_env(buyer_id)
    await reset_env(seller_id)

    # 清空 buyer 的 flour
    await CLIENT.post("/api/dev/set-resource",
                      json={"agent_id": buyer_id, "resource_type": "flour", "quantity": 0})

    # seller 挂高价单：10 flour for 30 credits（单价 3.0 > 1.5）
    await CLIENT.post("/api/dev/set-resource",
                      json={"agent_id": seller_id, "resource_type": "flour", "quantity": 20})
    r = await CLIENT.post("/api/market/orders", json={
        "seller_id": seller_id,
        "sell_type": "flour", "sell_amount": 10.0,
        "buy_type": "credits", "buy_amount": 30.0,
    })
    if r.status_code != 200 or not r.json().get("ok"):
        fail("ST-3 挂单", f"status={r.status_code}, body={r.text[:100]}")
        return
    order_id = r.json()["order_id"]
    ok("高价单挂单成功", f"order_id={order_id}, 单价=3.0")

    # 设置策略：flour 低于 1.5 就买
    r = await CLIENT.post(f"/api/agents/{buyer_id}/strategies", json=[{
        "agent_id": buyer_id,
        "strategy": "opportunistic_buy",
        "resource": "flour",
        "price_below": 1.5,
        "stop_when_amount": 20
    }])
    if r.status_code != 200:
        fail("ST-3 设置策略", f"status={r.status_code}")
        return

    # 执行策略（应该跳过高价单）
    r = await CLIENT.post("/api/dev/execute-strategies")
    if r.status_code != 200:
        fail("ST-3 执行策略", f"status={r.status_code}")
        return

    stats = r.json()
    print(f"  执行结果: {stats}")

    if stats.get("executed", 0) == 0:
        ok("高价单被跳过", f"skipped={stats.get('skipped', 0)}")
    else:
        fail("ST-3", f"期望 executed=0, 实际 executed={stats.get('executed')}")

    # 验证 buyer flour 未变化
    res = await get_agent_resources(buyer_id)
    flour = res.get("flour", 0)
    if flour == 0:
        ok("buyer flour 未变化", f"flour={flour}")
    else:
        fail("ST-3 资源", f"flour 不应增加，实际={flour}")

    # 清理挂单
    await CLIENT.post(f"/api/market/orders/{order_id}/cancel", json={"seller_id": seller_id})


# ─── ST-4: 策略观测 API ──────────────────────────────────────────

async def test_strategy_observation_api(agent_id: int, farm_id: int):
    print("\n=== ST-4: 策略观测 API ===")

    # 设置两条策略
    r = await CLIENT.post(f"/api/agents/{agent_id}/strategies", json=[
        {
            "agent_id": agent_id,
            "strategy": "keep_working",
            "building_id": farm_id,
            "stop_when_resource": "wheat",
            "stop_when_amount": 50
        },
        {
            "agent_id": agent_id,
            "strategy": "opportunistic_buy",
            "resource": "flour",
            "price_below": 1.5,
            "stop_when_amount": 20
        }
    ])
    if r.status_code != 200:
        fail("ST-4 设置策略", f"status={r.status_code}, body={r.text[:100]}")
        return

    # 查询策略
    r = await CLIENT.get(f"/api/agents/{agent_id}/strategies")
    if r.status_code != 200:
        fail("ST-4 查询 API", f"status={r.status_code}")
        return

    data = r.json()
    if len(data) != 2:
        fail("ST-4 策略数量", f"期望 2, 实际 {len(data)}")
        return

    ok("策略数量正确", f"count={len(data)}")

    s1 = data[0]
    if s1.get("strategy") == "keep_working" and s1.get("building_id") == farm_id:
        ok("keep_working 策略字段正确",
           f"building_id={s1['building_id']}, stop_when={s1.get('stop_when_resource')}={s1.get('stop_when_amount')}")
    else:
        fail("ST-4 keep_working", f"实际={s1}")

    s2 = data[1]
    if s2.get("strategy") == "opportunistic_buy" and s2.get("resource") == "flour":
        ok("opportunistic_buy 策略字段正确",
           f"resource={s2['resource']}, price_below={s2.get('price_below')}")
    else:
        fail("ST-4 opportunistic_buy", f"实际={s2}")


# ─── Main ────────────────────────────────────────────────────────

async def main():
    print("=" * 60)
    print("M6 Phase 1 — 策略自动机端到端验证")
    print("=" * 60)
    async with __import__("server_utils").managed_server():
        await _run()

async def _run():
    # 获取 agents
    agents = (await CLIENT.get("/api/agents/")).json()
    ST_MODEL = "stepfun/step-3.5-flash"
    bot_agents = [a for a in agents if a["id"] != 0]

    if len(bot_agents) < 2:
        print(f"  Bot Agent 不足（{len(bot_agents)}），自动创建...")
        for name, persona in [("Alice", "勤劳的农夫"), ("Bob", "精明的商人")]:
            if not any(a["name"] == name for a in bot_agents):
                r = await CLIENT.post("/api/agents/", json={
                    "name": name, "persona": persona, "model": ST_MODEL,
                })
                if r.status_code == 201:
                    print(f"  创建 {name} 成功")
        agents = (await CLIENT.get("/api/agents/")).json()
        bot_agents = [a for a in agents if a["id"] != 0]

    if len(bot_agents) < 2:
        print("ERROR: 仍然不足 2 个 Bot Agent")
        return

    agent1 = bot_agents[0]
    agent2 = bot_agents[1]
    print(f"[OK] agent1={agent1['name']}(id={agent1['id']}), agent2={agent2['name']}(id={agent2['id']})")

    # 获取或确认 farm 建筑
    farm_id = await get_or_create_farm()
    if not farm_id:
        print("ERROR: 没有 active farm 建筑，请先创建")
        return
    print(f"[OK] farm_id={farm_id}")

    # 执行测试
    await test_keep_working(agent1["id"], farm_id)                              # ST-1
    await test_opportunistic_buy(agent1["id"], agent2["id"])                    # ST-2
    await test_opportunistic_buy_skips_expensive(agent1["id"], agent2["id"])    # ST-3
    await test_strategy_observation_api(agent1["id"], farm_id)                  # ST-4

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

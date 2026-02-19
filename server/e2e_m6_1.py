"""
E2E Test — M6.1 建造系统端到端验证

覆盖场景：
  ST-1: POST /construct 建造成功 + 资源扣除
  ST-2: POST /construct 资源不足失败
  ST-3: GET /constructing 建造中列表
  ST-4: 建造中建筑拒绝分配工人
  ST-5: production-tick 不会提前完成建造
  ST-6: WebSocket 收到 building_construction_started 广播

用法: 先启动服务器 (uvicorn main:app --port 8001)，然后 python e2e_m6_1.py
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
    failed += 1
    errors.append(f"{name}: {detail}")
    print(f"  [FAIL] {name}" + (f" — {detail}" if detail else ""))


async def set_resource(agent_id: int, res_type: str, qty: float):
    r = await CLIENT.post(f"/api/dev/set-resource?agent_id={agent_id}&resource_type={res_type}&quantity={qty}")
    assert r.status_code == 200, f"set-resource failed: {r.text}"


async def get_agent_resources(agent_id: int) -> dict:
    r = await CLIENT.get(f"/api/agents/{agent_id}/resources")
    return {item["resource_type"]: item["quantity"] for item in r.json()}


# ─── ST-1: 建造成功 + 资源扣除 ─────────────────────────────────

async def test_construct_success(builder_id: int) -> int | None:
    print("\n=== ST-1: POST /construct 建造成功 + 资源扣除 ===")
    await set_resource(builder_id, "wood", 20)
    await set_resource(builder_id, "stone", 10)
    res_before = await get_agent_resources(builder_id)
    wood_before = res_before.get("wood", 0)
    stone_before = res_before.get("stone", 0)
    print(f"  建造前: wood={wood_before}, stone={stone_before}")

    r = await CLIENT.post("/api/cities/长安/buildings/construct", json={
        "builder_id": builder_id, "building_type": "farm", "name": "ST测试农田",
    })
    if r.status_code != 200:
        fail("ST-1 API", f"status={r.status_code}, body={r.text}")
        return None
    body = r.json()
    if not body.get("ok"):
        fail("ST-1 结果", f"ok=False, reason={body.get('reason')}")
        return None
    building_id = body["building_id"]
    ok("建造请求成功", f"building_id={building_id}")

    res_after = await get_agent_resources(builder_id)
    wood_after = res_after.get("wood", 0)
    stone_after = res_after.get("stone", 0)
    if abs(wood_after - (wood_before - 10)) < 0.01:
        ok("wood 扣除正确", f"{wood_before} → {wood_after}")
    else:
        fail("ST-1 wood", f"期望 {wood_before - 10}, 实际 {wood_after}")
    if abs(stone_after - (stone_before - 5)) < 0.01:
        ok("stone 扣除正确", f"{stone_before} → {stone_after}")
    else:
        fail("ST-1 stone", f"期望 {stone_before - 5}, 实际 {stone_after}")
    return building_id


# ─── ST-2: 资源不足建造失败 ─────────────────────────────────────

async def test_construct_insufficient(builder_id: int):
    print("\n=== ST-2: 资源不足建造失败 ===")
    await set_resource(builder_id, "wood", 1)
    await set_resource(builder_id, "stone", 0)
    r = await CLIENT.post("/api/cities/长安/buildings/construct", json={
        "builder_id": builder_id, "building_type": "farm", "name": "不够资源的农田",
    })
    if r.status_code == 400:
        ok("资源不足正确拒绝 (400)", r.text[:80])
    else:
        fail("ST-2", f"期望 400, 实际 status={r.status_code}, body={r.text[:80]}")


# ─── ST-3: 建造中列表 ──────────────────────────────────────────

async def test_constructing_list(building_id: int):
    print("\n=== ST-3: GET /constructing 建造中列表 ===")
    r = await CLIENT.get("/api/cities/长安/buildings/constructing")
    if r.status_code != 200:
        fail("ST-3 API", f"status={r.status_code}")
        return
    items = r.json()
    found = [b for b in items if b["id"] == building_id]
    if found:
        b = found[0]
        ok("建造中列表包含新建筑", f"name={b['name']}, days={b['construction_days']}")
        if b.get("progress_days", -1) >= 0:
            ok("进度字段存在", f"progress_days={b['progress_days']}")
        else:
            fail("ST-3 进度字段", "缺少 progress_days")
    else:
        fail("ST-3", f"building_id={building_id} 不在 constructing 列表中")


# ─── ST-4: 建造中建筑拒绝分配工人 ──────────────────────────────

async def test_reject_worker_constructing(building_id: int, agent_id: int):
    print("\n=== ST-4: 建造中建筑拒绝分配工人 ===")
    # 先确保 agent 没有在其他建筑工作
    r = await CLIENT.get("/api/cities/长安/buildings")
    for b in r.json():
        for w in b.get("workers", []):
            if w["agent_id"] == agent_id:
                await CLIENT.delete(f"/api/cities/长安/buildings/{b['id']}/workers/{agent_id}")
    r = await CLIENT.post(f"/api/cities/长安/buildings/{building_id}/workers",
                          json={"agent_id": agent_id})
    body = r.json()
    if not body.get("ok"):
        ok("建造中建筑拒绝分配工人", f"reason={body.get('reason')}")
    else:
        fail("ST-4", "建造中建筑不应允许分配工人")


# ─── ST-5: production-tick 不会提前完成 ─────────────────────────

async def test_no_premature_completion(building_id: int):
    print("\n=== ST-5: production-tick 不会提前完成建造 ===")
    await CLIENT.post("/api/cities/长安/production-tick")
    await CLIENT.post("/api/cities/长安/production-tick")
    r = await CLIENT.get("/api/cities/长安/buildings/constructing")
    items = r.json()
    found = [b for b in items if b["id"] == building_id]
    if found:
        ok("建筑仍在建造中", f"工期未到，不会提前完成")
    else:
        # 检查是否变成 active 了
        r2 = await CLIENT.get(f"/api/cities/长安/buildings/{building_id}")
        if r2.status_code == 200 and r2.json().get("status") == "active":
            fail("ST-5", "建筑提前完成了（工期3天，刚建造就完成）")
        else:
            fail("ST-5", "建筑既不在 constructing 也不在 active")


# ─── ST-6: WebSocket 收到 building_construction_started 广播 ───

async def test_ws_construct_broadcast(builder_id: int):
    print("\n=== ST-6: WebSocket 收到 building_construction_started ===")
    await set_resource(builder_id, "wood", 20)
    await set_resource(builder_id, "stone", 10)
    ws_url = f"{WS_BASE}/api/ws/0"
    events_received: list[str] = []
    try:
        async with websockets.connect(ws_url, ping_interval=None) as ws:
            await asyncio.wait_for(ws.recv(), timeout=5)
            await asyncio.sleep(0.3)

            async def collect():
                try:
                    while True:
                        msg = await asyncio.wait_for(ws.recv(), timeout=8)
                        data = json.loads(msg)
                        if data.get("type") == "ping":
                            await ws.send(json.dumps({"type": "pong"}))
                            continue
                        if data.get("type") == "system_event":
                            evt = data["data"].get("event", "")
                            if "building_" in evt:
                                events_received.append(evt)
                except asyncio.TimeoutError:
                    pass

            collector = asyncio.create_task(collect())
            await asyncio.sleep(0.1)
            await CLIENT.post("/api/cities/长安/buildings/construct", json={
                "builder_id": builder_id,
                "building_type": "farm",
                "name": "WS测试农田",
            })
            await collector

        if "building_construction_started" in events_received:
            ok("收到 building_construction_started 广播")
        else:
            fail("ST-6", f"未收到广播, 收到: {events_received}")
    except Exception as e:
        fail("ST-6 WebSocket", str(e))


# ─── Main ───────────────────────────────────────────────────────

async def _run():
    agents = (await CLIENT.get("/api/agents/")).json()
    bot_agents = [a for a in agents if a["id"] != 0]
    ST_MODEL = "stepfun/step-3.5-flash"
    if not bot_agents:
        print("  Bot Agent 不足，自动创建...")
        for name, persona in [("Alice", "热心肠的面包师"), ("Bob", "勤劳的农夫")]:
            r = await CLIENT.post("/api/agents/", json={
                "name": name, "persona": persona, "model": ST_MODEL,
            })
            if r.status_code == 201:
                print(f"  创建 {name} 成功")
        agents = (await CLIENT.get("/api/agents/")).json()
        bot_agents = [a for a in agents if a["id"] != 0]
    if not bot_agents:
        print("ERROR: 无 Bot Agent")
        return
    builder = bot_agents[0]
    print(f"[OK] builder={builder['name']}(id={builder['id']})")

    bid = await test_construct_success(builder["id"])
    await test_construct_insufficient(builder["id"])
    if bid:
        await test_constructing_list(bid)
        await test_reject_worker_constructing(bid, builder["id"])
        await test_no_premature_completion(bid)
    await test_ws_construct_broadcast(builder["id"])

    print("\n" + "=" * 60)
    print(f"结果: {passed} passed, {failed} failed")
    if errors:
        print("失败项:")
        for e in errors:
            print(f"  - {e}")
    print("=" * 60)
    await CLIENT.aclose()


async def main():
    print("=" * 60)
    print("M6.1 — 建造系统端到端验证")
    print("=" * 60)
    async with __import__("server_utils").managed_server():
        await _run()


if __name__ == "__main__":
    asyncio.run(main())

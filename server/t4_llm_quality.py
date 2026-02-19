"""
T4 验证：LLM 输出质量 Go/No-Go
跑 10 轮 LLM 决策，统计策略 JSON 解析成功率
成功率 >= 70% → Go
"""
import asyncio
import httpx

BASE_URL = "http://localhost:8001"
CLIENT = httpx.AsyncClient(timeout=60.0, base_url=BASE_URL)

async def _run():
    print("=" * 60)
    print("T4 验证：LLM 输出质量 Go/No-Go")
    print("=" * 60)

    success = 0
    fail = 0
    rounds = 10

    for i in range(1, rounds + 1):
        print(f"\n[Round {i}/{rounds}]")
        r = await CLIENT.post("/api/dev/probe-llm-decide")
        data = r.json()

        if data.get("ok"):
            print(f"  ✓ 解析成功: {data['actions_count']} actions, {data['strategies_count']} strategies")
            success += 1
        else:
            print(f"  ✗ 解析失败: {data.get('reason', 'unknown')}")
            fail += 1

        # 避免频繁调用
        await asyncio.sleep(1)

    print("\n" + "=" * 60)
    print(f"结果: {success}/{rounds} 成功 ({success/rounds*100:.1f}%)")
    print("=" * 60)

    if success / rounds >= 0.7:
        print("✓ Go/No-Go: GO（成功率 >= 70%）")
    else:
        print("✗ Go/No-Go: NO-GO（成功率 < 70%，需调整 prompt 或 schema）")

    await CLIENT.aclose()

async def main():
    async with __import__("server_utils").managed_server():
        await _run()

if __name__ == "__main__":
    asyncio.run(main())


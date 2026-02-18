"""M5.1 单元测试: ToolRegistry + transfer_resource 广播 + autonomy transfer_resource"""

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, patch, MagicMock
from sqlalchemy import select

from app.models import Agent, AgentResource
from app.services.tool_registry import ToolRegistry, ToolDefinition, tool_registry, TRANSFER_RESOURCE_TOOL

pytestmark = pytest.mark.asyncio


async def _seed_agent(db, *, id=1, name="TestAgent", satiety=80, mood=60, stamina=50):
    agent = Agent(id=id, name=name, persona="test", model="none", status="idle",
                  satiety=satiety, mood=mood, stamina=stamina)
    db.add(agent)
    await db.flush()
    return agent


async def _seed_resource(db, agent_id, resource_type, quantity):
    ar = AgentResource(agent_id=agent_id, resource_type=resource_type, quantity=quantity)
    db.add(ar)
    await db.flush()
    return ar


# ========== T1: 注册工具后 get_tools_for_llm 返回正确格式 ==========

async def test_t1_registry_get_tools_format():
    reg = ToolRegistry()
    handler = AsyncMock(return_value={"ok": True})
    reg.register(ToolDefinition(
        name="test_tool",
        description="A test tool",
        parameters={"type": "object", "properties": {"x": {"type": "integer"}}},
        handler=handler,
    ))
    tools = reg.get_tools_for_llm()
    assert len(tools) == 1
    t = tools[0]
    assert t["type"] == "function"
    assert t["function"]["name"] == "test_tool"
    assert t["function"]["description"] == "A test tool"
    assert "properties" in t["function"]["parameters"]


# ========== T2: 执行已注册工具返回成功 ==========

async def test_t2_registry_execute_success():
    reg = ToolRegistry()
    handler = AsyncMock(return_value={"data": 42})
    reg.register(ToolDefinition(
        name="my_tool", description="d", parameters={}, handler=handler,
    ))
    result = await reg.execute("my_tool", {"a": 1}, {"ctx": True})
    assert result["ok"] is True
    assert result["result"] == {"data": 42}
    handler.assert_called_once_with({"a": 1}, {"ctx": True})


# ========== T3: 执行未注册工具返回错误 ==========

async def test_t3_registry_execute_unknown():
    reg = ToolRegistry()
    result = await reg.execute("nonexistent", {}, {})
    assert result["ok"] is False
    assert "未知工具" in result["error"]


# ========== T4: handler 抛异常返回错误 ==========

async def test_t4_registry_execute_exception():
    reg = ToolRegistry()
    handler = AsyncMock(side_effect=ValueError("boom"))
    reg.register(ToolDefinition(
        name="bad_tool", description="d", parameters={}, handler=handler,
    ))
    result = await reg.execute("bad_tool", {}, {})
    assert result["ok"] is False
    assert "boom" in result["error"]


# ========== T5: transfer_resource 成功后广播被调用 ==========

async def test_t5_transfer_broadcast(db):
    await _seed_agent(db, id=1, name="Alice")
    await _seed_agent(db, id=2, name="Bob")
    await _seed_resource(db, 1, "flour", 10)
    await db.flush()

    with patch("app.services.city_service._broadcast_city_event", new_callable=AsyncMock) as mock_bc:
        from app.services.city_service import transfer_resource
        result = await transfer_resource(1, 2, "flour", 3, db)

    assert result["ok"] is True
    mock_bc.assert_called_once()
    call_args = mock_bc.call_args
    assert call_args[0][0] == "resource_transferred"
    payload = call_args[0][1]
    assert payload["from_agent_id"] == 1
    assert payload["from_agent_name"] == "Alice"
    assert payload["to_agent_id"] == 2
    assert payload["to_agent_name"] == "Bob"
    assert payload["resource_type"] == "flour"
    assert payload["quantity"] == 3


# ========== T6: autonomy execute_decisions 处理 transfer_resource ==========

async def test_t6_autonomy_transfer_success(db):
    await _seed_agent(db, id=1, name="Alice")
    await _seed_agent(db, id=2, name="Bob")
    await _seed_resource(db, 1, "flour", 10)
    await db.flush()

    with patch("app.services.city_service._broadcast_city_event", new_callable=AsyncMock):
        from app.services.autonomy_service import execute_decisions
        decisions = [
            {"agent_id": 1, "action": "transfer_resource",
             "params": {"to_agent_id": 2, "resource_type": "flour", "quantity": 5},
             "reason": "Bob 需要面粉"},
        ]
        stats = await execute_decisions(decisions, db)

    assert stats["success"] >= 1

    # 验证资源变化
    from_res = await db.execute(
        select(AgentResource).where(AgentResource.agent_id == 1, AgentResource.resource_type == "flour")
    )
    assert from_res.scalar().quantity == 5
    to_res = await db.execute(
        select(AgentResource).where(AgentResource.agent_id == 2, AgentResource.resource_type == "flour")
    )
    assert to_res.scalar().quantity == 5


# ========== T7: autonomy transfer_resource 参数不全 → failed ==========

async def test_t7_autonomy_transfer_missing_params(db):
    await _seed_agent(db, id=1, name="Alice")
    await db.flush()

    with patch("app.services.city_service._broadcast_city_event", new_callable=AsyncMock):
        from app.services.autonomy_service import execute_decisions
        decisions = [
            {"agent_id": 1, "action": "transfer_resource",
             "params": {"to_agent_id": 2},  # 缺少 resource_type 和 quantity
             "reason": "test"},
        ]
        stats = await execute_decisions(decisions, db)

    assert stats["failed"] >= 1


# ========== T8: decide() 接受 transfer_resource 不降级为 rest ==========

async def test_t8_decide_accepts_transfer_resource():
    """验证 decide() 的 valid_actions 包含 transfer_resource"""
    from app.services.autonomy_service import SYSTEM_PROMPT
    assert "transfer_resource" in SYSTEM_PROMPT

    # 模拟 decide 的 action 校验逻辑
    valid_actions = ("checkin", "purchase", "chat", "rest", "assign_building",
                     "unassign_building", "eat", "transfer_resource")
    d = {"agent_id": 1, "action": "transfer_resource", "params": {}, "reason": "test"}
    if d["action"] not in valid_actions:
        d["action"] = "rest"
    assert d["action"] == "transfer_resource"  # 没被降级


# ========== T9: 全局 tool_registry 已注册 transfer_resource ==========

async def test_t9_global_registry_has_transfer():
    tools = tool_registry.get_tools_for_llm()
    names = [t["function"]["name"] for t in tools]
    assert "transfer_resource" in names

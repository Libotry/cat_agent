"""F35: Agent 状态可视化 — 单元测试"""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from datetime import datetime

from app.models.tables import AgentStatus, Agent
from app.services.status_helper import set_agent_status


# ---------------------------------------------------------------------------
# AgentStatus 枚举
# ---------------------------------------------------------------------------

def test_status_enum_values():
    """AgentStatus 包含 IDLE/THINKING/EXECUTING/PLANNING 四个值"""
    assert AgentStatus.IDLE.value == "idle"
    assert AgentStatus.THINKING.value == "thinking"
    assert AgentStatus.EXECUTING.value == "executing"
    assert AgentStatus.PLANNING.value == "planning"


def test_old_status_removed():
    """CHATTING/WORKING/RESTING 不在 AgentStatus 枚举中"""
    values = [s.value for s in AgentStatus]
    assert "chatting" not in values
    assert "working" not in values
    assert "resting" not in values


def test_status_enum_count():
    """枚举只有 4 个值"""
    assert len(AgentStatus) == 4


# ---------------------------------------------------------------------------
# set_agent_status
# ---------------------------------------------------------------------------

def _make_agent(agent_id=1, name="Alice"):
    agent = MagicMock(spec=Agent)
    agent.id = agent_id
    agent.name = name
    agent.status = AgentStatus.IDLE.value
    agent.activity = ""
    return agent


@pytest.mark.asyncio
async def test_set_agent_status_updates_fields():
    """调用 set_agent_status 后 agent.status 和 agent.activity 正确更新"""
    agent = _make_agent()
    db = AsyncMock()

    with patch("app.api.chat.broadcast", new_callable=AsyncMock):
        await set_agent_status(agent, AgentStatus.THINKING, "正在思考…", db)

    assert agent.status == "thinking"
    assert agent.activity == "正在思考…"
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_set_agent_status_broadcasts():
    """调用后广播消息格式正确"""
    agent = _make_agent()
    db = AsyncMock()

    with patch("app.api.chat.broadcast", new_callable=AsyncMock) as mock_bc:
        await set_agent_status(agent, AgentStatus.EXECUTING, "执行 web_search…", db)

    mock_bc.assert_awaited_once()
    msg = mock_bc.call_args[0][0]
    assert msg["type"] == "system_event"
    data = msg["data"]
    assert data["event"] == "agent_status_change"
    assert data["agent_id"] == 1
    assert data["agent_name"] == "Alice"
    assert data["status"] == "executing"
    assert data["activity"] == "执行 web_search…"
    assert "timestamp" in data


@pytest.mark.asyncio
async def test_broadcast_contains_all_fields():
    """广播消息包含 agent_id, agent_name, status, activity, timestamp"""
    agent = _make_agent(agent_id=3, name="Charlie")
    db = AsyncMock()

    with patch("app.api.chat.broadcast", new_callable=AsyncMock) as mock_bc:
        await set_agent_status(agent, AgentStatus.PLANNING, "规划中…", db)

    data = mock_bc.call_args[0][0]["data"]
    required_keys = {"event", "agent_id", "agent_name", "status", "activity", "timestamp"}
    assert required_keys.issubset(data.keys())


@pytest.mark.asyncio
async def test_status_flow_thinking_to_idle():
    """THINKING → IDLE 流转正确"""
    agent = _make_agent()
    db = AsyncMock()

    with patch("app.api.chat.broadcast", new_callable=AsyncMock):
        await set_agent_status(agent, AgentStatus.THINKING, "思考中…", db)
        assert agent.status == "thinking"
        assert agent.activity == "思考中…"

        await set_agent_status(agent, AgentStatus.IDLE, "", db)
        assert agent.status == "idle"
        assert agent.activity == ""


@pytest.mark.asyncio
async def test_status_flow_thinking_executing_idle():
    """THINKING → EXECUTING → IDLE 流转正确"""
    agent = _make_agent()
    db = AsyncMock()

    with patch("app.api.chat.broadcast", new_callable=AsyncMock) as mock_bc:
        await set_agent_status(agent, AgentStatus.THINKING, "思考中…", db)
        await set_agent_status(agent, AgentStatus.EXECUTING, "执行 tool…", db)
        await set_agent_status(agent, AgentStatus.IDLE, "", db)

    assert mock_bc.await_count == 3
    statuses = [call[0][0]["data"]["status"] for call in mock_bc.call_args_list]
    assert statuses == ["thinking", "executing", "idle"]

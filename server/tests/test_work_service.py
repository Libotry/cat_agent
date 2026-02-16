"""Tests for WorkService (TEST-M3: U1-U9, U16-U17).

NOTE: work_service uses func.date('now') (UTC) for duplicate / capacity checks,
and CheckIn.checked_at server_default is func.now() (UTC in SQLite).
Tests that manually insert CheckIn rows use datetime.utcnow() to stay consistent.
"""

import pytest
import pytest_asyncio
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

from app.models import Agent, Job, CheckIn
from app.services.work_service import work_service

pytestmark = pytest.mark.asyncio


def _utc_now() -> datetime:
    """Return UTC datetime (consistent with SQLite CURRENT_TIMESTAMP / date('now')).
    Returns naive datetime since SQLite stores naive timestamps."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ── fixtures ──────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def agent(db):
    """Agent(id=1, credits=100)"""
    a = Agent(id=1, name="TestBot", persona="test", credits=100)
    db.add(a)
    await db.commit()
    await db.refresh(a)
    return a


@pytest_asyncio.fixture
async def job(db):
    """Job(id=1, title='矿工', daily_reward=8, max_workers=5)"""
    j = Job(id=1, title="矿工", description="挖矿", daily_reward=8, max_workers=5)
    db.add(j)
    await db.commit()
    await db.refresh(j)
    return j


@pytest_asyncio.fixture
async def unlimited_job(db):
    """Job(id=2, max_workers=0, daily_reward=10) — unlimited capacity"""
    j = Job(id=2, title="清洁工", description="打扫", daily_reward=10, max_workers=0)
    db.add(j)
    await db.commit()
    await db.refresh(j)
    return j


# ── U1: 正常打卡发薪 ─────────────────────────────────────────────

async def test_checkin_success(db, agent, job):
    result = await work_service.check_in(agent_id=1, job_id=1, db=db)

    assert result["ok"] is True
    assert result["reason"] == "success"
    assert result["reward"] == 8
    assert isinstance(result["checkin_id"], int)

    await db.refresh(agent)
    assert agent.credits == 108

    checkin = await db.get(CheckIn, result["checkin_id"])
    assert checkin is not None
    assert checkin.agent_id == 1
    assert checkin.job_id == 1
    assert checkin.reward == 8


# ── U2: 同日重复打卡被拒 ─────────────────────────────────────────

async def test_checkin_duplicate_same_day(db, agent, job):
    # 先手动插入一条今日打卡记录（用 local time 保证 date.today() 匹配）
    db.add(CheckIn(agent_id=1, job_id=1, reward=8, checked_at=_utc_now()))
    agent.credits += 8  # 模拟发薪
    await db.commit()

    # 创建第二个岗位
    job2 = Job(id=2, title="厨师", daily_reward=5, max_workers=5)
    db.add(job2)
    await db.commit()

    # 同日再打卡另一个岗位
    result = await work_service.check_in(agent_id=1, job_id=2, db=db)

    assert result["ok"] is False
    assert result["reason"] == "already_checked_in"
    assert result["reward"] == 0

    await db.refresh(agent)
    assert agent.credits == 108  # 只加了第一次的 8


# ── U3: 岗位满员被拒 ─────────────────────────────────────────────

async def test_checkin_job_full(db, job):
    # 创建 max_workers=2 的岗位
    small_job = Job(id=10, title="保安", daily_reward=6, max_workers=2)
    db.add(small_job)

    # 创建 3 个 Agent
    agents = []
    for i in range(1, 4):
        a = Agent(id=i, name=f"Bot{i}", persona="test", credits=100)
        db.add(a)
        agents.append(a)
    await db.commit()

    # 手动插入 2 条今日打卡记录（用 local time）
    now = _utc_now()
    for i in range(1, 3):
        db.add(CheckIn(agent_id=i, job_id=10, reward=6, checked_at=now))
    await db.commit()

    # 第 3 个被拒
    result = await work_service.check_in(agent_id=3, job_id=10, db=db)
    assert result["ok"] is False
    assert result["reason"] == "job_full"
    assert result["reward"] == 0

    await db.refresh(agents[2])
    assert agents[2].credits == 100


# ── U4: 不同日再次打卡 ───────────────────────────────────────────

async def test_checkin_different_day(db, agent, job):
    # 昨天打过卡（手动插入记录）
    yesterday = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=1)
    old_checkin = CheckIn(agent_id=1, job_id=1, reward=8, checked_at=yesterday)
    db.add(old_checkin)
    await db.commit()

    # 今天再打卡应该成功
    result = await work_service.check_in(agent_id=1, job_id=1, db=db)

    assert result["ok"] is True
    assert result["reason"] == "success"
    assert result["reward"] == 8

    await db.refresh(agent)
    assert agent.credits == 108


# ── U5: max_workers=0 岗位打卡成功 ───────────────────────────────

async def test_checkin_unlimited_job(db, agent, unlimited_job):
    result = await work_service.check_in(agent_id=1, job_id=2, db=db)

    assert result["ok"] is True
    assert result["reason"] == "success"
    assert result["reward"] == 10


# ── U6: max_workers=0 多人打卡全部成功 ───────────────────────────

async def test_checkin_unlimited_job_multiple(db, unlimited_job):
    # 创建 10 个 Agent
    for i in range(1, 11):
        db.add(Agent(id=i, name=f"Bot{i}", persona="test", credits=100))
    await db.commit()

    # 依次打卡
    for i in range(1, 11):
        result = await work_service.check_in(agent_id=i, job_id=2, db=db)
        assert result["ok"] is True, f"Agent {i} should succeed, got {result}"
        await db.commit()

    # 验证所有 Agent 的 credits 都增加了
    for i in range(1, 11):
        a = await db.get(Agent, i)
        assert a.credits == 110, f"Agent {i} credits should be 110"


# ── U7: 岗位列表含 today_workers ─────────────────────────────────

async def test_get_jobs_with_today_workers(db, job):
    # job fixture: id=1, max_workers=5
    # 创建第二个岗位
    job2 = Job(id=2, title="厨师", daily_reward=5, max_workers=3)
    db.add(job2)

    # 创建 3 个 Agent
    for i in range(1, 4):
        db.add(Agent(id=i, name=f"Bot{i}", persona="test", credits=100))
    await db.commit()

    # 手动插入 3 条今日打卡记录到 job1（用 local time）
    now = _utc_now()
    for i in range(1, 4):
        db.add(CheckIn(agent_id=i, job_id=1, reward=8, checked_at=now))
    await db.commit()

    jobs = await work_service.get_jobs(db)

    job1_data = next(j for j in jobs if j["id"] == 1)
    job2_data = next(j for j in jobs if j["id"] == 2)

    assert job1_data["today_workers"] == 3
    assert job2_data["today_workers"] == 0


# ── U8: agent_not_found 打卡被拒 ─────────────────────────────────

async def test_checkin_agent_not_found(db, job):
    result = await work_service.check_in(agent_id=999, job_id=1, db=db)

    assert result["ok"] is False
    assert result["reason"] == "agent_not_found"
    assert result["reward"] == 0


# ── U9: job_not_found 打卡被拒 ───────────────────────────────────

async def test_checkin_job_not_found(db, agent):
    result = await work_service.check_in(agent_id=1, job_id=999, db=db)

    assert result["ok"] is False
    assert result["reason"] == "job_not_found"
    assert result["reward"] == 0


# ── U16: get_work_history 默认 7 天 ───────────────────────────────

async def test_work_history_default_days(db, agent, job):
    now = datetime.now()

    # 3 条在最近 7 天内
    for d in [1, 3, 5]:
        db.add(CheckIn(
            agent_id=1, job_id=1, reward=8,
            checked_at=now - timedelta(days=d),
        ))
    # 2 条在 8~10 天前
    for d in [8, 10]:
        db.add(CheckIn(
            agent_id=1, job_id=1, reward=8,
            checked_at=now - timedelta(days=d),
        ))
    await db.commit()

    history = await work_service.get_work_history(agent_id=1, db=db)

    assert len(history) == 3
    # 按 checked_at 降序
    dates = [h["checked_at"] for h in history]
    assert dates == sorted(dates, reverse=True)


# ── U17: get_work_history 自定义 days ────────────────────────────

async def test_work_history_custom_days(db, agent, job):
    now = datetime.now()

    # 3 条在最近 3 天内
    for d in [0, 1, 2]:
        db.add(CheckIn(
            agent_id=1, job_id=1, reward=8,
            checked_at=now - timedelta(days=d),
        ))
    # 2 条在 4~10 天前
    for d in [4, 10]:
        db.add(CheckIn(
            agent_id=1, job_id=1, reward=8,
            checked_at=now - timedelta(days=d),
        ))
    await db.commit()

    history = await work_service.get_work_history(agent_id=1, db=db, days=3)

    assert len(history) == 3
    # 按 checked_at 降序
    dates = [h["checked_at"] for h in history]
    assert dates == sorted(dates, reverse=True)

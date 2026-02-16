from datetime import datetime
from sqlalchemy import select, func as sa_func
from sqlalchemy.ext.asyncio import AsyncSession
from ..models import Agent, Job, CheckIn

class WorkService:

    async def get_jobs(self, db: AsyncSession) -> list[dict]:
        """岗位列表，含当日在岗人数"""
        # 用 date('now') 保持与 CURRENT_TIMESTAMP (UTC) 一致
        today_utc = sa_func.date("now")
        # 子查询：当日每个岗位的打卡人数
        checkin_counts = (
            select(
                CheckIn.job_id,
                sa_func.count(CheckIn.id).label("today_workers")
            )
            .where(sa_func.date(CheckIn.checked_at) == today_utc)
            .group_by(CheckIn.job_id)
            .subquery()
        )
        result = await db.execute(
            select(Job, checkin_counts.c.today_workers)
            .outerjoin(checkin_counts, Job.id == checkin_counts.c.job_id)
        )
        jobs = []
        for job, today_workers in result.all():
            jobs.append({
                "id": job.id,
                "title": job.title,
                "description": job.description,
                "daily_reward": job.daily_reward,
                "max_workers": job.max_workers,
                "today_workers": today_workers or 0,
            })
        return jobs

    async def check_in(
        self, agent_id: int, job_id: int, db: AsyncSession
    ) -> dict:
        """
        打卡逻辑。
        校验：Agent 存在 → 岗位存在 → 今日未打卡 → 岗位未满员
        成功：写 CheckIn + Agent.credits += daily_reward
        返回：{"ok": True/False, "reason": str, "reward": int}
        """
        agent = await db.get(Agent, agent_id)
        if not agent:
            return {"ok": False, "reason": "agent_not_found", "reward": 0}

        job = await db.get(Job, job_id)
        if not job:
            return {"ok": False, "reason": "job_not_found", "reward": 0}
        # 今日是否已打卡（任意岗位）— 用 date('now') 与 UTC 时间戳对齐
        today_utc = sa_func.date("now")
        existing = await db.execute(
            select(CheckIn)
            .where(
                CheckIn.agent_id == agent_id,
                sa_func.date(CheckIn.checked_at) == today_utc,
            )
            .limit(1)
        )
        if existing.scalar_one_or_none():
            return {"ok": False, "reason": "already_checked_in", "reward": 0}

        # 岗位容量检查（max_workers=0 表示无限制）
        if job.max_workers > 0:
            today_count = await db.execute(
                select(sa_func.count(CheckIn.id))
                .where(
                    CheckIn.job_id == job_id,
                    sa_func.date(CheckIn.checked_at) == today_utc,
                )
            )
            if today_count.scalar() >= job.max_workers:
                return {"ok": False, "reason": "job_full", "reward": 0}

        # 写入打卡记录 + 发薪
        checkin = CheckIn(
            agent_id=agent_id,
            job_id=job_id,
            reward=job.daily_reward,
        )
        db.add(checkin)
        agent.credits += job.daily_reward
        await db.flush()
        await db.refresh(checkin)

        return {
            "ok": True,
            "reason": "success",
            "reward": job.daily_reward,
            "checkin_id": checkin.id,
        }

    async def get_today_checkin(
        self, agent_id: int, db: AsyncSession
    ) -> dict | None:
        """查询 Agent 今日打卡记录，无则返回 None"""
        today_utc = sa_func.date("now")
        result = await db.execute(
            select(CheckIn)
            .where(
                CheckIn.agent_id == agent_id,
                sa_func.date(CheckIn.checked_at) == today_utc,
            )
            .limit(1)
        )
        checkin = result.scalar_one_or_none()
        if not checkin:
            return None
        return {
            "checkin_id": checkin.id,
            "job_id": checkin.job_id,
            "reward": checkin.reward,
            "checked_at": str(checkin.checked_at),
        }

    async def get_work_history(
        self, agent_id: int, db: AsyncSession, days: int = 7
    ) -> list[dict]:
        """最近 N 天打卡记录"""
        from datetime import timedelta
        since = datetime.now() - timedelta(days=days)
        result = await db.execute(
            select(CheckIn)
            .where(CheckIn.agent_id == agent_id, CheckIn.checked_at >= since)
            .order_by(CheckIn.checked_at.desc())
        )
        return [
            {
                "checkin_id": c.id,
                "job_id": c.job_id,
                "reward": c.reward,
                "checked_at": str(c.checked_at),
            }
            for c in result.scalars().all()
        ]

work_service = WorkService()

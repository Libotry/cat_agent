"""
工作系统 REST API

GET  /work/jobs                        — 岗位列表（含当日在岗人数）
POST /work/jobs/{job_id}/checkin       — 打卡
GET  /work/agents/{agent_id}/today     — 今日打卡状态
GET  /work/agents/{agent_id}/history   — 打卡记录
"""
from datetime import datetime
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from ..core import get_db
from ..models import Agent, Job
from ..services.work_service import work_service
from .schemas import JobOut, CheckInRequest, CheckInResult, CheckInOut
from .chat import broadcast

router = APIRouter(prefix="/work", tags=["work"])


@router.get("/jobs", response_model=list[JobOut])
async def list_jobs(db: AsyncSession = Depends(get_db)):
    """岗位列表，含当日在岗人数"""
    return await work_service.get_jobs(db)


@router.post("/jobs/{job_id}/checkin", response_model=CheckInResult)
async def checkin(job_id: int, req: CheckInRequest, db: AsyncSession = Depends(get_db)):
    """打卡：先 commit 再 broadcast"""
    result = await work_service.check_in(req.agent_id, job_id, db)
    if result["ok"]:
        await db.commit()
        # 查询 agent 和 job 信息用于广播
        agent = await db.get(Agent, req.agent_id)
        job = await db.get(Job, job_id)
        await broadcast({
            "type": "system_event",
            "data": {
                "event": "checkin",
                "agent_id": req.agent_id,
                "agent_name": agent.name if agent else "unknown",
                "job_title": job.title if job else "unknown",
                "reward": result["reward"],
                "timestamp": datetime.now().isoformat(sep=" ", timespec="seconds"),
            }
        })
    return result


@router.get("/agents/{agent_id}/today", response_model=CheckInOut | None)
async def today_checkin(agent_id: int, db: AsyncSession = Depends(get_db)):
    """今日打卡状态"""
    return await work_service.get_today_checkin(agent_id, db)


@router.get("/agents/{agent_id}/history", response_model=list[CheckInOut])
async def work_history(agent_id: int, days: int = 7, db: AsyncSession = Depends(get_db)):
    """打卡记录（默认最近 7 天）"""
    return await work_service.get_work_history(agent_id, db, days=days)

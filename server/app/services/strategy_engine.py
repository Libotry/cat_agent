"""
M6 Phase 1 — 策略自动机引擎

两层架构：LLM 每小时输出策略指令 → 自动机按策略匹配事件自动执行
"""
import logging
from enum import Enum
from typing import Optional
from pydantic import BaseModel, field_validator

logger = logging.getLogger(__name__)


# ── T1: 策略数据模型 ──────────────────────────────────────

class StrategyType(str, Enum):
    KEEP_WORKING = "keep_working"
    OPPORTUNISTIC_BUY = "opportunistic_buy"


class Strategy(BaseModel):
    """极简扁平策略，LLM 输出一条 = 一个 Strategy。"""
    agent_id: int
    strategy: StrategyType
    # keep_working 字段
    building_id: Optional[int] = None
    stop_when_resource: Optional[str] = None
    stop_when_amount: Optional[float] = None
    # opportunistic_buy 字段
    resource: Optional[str] = None
    price_below: Optional[float] = None

    @field_validator("building_id", mode="before")
    @classmethod
    def coerce_building_id(cls, v):
        if v is None:
            return v
        return int(v)

    @field_validator("price_below", "stop_when_amount", mode="before")
    @classmethod
    def coerce_float(cls, v):
        if v is None:
            return v
        return float(v)


def parse_strategies(raw_list: list[dict]) -> list[Strategy]:
    """从 LLM 输出的 JSON 列表解析策略，跳过不合法的条目。"""
    valid = []
    for item in raw_list:
        try:
            s = Strategy(**item)
            valid.append(s)
        except Exception as e:
            logger.warning("Strategy parse failed: %s, item=%s", e, item)
    return valid


# ── 策略存储（内存，重启丢失可接受）──────────────────────

# agent_id -> list[Strategy]
_strategy_store: dict[int, list[Strategy]] = {}


def update_strategies(agent_id: int, strategies: list[Strategy]):
    """全量覆盖某 Agent 的策略（每次 hourly tick 后调用）。"""
    _strategy_store[agent_id] = [s for s in strategies if s.agent_id == agent_id]


def get_strategies(agent_id: int) -> list[Strategy]:
    """获取某 Agent 当前活跃策略。"""
    return list(_strategy_store.get(agent_id, []))


def get_all_strategies() -> dict[int, list[Strategy]]:
    """获取所有 Agent 的策略（观测用）。"""
    return {aid: list(ss) for aid, ss in _strategy_store.items()}


def clear_strategies(agent_id: int | None = None):
    """清空策略（agent_id=None 清全部，否则只清指定 agent）。"""
    if agent_id is None:
        _strategy_store.clear()
    else:
        _strategy_store.pop(agent_id, None)

"""M6.2-P2: SOUL.md 深度人格 — 单元测试

覆盖场景：
1. SoulPersonality schema 校验（截断、extra ignore、空值）
2. _validate_personality_json 清洗逻辑
3. _build_soul_block prompt 格式化
4. generate_reply 走 SOUL 模板 vs 普通模板分支
5. get_or_create 缓存刷新可变字段
"""
from unittest.mock import AsyncMock, patch, MagicMock

import pytest

from app.api.schemas import SoulPersonality


# ============================================================
# 1. SoulPersonality schema
# ============================================================

class TestSoulPersonalitySchema:
    """SoulPersonality Pydantic 模型校验"""

    def test_full_valid(self):
        pj = SoulPersonality(
            values=["正义", "勇气"],
            speaking_style="冷静",
            knowledge_domains=["历史"],
            emotional_tendency="乐观",
            catchphrases=["嗯哼"],
            relationships={"Alice": "友好"},
            taboos=["说谎"],
        )
        assert pj.values == ["正义", "勇气"]
        assert pj.speaking_style == "冷静"

    def test_all_none(self):
        pj = SoulPersonality()
        assert pj.values is None
        assert pj.catchphrases is None
        assert pj.taboos is None

    def test_values_truncate_to_5(self):
        pj = SoulPersonality(values=["a", "b", "c", "d", "e", "f", "g"])
        assert len(pj.values) == 5

    def test_catchphrases_truncate_to_3(self):
        pj = SoulPersonality(catchphrases=["a", "b", "c", "d", "e"])
        assert len(pj.catchphrases) == 3

    def test_taboos_truncate_to_3(self):
        pj = SoulPersonality(taboos=["x", "y", "z", "w"])
        assert len(pj.taboos) == 3

    def test_extra_fields_ignored(self):
        """extra='ignore' — 未知字段不报错"""
        pj = SoulPersonality(values=["ok"], unknown_field="should be ignored")
        assert pj.values == ["ok"]
        assert not hasattr(pj, "unknown_field")

    def test_empty_lists_kept(self):
        """空列表不被截断（只截断超限）"""
        pj = SoulPersonality(values=[], catchphrases=[], taboos=[])
        assert pj.values == []
        assert pj.catchphrases == []


# ============================================================
# 2. _validate_personality_json
# ============================================================

class TestValidatePersonalityJson:
    """agents.py 中的 _validate_personality_json 清洗逻辑"""

    def _call(self, raw):
        from app.api.agents import _validate_personality_json
        return _validate_personality_json(raw)

    def test_none_returns_none(self):
        assert self._call(None) is None

    def test_empty_dict_returns_none(self):
        assert self._call({}) is None

    def test_valid_dict_cleaned(self):
        result = self._call({"values": ["正义"], "speaking_style": "冷静"})
        assert result == {"values": ["正义"], "speaking_style": "冷静"}

    def test_extra_fields_stripped(self):
        result = self._call({"values": ["ok"], "bogus": 123})
        assert "bogus" not in result
        assert result["values"] == ["ok"]

    def test_all_none_fields_returns_none(self):
        """所有字段都是 None → exclude_none 后为空 dict → 返回 None"""
        result = self._call({"values": None, "speaking_style": None})
        assert result is None

    def test_truncation_applied(self):
        result = self._call({"values": ["a", "b", "c", "d", "e", "f"]})
        assert len(result["values"]) == 5

    def test_invalid_type_returns_none(self):
        """完全无效的输入 → 校验异常 → 返回 None"""
        result = self._call({"values": "not a list"})
        assert result is None


# ============================================================
# 3. _build_soul_block
# ============================================================

class TestBuildSoulBlock:
    """agent_runner.py 中的 _build_soul_block prompt 格式化"""

    def _call(self, pj):
        from app.services.agent_runner import _build_soul_block
        return _build_soul_block(pj)

    def test_full_fields(self):
        pj = {
            "values": ["正义", "勇气"],
            "speaking_style": "冷静理性",
            "knowledge_domains": ["历史", "哲学"],
            "emotional_tendency": "乐观",
            "catchphrases": ["嗯哼", "有意思"],
            "relationships": {"Alice": "友好", "Bob": "警惕"},
            "taboos": ["说谎"],
        }
        result = self._call(pj)
        assert "核心价值观：正义、勇气" in result
        assert "说话风格：冷静理性" in result
        assert "擅长领域：历史、哲学" in result
        assert "情感倾向：乐观" in result
        assert '"嗯哼"' in result
        assert "对 Alice：友好" in result
        assert "对 Bob：警惕" in result
        assert "行为禁区：说谎" in result

    def test_partial_fields(self):
        pj = {"values": ["善良"], "taboos": ["暴力"]}
        result = self._call(pj)
        assert "核心价值观：善良" in result
        assert "行为禁区：暴力" in result
        assert "说话风格" not in result
        assert "口头禅" not in result

    def test_empty_dict(self):
        result = self._call({})
        assert result == ""

    def test_relationships_format(self):
        pj = {"relationships": {"小明": "崇拜", "小红": "竞争"}}
        result = self._call(pj)
        assert "  - 对 小明：崇拜" in result
        assert "  - 对 小红：竞争" in result


# ============================================================
# 4. generate_reply — SOUL 模板 vs 普通模板
# ============================================================

class TestGenerateReplySoulBranch:
    """AgentRunner 根据 personality_json 选择不同 system prompt"""

    def _make_runner(self, personality_json=None):
        from app.services.agent_runner import AgentRunner
        return AgentRunner(
            agent_id=1, name="TestBot", persona="测试人格",
            model="gpt-4o-mini", personality_json=personality_json,
        )

    def test_with_soul_runner_has_personality(self):
        pj = {"values": ["正义"], "speaking_style": "冷静"}
        runner = self._make_runner(personality_json=pj)
        assert runner.personality_json == pj

    def test_without_soul_runner_no_personality(self):
        runner = self._make_runner(personality_json=None)
        assert runner.personality_json is None

    def test_soul_template_contains_deep_persona_section(self):
        """SOUL_PROMPT_TEMPLATE 包含深度人格占位符"""
        from app.services.agent_runner import SOUL_PROMPT_TEMPLATE
        assert "{soul_block}" in SOUL_PROMPT_TEMPLATE
        assert "{name}" in SOUL_PROMPT_TEMPLATE
        assert "{persona}" in SOUL_PROMPT_TEMPLATE

    def test_normal_template_no_soul_block(self):
        """SYSTEM_PROMPT_TEMPLATE 不包含 soul_block"""
        from app.services.agent_runner import SYSTEM_PROMPT_TEMPLATE
        assert "{soul_block}" not in SYSTEM_PROMPT_TEMPLATE

    def test_soul_template_format_produces_valid_prompt(self):
        """SOUL 模板 + _build_soul_block 组合输出完整 prompt"""
        from app.services.agent_runner import SOUL_PROMPT_TEMPLATE, _build_soul_block
        pj = {"values": ["正义"], "catchphrases": ["嗯哼"]}
        soul_block = _build_soul_block(pj)
        prompt = SOUL_PROMPT_TEMPLATE.format(
            name="TestBot", persona="测试人格", soul_block=soul_block,
        )
        assert "TestBot" in prompt
        assert "测试人格" in prompt
        assert "核心价值观：正义" in prompt
        assert "嗯哼" in prompt
        assert "深度人格" in prompt


# ============================================================
# 5. RunnerPool.get_or_create 缓存刷新
# ============================================================

class TestRunnerPoolCacheRefresh:
    """AgentRunnerManager.get_or_create 每次刷新可变字段"""

    def _make_pool(self):
        from app.services.agent_runner import AgentRunnerManager
        return AgentRunnerManager()

    def test_create_new_runner(self):
        pool = self._make_pool()
        runner = pool.get_or_create(1, "Bot", "persona", "gpt-4o-mini", None)
        assert runner.agent_id == 1
        assert runner.name == "Bot"
        assert runner.personality_json is None

    def test_reuse_existing_runner(self):
        pool = self._make_pool()
        r1 = pool.get_or_create(1, "Bot", "persona", "gpt-4o-mini", None)
        r2 = pool.get_or_create(1, "Bot", "persona", "gpt-4o-mini", None)
        assert r1 is r2

    def test_refresh_persona(self):
        pool = self._make_pool()
        pool.get_or_create(1, "Bot", "old persona", "gpt-4o-mini", None)
        r = pool.get_or_create(1, "Bot", "new persona", "gpt-4o-mini", None)
        assert r.persona == "new persona"

    def test_refresh_model(self):
        pool = self._make_pool()
        pool.get_or_create(1, "Bot", "persona", "gpt-4o-mini", None)
        r = pool.get_or_create(1, "Bot", "persona", "gpt-4o", None)
        assert r.model == "gpt-4o"

    def test_refresh_personality_json(self):
        """CR B1 修复验证：personality_json 更新后缓存刷新"""
        pool = self._make_pool()
        pool.get_or_create(1, "Bot", "persona", "gpt-4o-mini", None)
        pj = {"values": ["正义"]}
        r = pool.get_or_create(1, "Bot", "persona", "gpt-4o-mini", pj)
        assert r.personality_json == pj

    def test_refresh_personality_json_to_none(self):
        """SOUL 删除后缓存清空"""
        pool = self._make_pool()
        pool.get_or_create(1, "Bot", "persona", "gpt-4o-mini", {"values": ["x"]})
        r = pool.get_or_create(1, "Bot", "persona", "gpt-4o-mini", None)
        assert r.personality_json is None

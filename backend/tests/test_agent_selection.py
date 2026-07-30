"""P0-3b 单元测试：Agent 选择算法

对应方案书 2.3-2.4 节 + 7.5 节测试要求。
覆盖：
  - _compute_match_score 三档评分（P1-3 修复的核心：1.0/0.7/0.5/0.0，无死代码）
  - _resolve_domains 领域解析（单领域/跨领域/全链路）
  - _select_candidates 候选遴选（Top-2 / 早停 Top-1 / 兜底补齐）
  - dispatch 三路径（generation/navigation/clarification）
"""

import pytest

from backend.agents.matcher import Matcher, Segment, DispatchResult
from backend.agents.agent_registry import AGENT_CARDS, get_domain_agents
from backend.schemas.student_profile import (
    StudentProfile,
    KnowledgeLevel,
    Background,
    CurrentGoal,
    QuestionType,
    ComplexityEstimate,
    IntentType,
    ConfidenceLevel,
)


# ============================================================
# fixtures
# ============================================================

@pytest.fixture
def matcher():
    return Matcher()


def _make_profile(
    domain_hint=None,
    question_type=QuestionType.CONCEPT,
    complexity=ComplexityEstimate.SINGLE_DOMAIN,
    intent=IntentType.GENERATION,
    domain_confidence=None,
):
    """构造学情画像的辅助函数"""
    if domain_hint is None:
        domain_hint = ["LLM基础"]
    if domain_confidence is None:
        domain_confidence = {h: ConfidenceLevel.HIGH for h in domain_hint}
    return StudentProfile(
        knowledge_level=KnowledgeLevel.INTERMEDIATE,
        background=Background.PYTHON,
        current_goal=CurrentGoal.QUICK_START,
        question_type=question_type,
        domain_hint=domain_hint,
        complexity_estimate=complexity,
        intent_type=intent,
        domain_confidence=domain_confidence,
        session_id="test-session",
    )


# ============================================================
# 1. _compute_match_score 三档评分（P1-3 修复核心）
# ============================================================

class TestComputeMatchScore:
    """方案书 2.4.1 节三档评分：primary_function→1.0 / secondary→0.7 / domain_tags→0.5"""

    def test_primary_domain_returns_1_0(self, matcher):
        """主领域匹配（domain_tags[0]）→ 1.0"""
        # agent_001 LLM基础Agent: domain_tags=["LLM基础", "Prompt工程"]
        card = AGENT_CARDS[0]
        assert matcher._compute_match_score(card, "LLM基础") == 1.0

    def test_secondary_domain_returns_0_7(self, matcher):
        """次领域匹配（domain_tags[1:]）→ 0.7"""
        # agent_001: domain_tags=["LLM基础", "Prompt工程"]，"Prompt工程" 是次领域
        card = AGENT_CARDS[0]
        assert matcher._compute_match_score(card, "Prompt工程") == 0.7

    def test_weak_tag_match_returns_0_5(self, matcher):
        """弱标签匹配（domain 出现在 secondary_functions 文本中）→ 0.5"""
        # agent_001: secondary_functions=["Token机制", "Embedding", "注意力机制"]
        # "Embedding" 不在 domain_tags，但在 secondary_functions → 0.5
        # 但 "Embedding" 不是 domain_hint 值，用一个能命中的 case
        # agent_010 代码调试Agent: domain_tags=["LangChain", "HuggingFace", "Prompt工程"]
        # secondary_functions=["报错分析", "依赖冲突", "环境配置"]
        # "报错分析" 在 secondary_functions → 0.5
        card = AGENT_CARDS[9]  # 代码调试Agent
        assert matcher._compute_match_score(card, "报错分析") == 0.5

    def test_no_match_returns_0(self, matcher):
        """完全不匹配 → 0.0"""
        card = AGENT_CARDS[0]  # LLM基础Agent
        assert matcher._compute_match_score(card, "完全不相关的领域") == 0.0

    def test_primary_takes_precedence_over_secondary(self, matcher):
        """主领域优先级高于次领域（短路返回）"""
        # agent_001: domain_tags=["LLM基础", "Prompt工程"]
        # domain="LLM基础" 应返回 1.0 而非 0.7
        card = AGENT_CARDS[0]
        score = matcher._compute_match_score(card, "LLM基础")
        assert score == 1.0  # 不是 0.7

    def test_each_domain_agent_has_primary_domain(self, matcher):
        """每个领域 Agent 都有自己的主领域（domain_tags[0]）得 1.0"""
        for card in get_domain_agents():
            if not card["domain_tags"]:
                continue
            primary_domain = card["domain_tags"][0]
            score = matcher._compute_match_score(card, primary_domain)
            assert score == 1.0, (
                f"{card['agent_name']} 的主领域 {primary_domain} 应得 1.0，实际 {score}"
            )

    def test_resource_agent_no_match(self, matcher):
        """资源生成 Agent（agent_011）domain_tags 为空，任何 domain 都不匹配"""
        resource_card = AGENT_CARDS[10]  # agent_011
        assert resource_card["domain_tags"] == []
        assert matcher._compute_match_score(resource_card, "LLM基础") == 0.0


# ============================================================
# 2. _resolve_domains 领域解析
# ============================================================

class TestResolveDomains:
    """方案书 2.3.2 节领域解析规则"""

    def test_single_domain_one_segment(self, matcher):
        """单领域 → 1 段"""
        profile = _make_profile(domain_hint=["RAG"])
        segments = matcher._resolve_domains(profile)
        assert len(segments) == 1
        assert segments[0][1] == "RAG"

    def test_cross_domain_multi_segments(self, matcher):
        """跨领域 → 每个领域 1 段"""
        profile = _make_profile(
            domain_hint=["RAG", "LangChain"],
            complexity=ComplexityEstimate.CROSS_DOMAIN,
        )
        segments = matcher._resolve_domains(profile)
        assert len(segments) == 2
        domains = [s[1] for s in segments]
        assert "RAG" in domains
        assert "LangChain" in domains

    def test_full_pipeline_split_by_hint_order(self, matcher):
        """全链路规划 → 按 domain_hint 顺序拆段"""
        profile = _make_profile(
            domain_hint=["LLM基础", "RAG", "Agent框架"],
            question_type=QuestionType.FULL_PIPELINE,
            complexity=ComplexityEstimate.FULL_PIPELINE,
        )
        segments = matcher._resolve_domains(profile)
        assert len(segments) == 3
        # 顺序保持
        assert segments[0][1] == "LLM基础"
        assert segments[1][1] == "RAG"
        assert segments[2][1] == "Agent框架"

    def test_empty_hint_fallback_default(self, matcher):
        """domain_hint 为空时退回默认领域"""
        profile = _make_profile(domain_hint=[])
        segments = matcher._resolve_domains(profile)
        assert len(segments) == 1
        assert segments[0][1] == "LLM基础"  # 默认领域

    def test_segment_id_format(self, matcher):
        """段 ID 格式为 seg_N"""
        profile = _make_profile(domain_hint=["RAG", "LangChain"])
        segments = matcher._resolve_domains(profile)
        for i, (seg_id, _) in enumerate(segments):
            assert seg_id == f"seg_{i+1}"


# ============================================================
# 3. _select_candidates 候选遴选
# ============================================================

class TestSelectCandidates:
    """方案书 2.4 节候选遴选 + 2.4.4 早停机制"""

    def test_returns_at_most_two_candidates(self, matcher):
        """每段最多返回 2 个候选"""
        profile = _make_profile(domain_hint=["LLM基础"])
        candidates = matcher._select_candidates("LLM基础", profile)
        assert 1 <= len(candidates) <= 2

    def test_candidate_has_required_fields(self, matcher):
        """候选 Agent 包含必要字段"""
        profile = _make_profile(domain_hint=["LLM基础"])
        candidates = matcher._select_candidates("LLM基础", profile)
        for c in candidates:
            assert "agent_id" in c
            assert "agent_name" in c
            assert "match_score" in c
            assert "importance_score" in c
            assert "composite_score" in c
            assert "function_tag" in c

    def test_candidates_sorted_by_composite_desc(self, matcher):
        """候选按综合权重降序排列"""
        profile = _make_profile(domain_hint=["RAG"])
        candidates = matcher._select_candidates("RAG", profile)
        scores = [c["composite_score"] for c in candidates]
        assert scores == sorted(scores, reverse=True)

    def test_top_candidate_is_primary_domain_agent(self, matcher):
        """主领域 Agent 应排第一（match_score=1.0 最高）"""
        profile = _make_profile(domain_hint=["LLM基础"])
        candidates = matcher._select_candidates("LLM基础", profile)
        # LLM基础Agent（agent_001）的主领域是 LLM基础，应排第一
        assert candidates[0]["agent_id"] == "agent_001"
        assert candidates[0]["match_score"] == 1.0

    def test_suspended_agent_excluded(self, matcher, monkeypatch):
        """被淘汰的 Agent 不走主匹配（兜底逻辑可能以低分加回，但 match_score 必然低）"""
        # 模拟 agent_001 被淘汰
        from backend.db.repositories import agent_repo
        original = agent_repo.get_agent_performance

        def mocked(agent_id, function_tag):
            result = original(agent_id, function_tag)
            if isinstance(result, dict):
                result = dict(result)
                if agent_id == "agent_001":
                    result["is_suspended"] = True
            return result

        monkeypatch.setattr(agent_repo, "get_agent_performance", mocked)

        profile = _make_profile(domain_hint=["LLM基础"])
        candidates = matcher._select_candidates("LLM基础", profile)
        # agent_001 被 suspended 后不走主匹配（match_score=1.0），
        # 兜底逻辑可能以 match_score=0.1 加回，但绝不应该是高分主匹配
        for c in candidates:
            if c["agent_id"] == "agent_001":
                assert c["match_score"] < 1.0, "suspended agent 不应走主匹配路径"

    def test_early_stop_returns_one_candidate(self, matcher, monkeypatch):
        """早停触发时只返回 1 个候选（方案书 2.4.4）"""
        from backend.db.repositories import config_repo
        # 模拟已连续 1 轮稳定，本轮再稳定 → stable_rounds=2 触发早停
        monkeypatch.setattr(config_repo, "get_stable_rounds", lambda: 1)
        # last_snapshot 必须非空才能进入早停判断；返回与当前一致快照 → all_stable=True
        monkeypatch.setattr(config_repo, "get_importance_snapshot", lambda: {"agent_001": 0.5})
        monkeypatch.setattr(config_repo, "set_stable_rounds", lambda x: None)
        monkeypatch.setattr(config_repo, "set_importance_snapshot", lambda x: None)

        profile = _make_profile(domain_hint=["LLM基础"])
        candidates = matcher._select_candidates("LLM基础", profile)
        assert len(candidates) == 1


# ============================================================
# 4. dispatch 三路径
# ============================================================

class TestDispatchPaths:
    """方案书 2.3.1 节三路径路由"""

    def test_generation_path_returns_segments(self, matcher):
        """generation 路径返回段列表"""
        profile = _make_profile(
            domain_hint=["RAG"],
            intent=IntentType.GENERATION,
        )
        result = matcher.dispatch(profile)
        assert result.intent == IntentType.GENERATION
        assert len(result.segments) >= 1
        assert result.navigation_roadmap is None
        assert result.clarification_options is None

    def test_navigation_path_returns_roadmap(self, matcher):
        """navigation 路径返回学习路线图"""
        profile = _make_profile(
            domain_hint=["LLM基础"],
            intent=IntentType.NAVIGATION,
        )
        result = matcher.dispatch(profile)
        assert result.intent == IntentType.NAVIGATION
        assert result.navigation_roadmap is not None
        assert len(result.navigation_roadmap) > 0
        assert result.segments == []
        assert result.clarification_options is None

    def test_clarification_path_returns_options(self, matcher):
        """clarification 路径返回澄清选项"""
        profile = _make_profile(
            domain_hint=[],
            intent=IntentType.CLARIFICATION,
        )
        result = matcher.dispatch(profile)
        assert result.intent == IntentType.CLARIFICATION
        assert result.clarification_options is not None
        assert len(result.clarification_options) > 0
        assert result.segments == []
        assert result.navigation_roadmap is None

    def test_navigation_roadmap_contains_stages(self, matcher):
        """navigation 路线图包含学习阶段"""
        profile = _make_profile(intent=IntentType.NAVIGATION)
        result = matcher.dispatch(profile)
        assert "阶段" in result.navigation_roadmap

    def test_clarification_options_count(self, matcher):
        """clarification 选项数量合理（6 个领域方向）"""
        profile = _make_profile(
            domain_hint=[],
            intent=IntentType.CLARIFICATION,
        )
        result = matcher.dispatch(profile)
        assert result.clarification_options is not None
        assert len(result.clarification_options) >= 4

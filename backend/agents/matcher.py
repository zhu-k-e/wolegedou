"""调度员 Matcher - 模块一（第二部分）

对应方案书 2.3 节三步调度框架：
  Step 1: 意图裁决（generation/navigation/clarification路由）
  Step 2: 领域解析（段数+每段领域）
  Step 3: 候选遴选（每段2个候选Agent）

以及 2.4 节调度员选人机制：
  2.4.1 标签匹配度计算
  2.4.2 综合遴选权重（α动态切换）
  2.4.3 动态淘汰
"""

from dataclasses import dataclass
from typing import Optional

from loguru import logger

from backend.schemas.student_profile import (
    StudentProfile,
    IntentType,
    ConfidenceLevel,
    QuestionType,
)
from backend.db.repositories import agent_repo, config_repo
from backend.agents.agent_registry import get_domain_agents


@dataclass
class Segment:
    """一个调度段"""
    seg_id: str
    domain: str                  # 该段对应的domain_hint
    candidates: list[dict]       # 候选Agent列表 [{agent_id, match_score, importance_score}]


@dataclass
class DispatchResult:
    """调度结果"""
    intent: IntentType
    segments: list[Segment]              # generation路径的段列表
    navigation_roadmap: Optional[str]    # navigation路径的路线图
    clarification_options: Optional[list[str]]  # clarification路径的选项


class Matcher:
    """调度员 - 从Agent池遴选候选Agent

    调度员仅属于模块一，不参与审核/裁判阶段。
    """

    def __init__(self):
        self._domain_agents = get_domain_agents()

    def dispatch(self, profile: StudentProfile) -> DispatchResult:
        """三步调度框架

        Step 1: 意图裁决 → 路由
        Step 2: 领域解析 → 段数+每段领域
        Step 3: 候选遴选 → 每段2个候选Agent
        """
        # === Step 1: 意图裁决 ===
        intent = profile.intent_type

        if intent == IntentType.CLARIFICATION:
            return DispatchResult(
                intent=intent,
                segments=[],
                navigation_roadmap=None,
                clarification_options=self._generate_clarification_options(profile),
            )

        if intent == IntentType.NAVIGATION:
            return DispatchResult(
                intent=intent,
                segments=[],
                navigation_roadmap=self._generate_navigation_roadmap(profile),
                clarification_options=None,
            )

        # === generation路径 ===
        # Step 2: 领域解析
        segments_def = self._resolve_domains(profile)

        # Step 3: 候选遴选
        segments = []
        for seg_id, domain in segments_def:
            candidates = self._select_candidates(domain, profile)
            segments.append(Segment(
                seg_id=seg_id,
                domain=domain,
                candidates=candidates,
            ))

        logger.info(
            f"调度完成: intent={intent}, segments={len(segments)}, "
            f"domains={[s.domain for s in segments]}"
        )

        return DispatchResult(
            intent=intent,
            segments=segments,
            navigation_roadmap=None,
            clarification_options=None,
        )

    # ============================================================
    # Step 2: 领域解析
    # ============================================================

    def _resolve_domains(self, profile: StudentProfile) -> list[tuple[str, str]]:
        """根据domain_hint、domain_confidence和complexity_estimate确定段数和每段领域

        对应方案书 2.3.2 节领域解析规则
        """
        hints = profile.domain_hint
        confidences = profile.domain_confidence

        # 全low → 退回clarification
        if hints and all(
            confidences.get(h, ConfidenceLevel.LOW) == ConfidenceLevel.LOW
            for h in hints
        ):
            logger.warning("所有domain_confidence为low，应退回clarification")
            # 这里仍返回领域，由调用方判断是否退回
            # 实际实现中应由画像生成器在intent_type阶段就处理

        # 全链路规划 → 按流程步骤拆段
        if profile.question_type == QuestionType.FULL_PIPELINE:
            # 简化：按domain_hint顺序拆段
            return [(f"seg_{i+1}", h) for i, h in enumerate(hints)]

        # 单领域 → 1段
        if len(hints) <= 1:
            return [("seg_1", hints[0] if hints else "LLM基础")]

        # 跨领域 → 每个领域1段
        return [(f"seg_{i+1}", h) for i, h in enumerate(hints)]

    # ============================================================
    # Step 3: 候选遴选
    # ============================================================

    def _select_candidates(
        self, domain: str, profile: StudentProfile
    ) -> list[dict]:
        """从Agent池遴选候选Agent（每段固定2个）

        对应方案书 2.4 节：
          综合权重 = α × 功能匹配度 + (1-α) × importance_score(function_tag)
          α冷启动0.9 → 数据积累后0.3
        """
        alpha = config_repo.get_alpha()

        # 计算每个Agent的匹配度
        scored_agents = []
        for card in self._domain_agents:
            match_score = self._compute_match_score(card, domain)
            if match_score == 0:
                continue  # 不匹配，跳过

            # 获取importance_score
            function_tag = card["primary_function"]
            perf = agent_repo.get_agent_performance(card["agent_id"], function_tag)

            importance = 0.5  # 冷启动默认值
            is_suspended = False
            if perf:
                importance = perf["importance_score"]
                is_suspended = perf["is_suspended"]

            if is_suspended:
                continue  # 被淘汰的跳过

            # 综合权重
            composite = alpha * match_score + (1 - alpha) * importance

            scored_agents.append({
                "agent_id": card["agent_id"],
                "agent_name": card["agent_name"],
                "match_score": match_score,
                "importance_score": importance,
                "composite_score": round(composite, 4),
                "function_tag": function_tag,
            })

        # 按综合权重排序，取Top-2
        scored_agents.sort(key=lambda x: x["composite_score"], reverse=True)

        # 核心原则：每段固定2个候选Agent
        # 即便只有1个"最匹配"的Agent，也必须从次匹配Agent中选一个补上
        if len(scored_agents) < 2:
            # 放宽匹配规则：从所有Agent中选
            for card in self._domain_agents:
                if any(a["agent_id"] == card["agent_id"] for a in scored_agents):
                    continue
                scored_agents.append({
                    "agent_id": card["agent_id"],
                    "agent_name": card["agent_name"],
                    "match_score": 0.1,  # 放宽匹配
                    "importance_score": 0.5,
                    "composite_score": 0.1 * alpha + 0.5 * (1 - alpha),
                    "function_tag": card["primary_function"],
                })
                if len(scored_agents) >= 2:
                    break

        candidates = scored_agents[:2]
        logger.debug(
            f"候选遴选: domain={domain}, "
            f"candidates={[(c['agent_id'], c['composite_score']) for c in candidates]}"
        )
        return candidates

    def _compute_match_score(self, card: dict, domain: str) -> float:
        """计算功能匹配度

        对应方案书 2.4.1 节：
          primary_function匹配 → 1.0
          secondary_functions匹配 → 0.7
          domain_tags匹配 → 0.5
          否则 → 0
        """
        # 注意：domain是domain_hint值（如"RAG"），需要匹配domain_tags
        if domain in card.get("domain_tags", []):
            # 进一步判断是primary还是secondary
            # 通过function_tag间接判断
            primary_tag = card["primary_function"]
            perf = agent_repo.get_agent_performance(card["agent_id"], primary_tag)
            if perf and not perf["is_suspended"]:
                return 1.0

        for sec in card.get("secondary_functions", []):
            # secondary_functions是功能描述，不是domain_hint
            # 这里简化：如果domain出现在secondary_functions文本中
            if domain.lower() in sec.lower():
                return 0.7

        if domain in card.get("domain_tags", []):
            return 0.5

        return 0.0

    # ============================================================
    # navigation路径
    # ============================================================

    def _generate_navigation_roadmap(self, profile: StudentProfile) -> str:
        """生成学习路线图（Markdown格式）

        对应方案书 2.3.1 节navigation路径
        """
        level = profile.knowledge_level.value
        bg = profile.background.value
        goal = profile.current_goal.value

        return (
            f"# AI技能培训学习路线图\n\n"
            f"> 根据你的学情画像（{level} / {bg} / {goal}），推荐以下学习路径：\n\n"
            f"## 第一阶段：基础入门\n"
            f"| 知识点 | 预计学习时间 | 学习目标 |\n"
            f"|--------|--------------|----------|\n"
            f"| LLM基础 | 2小时 | 理解大模型基本原理 |\n"
            f"| Prompt工程 | 3小时 | 掌握提示词设计方法 |\n\n"
            f"## 第二阶段：应用开发\n"
            f"| 知识点 | 预计学习时间 | 学习目标 |\n"
            f"|--------|--------------|----------|\n"
            f"| RAG原理与实战 | 4小时 | 掌握检索增强生成 |\n"
            f"| 向量数据库 | 3小时 | 掌握向量存储与检索 |\n"
            f"| LangChain开发 | 5小时 | 掌握Agent开发框架 |\n\n"
            f"## 第三阶段：高级技术\n"
            f"| 知识点 | 预计学习时间 | 学习目标 |\n"
            f"|--------|--------------|----------|\n"
            f"| 模型微调 | 6小时 | 掌握参数高效微调 |\n"
            f"| Agent框架进阶 | 4小时 | 掌握多Agent协作 |\n"
            f"| 项目部署 | 3小时 | 掌握API封装与部署 |\n\n"
            f"---\n"
            f"**你想从哪个阶段开始深入学习？请输入阶段编号（一/二/三）。**"
        )

    # ============================================================
    # clarification路径
    # ============================================================

    def _generate_clarification_options(self, profile: StudentProfile) -> list[str]:
        """生成澄清选项

        对应方案书 2.3.1 节clarification路径
        """
        return [
            "① LLM基础与Prompt工程",
            "② RAG与向量数据库",
            "③ LangChain开发",
            "④ 模型微调",
            "⑤ Agent框架",
            "⑥ 项目部署",
        ]

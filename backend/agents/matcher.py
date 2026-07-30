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

        # 意图兜底：LLM 偶尔对"什么是RAG"这类简短但领域明确的问题过度保守判 clarification
        # 既然已经识别到 domain_hint（有领域线索），就强制走 generation 直接给学习资源
        if intent == IntentType.CLARIFICATION and profile.domain_hint:
            logger.info(
                f"[意图兜底] LLM判clarification但有domain_hint={profile.domain_hint}，改判generation"
            )
            intent = IntentType.GENERATION

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

        # P0-2: 如果领域解析返回空（全low情况），退回clarification
        if not segments_def and profile.domain_hint:
            logger.info(
                f"[DISPATCHING回退] domain_confidence全low，转入clarification路径: "
                f"hints={profile.domain_hint}"
            )
            return DispatchResult(
                intent=IntentType.CLARIFICATION,
                segments=[],
                navigation_roadmap=None,
                clarification_options=self._generate_clarification_options(profile),
            )

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

        P0-2修复：
          - 全low时返回空列表作为信号，由调用方决定退回clarification
          - 调用方（matcher.dispatch + orchestrator._do_dispatching）
            收到空列表后转为clarification路径
        """
        hints = profile.domain_hint
        confidences = profile.domain_confidence

        # P0-2: 全low → 返回空列表，由调用方退回clarification
        if hints and all(
            confidences.get(h, ConfidenceLevel.LOW) == ConfidenceLevel.LOW
            for h in hints
        ):
            logger.warning(
                "所有domain_confidence为low，退回clarification: "
                f"hints={hints}, confidences={confidences}"
            )
            return []

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
        """从Agent池遴选候选Agent

        对应方案书 2.4 节：
          综合权重 = α × 功能匹配度 + (1-α) × importance_score(function_tag)
          α冷启动0.9 → 数据积累后0.3

        对应方案书 2.4.4 节早停机制：
          连续2轮importance_score波动<0.05 → 只选Top-1，节省API调用
        """
        alpha = config_repo.get_alpha()

        # P1-3: 早停机制 — 检查importance_score历史波动
        last_snapshot = config_repo.get_importance_snapshot()
        current_snapshot = {}

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

            # 记录当前快照
            current_snapshot[card["agent_id"]] = importance

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

        # P1-3: 早停判断 — 连续2轮importance_score波动<0.05时只选Top-1（方案书2.4.4）
        early_stop = False
        if last_snapshot and current_snapshot:
            all_stable = True
            for agent_id, score in current_snapshot.items():
                last_score = last_snapshot.get(agent_id, score)
                if abs(score - last_score) >= 0.05:
                    all_stable = False
                    break

            # 连续2轮稳定才触发早停（避免单次巧合误判）
            stable_rounds = config_repo.get_stable_rounds()
            if all_stable:
                stable_rounds += 1
            else:
                stable_rounds = 0

            if stable_rounds >= 2:
                early_stop = True
                logger.info(
                    f"早停触发: domain={domain}, 连续{stable_rounds}轮"
                    f"importance_score波动<0.05，只选Top-1候选"
                )

            config_repo.set_stable_rounds(stable_rounds)

        # 核心原则：每段固定2个候选Agent（早停时只选1个）
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

        # 早停时只取1个，否则取2个
        top_n = 1 if early_stop else 2
        candidates = scored_agents[:top_n]
        logger.debug(
            f"候选遴选: domain={domain}, early_stop={early_stop}, "
            f"candidates={[(c['agent_id'], c['composite_score']) for c in candidates]}"
        )

        # 更新importance_score快照（供下一轮早停判断）
        config_repo.set_importance_snapshot(current_snapshot)

        return candidates

    def _compute_match_score(self, card: dict, domain: str) -> float:
        """计算功能匹配度

        对应方案书 2.4.1 节三档评分：
          primary_function 主领域匹配   → 1.0
          secondary_functions 次领域匹配 → 0.7
          domain_tags 弱标签匹配        → 0.5
          否则                          → 0.0

        实现说明（基于 AGENT_CARDS 结构）：
          domain_tags[0] 视为 Agent 的主领域（与 primary_function 对应），
          domain_tags[1:] 视为次领域（Agent 有该领域次要能力，对应 secondary_functions），
          domain 出现在 secondary_functions 文本中视为弱标签相关。
        所有分支互斥，按 1.0 → 0.7 → 0.5 顺序短路返回，无死代码。
        """
        domain_tags = card.get("domain_tags", [])

        # 1. 主领域匹配 → primary_function 档 → 1.0
        if domain_tags and domain_tags[0] == domain:
            return 1.0

        # 2. 次领域匹配 → secondary_functions 档 → 0.7
        if domain in domain_tags[1:]:
            return 0.7

        # 3. 弱标签匹配：domain 出现在 secondary_functions 文本中 → 0.5
        domain_lower = domain.lower()
        for sec in card.get("secondary_functions", []):
            if domain_lower in sec.lower():
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

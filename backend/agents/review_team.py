"""审核团队 - 模块三（第一部分）

对应方案书 4.2 节：
  4.2.1 三人Persona定义（Verifier/Skeptic/Evaluator）
  4.2.2 Verifier——事实核查
  4.2.3 Skeptic——检查清单
  4.2.4 Evaluator——教学适配评估
  4.2.5 段内评选汇总规则
  4.2.6 审核团队意见冲突解决
  4.3 跨段一致性审查
"""

import asyncio
import json
from typing import Optional

from loguru import logger

from backend.agents.base_agent import BaseAgent
from backend.schemas.candidate_output import CandidateOutput
from backend.schemas.review_feedback import (
    ReviewFeedback,
    CandidateReview,
    ReviewerScores,
    IssueFound,
)
from backend.schemas.student_profile import StudentProfile
from backend.services.llm_client import ModelTier
from backend.db.repositories import config_repo


def _safe_str(item) -> str:
    """将 LLM 返回的 item 安全转为字符串（兼容 str 和 dict 两种格式）"""
    if isinstance(item, str):
        return item
    if isinstance(item, dict):
        parts = []
        for key in ("item", "description", "issue", "detail", "reason", "problem"):
            val = item.get(key)
            if val:
                parts.append(str(val))
        return " | ".join(parts) if parts else json.dumps(item, ensure_ascii=False)
    return str(item)


class Verifier(BaseAgent):
    """事实核查员 - 逐条核查知识点是否正确

    锚定方式：将Agent输出切分为知识点陈述，对每个陈述去知识库检索验证。
    """

    def __init__(self, **kwargs):
        super().__init__(agent_id="review_verifier", agent_name="Verifier", **kwargs)

    @property
    def system_prompt(self) -> str:
        return (
            "你是一个事实核查员。请对AI输出进行逐条事实核查。\n"
            "对每条知识点，去知识库检索验证（系统已为你检索好Top-3相关片段）。\n"
            "输出严格JSON: {\"fact_accuracy\": 0.0-1.0, \"verified_count\": N, "
            "\"contradiction_count\": N, \"unverified_items\": [], \"contradiction_items\": []}"
        )

    async def review(
        self, candidate: CandidateOutput, profile: StudentProfile
    ) -> tuple[float, list[IssueFound]]:
        """审核单个候选输出"""
        # 知识库检索验证
        kb_results = []
        for ref in candidate.answer.knowledge_refs:
            result = await self._kb.verify_statement(ref.content_summary)
            kb_results.append({"statement": ref.content_summary, "verification": result})

        user_prompt = (
            f"AI输出：\n{candidate.answer.model_dump_json(indent=2)}\n\n"
            f"知识库验证结果：\n{json.dumps(kb_results, ensure_ascii=False, indent=2)}"
        )

        raw = await self.generate(user_prompt, tier=ModelTier.MID, temperature=0.0)
        data = await self.parse_json_safe(raw)
        if data is None:
            data = {"fact_accuracy": 0.5, "verified_count": 0, "contradiction_count": 0, "unverified_items": [], "contradiction_items": []}

        score = data.get("fact_accuracy", 0.5)
        issues = [
            IssueFound(
                reviewer="Verifier",
                severity="high" if data.get("contradiction_count", 0) > 0 else "medium",
                location=f"knowledge_refs[{i}]",
                description=_safe_str(item),
            )
            for i, item in enumerate(data.get("contradiction_items", []))
        ]
        issues.extend([
            IssueFound(
                reviewer="Verifier", severity="low",
                location=f"knowledge_refs[{i}]",
                description=_safe_str(item),
            )
            for i, item in enumerate(data.get("unverified_items", []))
        ])

        return score, issues


class Skeptic(BaseAgent):
    """逻辑挑刺者 - 过5条固定检查清单

    不依赖LLM自由判断，每条通过得0.2分，总分1.0。
    """

    CHECKLIST = [
        "每一步推理是否给出了原因？",
        "结论是否和前面的推理一致？",
        "有没有遗漏已知的前置条件？",
        "是否存在循环论证？",
        "关键步骤是否可执行（如果是操作步骤类）？",
    ]

    def __init__(self, **kwargs):
        super().__init__(agent_id="review_skeptic", agent_name="Skeptic", **kwargs)

    @property
    def system_prompt(self) -> str:
        checklist_str = "\n".join(f"清单{i+1}：{item}" for i, item in enumerate(self.CHECKLIST))
        return (
            "你是一个逻辑挑刺者。请对照以下5条检查清单，逐条评估AI输出。\n"
            f"{checklist_str}\n\n"
            "评分：每条通过→+0.2；不通过→0；部分通过→+0.1\n"
            "输出严格JSON: {\"logic_completeness\": 0.0-1.0, "
            "\"checklist_results\": [{\"item\": \"清单1\", \"passed\": true, \"score\": 0.2, \"reason\": \"...\"}], "
            "\"failed_items\": [\"不通过的清单条目及原因，必须是字符串\"]}"
        )

    async def review(
        self, candidate: CandidateOutput, profile: StudentProfile
    ) -> tuple[float, list[IssueFound]]:
        user_prompt = f"AI输出：\n{candidate.answer.model_dump_json(indent=2)}"

        raw = await self.generate(user_prompt, tier=ModelTier.MID, temperature=0.0)
        data = await self.parse_json_safe(raw)
        if data is None:
            data = {"logic_completeness": 0.5, "checklist_results": [], "failed_items": []}

        # 按方案书 §4.2.3：从 checklist_results 自行计算总分，不信任 LLM 自报的 logic_completeness
        checklist = data.get("checklist_results", [])
        if checklist:
            score = sum(float(item.get("score", 0)) for item in checklist)
            score = max(0.0, min(1.0, score))
        else:
            score = data.get("logic_completeness", 0.5)

        issues = [
            IssueFound(
                reviewer="Skeptic", severity="medium",
                location="reasoning_steps",
                description=_safe_str(item),
            )
            for item in data.get("failed_items", [])
        ]

        return score, issues


class Evaluator(BaseAgent):
    """教学适配评估员 - 对照学情画像逐字段评估

    4个维度：knowledge_level匹配度 / background适配度 / goal对齐度 / 可操作性
    """

    def __init__(self, **kwargs):
        super().__init__(agent_id="review_evaluator", agent_name="Evaluator", **kwargs)

    @property
    def system_prompt(self) -> str:
        return (
            "你是一个教学适配评估员。请根据学情画像，评估AI输出对该学生的适配程度。\n"
            "逐条评估4个维度（0.0-1.0）：\n"
            "1. knowledge_level匹配度\n2. background适配度\n"
            "3. goal对齐度\n4. 可操作性\n\n"
            "输出严格JSON: {\"pedagogical_fit\": 0.0-1.0, "
            "\"dimension_scores\": {\"level_match\": 0, \"bg_fit\": 0, \"goal_align\": 0, \"actionability\": 0}, "
            "\"mismatch_details\": []}"
        )

    async def review(
        self, candidate: CandidateOutput, profile: StudentProfile
    ) -> tuple[float, list[IssueFound]]:
        user_prompt = (
            f"学情画像：\n{profile.model_dump_json(indent=2)}\n\n"
            f"AI输出：\n{candidate.answer.model_dump_json(indent=2)}"
        )

        raw = await self.generate(user_prompt, tier=ModelTier.MID, temperature=0.0)
        data = await self.parse_json_safe(raw)
        if data is None:
            data = {"pedagogical_fit": 0.5, "dimension_scores": {}, "mismatch_details": []}

        score = data.get("pedagogical_fit", 0.5)
        issues = [
            IssueFound(
                reviewer="Evaluator", severity="medium",
                location="answer",
                description=_safe_str(item),
            )
            for item in data.get("mismatch_details", [])
        ]

        return score, issues


class ReviewTeam:
    """审核团队 - 3人并行评分 + 段内评选 + 跨段一致性审查

    对应方案书 4.2 节
    """

    def __init__(self, **kwargs):
        self.verifier = Verifier(**kwargs)
        self.skeptic = Skeptic(**kwargs)
        self.evaluator = Evaluator(**kwargs)

    async def review_segment(
        self,
        candidates: list[CandidateOutput],
        profile: StudentProfile,
        seg_id: str,
    ) -> ReviewFeedback:
        """审核一个段的所有候选输出

        对应方案书 4.2.5 段内评选汇总规则：
          综合得分 = fact_accuracy * w1 + logic_completeness * w2 + pedagogical_fit * w3
        """
        weights = config_repo.get_review_weights()
        w1, w2, w3 = weights["w1"], weights["w2"], weights["w3"]

        candidate_reviews = []

        for candidate in candidates:
            # 3人并行评分（方案书§8.4.2优化1：asyncio.gather节省2×3秒）
            (v_score, v_issues), (s_score, s_issues), (e_score, e_issues) = await asyncio.gather(
                self.verifier.review(candidate, profile),
                self.skeptic.review(candidate, profile),
                self.evaluator.review(candidate, profile),
            )

            # 综合得分
            composite = v_score * w1 + s_score * w2 + e_score * w3

            all_issues = v_issues + s_issues + e_issues

            candidate_reviews.append(CandidateReview(
                agent_id=candidate.agent_id,
                scores=ReviewerScores(
                    fact_accuracy=v_score,
                    logic_completeness=s_score,
                    pedagogical_fit=e_score,
                ),
                issues_found=all_issues,
                is_winner=False,  # 稍后判定
            ))

            logger.debug(
                f"审核完成: {candidate.agent_id} seg={seg_id}, "
                f"V={v_score:.2f} S={s_score:.2f} E={e_score:.2f} → composite={composite:.4f}"
            )

        # 选出综合得分最高的为winner
        # 按 composite score 排序
        composites = []
        for cr in candidate_reviews:
            composite = (
                cr.scores.fact_accuracy * w1
                + cr.scores.logic_completeness * w2
                + cr.scores.pedagogical_fit * w3
            )
            composites.append(composite)

        winner_idx = composites.index(max(composites))
        candidate_reviews[winner_idx].is_winner = True

        logger.info(
            f"段内评选完成: seg={seg_id}, winner={candidate_reviews[winner_idx].agent_id}, "
            f"composite={composites[winner_idx]:.4f}"
        )

        return ReviewFeedback(
            seg_id=seg_id,
            candidates=candidate_reviews,
        )

    async def check_cross_segment_consistency(
        self,
        segment_reviews: list[ReviewFeedback],
        profile: StudentProfile,
    ) -> list[IssueFound]:
        """跨段一致性审查（多段场景）

        对应方案书 4.3 节
        """
        if len(segment_reviews) <= 1:
            return []

        # 构建各段摘要
        summaries = []
        for review in segment_reviews:
            winner = next(c for c in review.candidates if c.is_winner)
            summaries.append(f"段{review.seg_id}: winner={winner.agent_id}")

        user_prompt = (
            f"请检查以下各段输出的一致性：\n{chr(10).join(summaries)}\n\n"
            f"检查维度：\n"
            f"1. 前后段术语是否一致\n"
            f"2. 第N段开头是否承接第N-1段结尾\n"
            f"3. 步骤编号是否连续\n\n"
            f"输出JSON: {{\"issues\": [{{\"severity\": \"medium\", "
            f"\"location\": \"seg_1-seg_2\", \"description\": \"问题描述\"}}]}}"
        )

        raw = await self.verifier.generate(user_prompt, tier=ModelTier.MID, temperature=0.0)

        data = await self.verifier.parse_json_safe(raw)
        if data is None:
            return []
        return [
            IssueFound(
                reviewer="CrossSegment",
                severity=issue.get("severity", "medium"),
                location=issue.get("location", ""),
                description=issue.get("description", ""),
            )
            for issue in data.get("issues", [])
        ]

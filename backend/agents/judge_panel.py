"""裁判团 - 模块三（第二部分）

对应方案书 4.4 节：
  4.4.1 三人分工（事实审查/逻辑审查/适用性审查）
  4.4.2 分歧解决状态机（DISSENT_RESOLVE）
  4.4.3 反向怀疑机制
  4.4.4 高保真知识溯源标注
"""

import json
from typing import Optional

from loguru import logger

from backend.agents.base_agent import BaseAgent
from backend.agents.domain_agent import DomainAgent
from backend.agents.review_team import _safe_str
from backend.schemas.candidate_output import CandidateOutput
from backend.schemas.focused_output import FocusedOutput
from backend.schemas.judge_verdict import (
    JudgeVerdict,
    Verdict,
    JudgeOpinion,
    DissentResolution,
    CandidateDebate,
    TraceabilityItem,
    VerificationStatus,
)
from backend.schemas.student_profile import StudentProfile
from backend.services.llm_client import ModelTier


class JudgeFact(BaseAgent):
    """裁判1 - 事实审查（知识库对照专家）"""

    def __init__(self, **kwargs):
        super().__init__(agent_id="judge_fact", agent_name="事实审查裁判", **kwargs)

    @property
    def system_prompt(self) -> str:
        return (
            "你是一名事实审查裁判。请对聚焦输出进行独立审查。\n"
            "【重要】你的审查是独立的，不要参考其他裁判的意见。\n\n"
            "任务：\n"
            "1. 对每条knowledge_refs，去知识库检索验证\n"
            "2. 判断整体输出是否足以直接提供给学生\n"
            "   - 事实准确率≥90%且无未验证错误 → passed\n"
            "   - 事实准确率≥90%但有轻微表述问题 → revise\n"
            "   - 事实准确率80%-90% → low_confidence_passed\n"
            "   - 否则 → failed\n\n"
            "【反向怀疑】若knowledge_refs≥5条 / code_example≥20行 / reasoning_steps≥8步，"
            "启用严格审查（每条必须100%可溯源）\n\n"
            "输出JSON: {\"verdict\": \"passed/revise/low_confidence_passed/failed\", "
            "\"confidence\": 0.0-1.0, \"issues\": [], \"verification_coverage\": 0.0-1.0}"
        )


class JudgeLogic(BaseAgent):
    """裁判2 - 逻辑审查（推理链完整性专家，对应MAR论文Logician）"""

    def __init__(self, **kwargs):
        super().__init__(agent_id="judge_logic", agent_name="逻辑审查裁判", **kwargs)

    @property
    def system_prompt(self) -> str:
        return (
            "你是一名逻辑审查裁判。请检查推理链的完整性和一致性。\n"
            "【重要】你的审查是独立的。\n\n"
            "检查重点：\n"
            "1. 步骤之间有没有跳跃\n"
            "2. 有没有矛盾\n"
            "3. 结论是否由推理步骤支持\n\n"
            "输出JSON: {\"verdict\": \"passed/revise/low_confidence_passed/failed\", "
            "\"confidence\": 0.0-1.0, \"issues\": []}"
        )


class JudgeApplicability(BaseAgent):
    """裁判3 - 适用性审查（学生适配专家）"""

    def __init__(self, **kwargs):
        super().__init__(agent_id="judge_applicability", agent_name="适用性审查裁判", **kwargs)

    @property
    def system_prompt(self) -> str:
        return (
            "你是一名适用性审查裁判。请评估输出对该学生是否合适。\n"
            "【重要】你的审查是独立的。\n\n"
            "防止'准确但不适合'的答案通过：\n"
            "1. 难度是否匹配学生knowledge_level\n"
            "2. 是否考虑了学生background\n"
            "3. 是否朝着学生current_goal方向\n\n"
            "输出JSON: {\"verdict\": \"passed/revise/low_confidence_passed/failed\", "
            "\"confidence\": 0.0-1.0, \"issues\": []}"
        )


class JudgePanel:
    """裁判团 - 3人独立审查 + 分歧解决 + 候选辩论 + 溯源标注

    对应方案书 4.4 节

    核心设计原则（来自Debate论文）：
      - 三人独立审查，互不可见
      - 裁判团不看到审核团队的review_score
      - 裁判团只看到：聚焦输出JSON + 学情画像 + 知识库检索接口
    """

    def __init__(self, **kwargs):
        self.judge_fact = JudgeFact(**kwargs)
        self.judge_logic = JudgeLogic(**kwargs)
        self.judge_applicability = JudgeApplicability(**kwargs)

    async def judge(
        self,
        focused_output: FocusedOutput,
        profile: StudentProfile,
        winning_candidate: Optional[CandidateOutput] = None,
        losing_candidate: Optional[CandidateOutput] = None,
        losing_agent: Optional[DomainAgent] = None,
        winning_agent: Optional[DomainAgent] = None,
    ) -> JudgeVerdict:
        """裁判团完整审查流程

        状态机：
          REVIEWING → COMPARING → PASSED(3:0) 或 DISSENT_RESOLVE(2:1) → REVISING/PASSED
        """
        import asyncio

        # === [REVIEWING] 三人独立审查（并行） ===
        judges_tasks = [
            self._judge_single(self.judge_fact, focused_output, profile),
            self._judge_single(self.judge_logic, focused_output, profile),
            self._judge_single(self.judge_applicability, focused_output, profile),
        ]
        judge_results = await asyncio.gather(*judges_tasks)
        judges = list(judge_results)

        # === [COMPARING] 汇总 ===
        pass_count = sum(1 for j in judges if j.judgment == "pass")
        fail_count = 3 - pass_count

        logger.info(f"裁判团投票: pass={pass_count}, fail={fail_count}")

        # 3:0 全票通过
        if pass_count == 3:
            verdict_value = Verdict.PASSED
            dissent_resolution = None
        # 2:1 分歧
        elif pass_count == 2:
            verdict_value, dissent_resolution = await self._resolve_dissent(
                focused_output, profile, judges,
                winning_candidate, losing_candidate,
                losing_agent, winning_agent,
            )
        # 1:2 或 0:3 未通过
        else:
            verdict_value = Verdict.FAILED if fail_count == 3 else Verdict.REVISE
            dissent_resolution = None

        # === 溯源标注（裁判1执行） ===
        traceability = await self._annotate_traceability(focused_output)
        verified_count = sum(1 for t in traceability if t.verification_status == VerificationStatus.VERIFIED)
        overall_rate = verified_count / len(traceability) if traceability else 0.0

        return JudgeVerdict(
            verdict=verdict_value,
            judges=judges,
            dissent_resolution=dissent_resolution,
            traceability=traceability,
            overall_verification_rate=overall_rate,
        )

    async def _judge_single(
        self, judge: BaseAgent, focused: FocusedOutput, profile: StudentProfile
    ) -> JudgeOpinion:
        """单个裁判独立审查"""
        user_prompt = (
            f"聚焦输出（待审查）：\n{focused.model_dump_json(indent=2)}\n\n"
            f"学情画像：\n{profile.model_dump_json(indent=2)}"
        )

        raw = await judge.generate(user_prompt, tier=ModelTier.HIGH, temperature=0.0)
        data = json.loads(raw)

        # 将 LLM 返回的 verdict 归一化为 pass / fail 二元判断
        raw_verdict = data.get("verdict", "failed")
        judgment = "pass" if raw_verdict in ("passed", "low_confidence_passed") else "fail"

        return JudgeOpinion(
            role=judge.agent_name,
            judgment=judgment,
            evidence=[_safe_str(item) for item in data.get("issues", [])],
            confidence=data.get("confidence", 0.5),
        )

    async def _resolve_dissent(
        self,
        focused: FocusedOutput,
        profile: StudentProfile,
        judges: list[JudgeOpinion],
        winning_candidate: Optional[CandidateOutput],
        losing_candidate: Optional[CandidateOutput],
        losing_agent: Optional[DomainAgent],
        winning_agent: Optional[DomainAgent],
    ) -> tuple[Verdict, DissentResolution]:
        """分歧解决（DISSENT_RESOLVE状态）

        对应方案书 4.4.2 节：
          第一层：裁判团分歧解决（少数方举证→多数方回应→僵持裁判长裁决）
          第二层：候选Agent辩论（落选候选质疑+获胜候选辩护）
        """
        # 找出少数方
        minority = next(j for j in judges if j.judgment == "fail")
        majority = [j for j in judges if j.judgment == "pass"]

        # 第一层：少数方举证
        minority_evidence = minority.evidence

        # 第二层：候选Agent辩论（如果有落选候选）
        candidate_debate = None
        if losing_agent and winning_agent and losing_candidate and winning_candidate:
            # 落选候选质疑
            challenge_evidence = await losing_agent.debate_challenge(
                question="",  # 从上下文获取
                winning_output=focused,
                minority_opinion="; ".join(minority_evidence),
            )

            # 获胜候选辩护
            defense_evidence = await winning_agent.debate_defense(
                question="",
                original_output=winning_candidate,
                challenge_evidence=challenge_evidence,
            )

            candidate_debate = CandidateDebate(
                challenging_agent=losing_candidate.agent_id,
                challenge_evidence=challenge_evidence,
                defending_agent=winning_candidate.agent_id,
                defense_evidence=defense_evidence,
            )

        # 裁判团根据辩论证据重新判断
        # 简化实现：如果辩论证据揭示实质问题 → revise，否则 → passed
        all_evidence = minority_evidence
        if candidate_debate:
            all_evidence.extend(candidate_debate.challenge_evidence)

        # 判断证据是否充分（简化：有证据则revise）
        if len(all_evidence) > 0:
            verdict = Verdict.REVISE
            majority_response = "accepted"
        else:
            verdict = Verdict.PASSED
            majority_response = "rejected"

        logger.info(f"分歧解决完成: verdict={verdict}, evidence_count={len(all_evidence)}")

        return verdict, DissentResolution(
            minority_judge=minority.role,
            evidence_submitted=minority_evidence,
            majority_response=majority_response,
            candidate_debate=candidate_debate,
        )

    async def _annotate_traceability(
        self, focused: FocusedOutput
    ) -> list[TraceabilityItem]:
        """高保真知识溯源标注

        对应方案书 4.4.4 节：裁判1对每条knowledge_refs验证来源
        """
        items = []
        for ref in focused.knowledge_refs:
            result = await self.judge_fact._kb.verify_statement(ref.content_summary)

            status_map = {
                "已验证": VerificationStatus.VERIFIED,
                "矛盾": VerificationStatus.CONTRADICTED,
                "待验证": VerificationStatus.UNVERIFIED,
            }
            status = status_map.get(result.get("status", "待验证"), VerificationStatus.UNVERIFIED)

            items.append(TraceabilityItem(
                statement=ref.content_summary,
                source=result.get("source", ref.source),
                verification_status=status,
            ))

        return items

    async def recheck(
        self, focused: FocusedOutput, feedback: str
    ) -> dict:
        """审核复检（RECHECK状态）

        对应方案书 6.1.3 节延伸路径：
          学生反馈"内容有误" → 审核团队对被质疑内容进行专项复检
        """
        user_prompt = (
            f"学生反馈内容有误：{feedback}\n\n"
            f"原输出：\n{focused.model_dump_json(indent=2)}\n\n"
            f"请复检该内容是否确实有误。"
            f"输出JSON: {{\"has_error\": true/false, \"error_detail\": \"错误描述\", "
            f"\"corrected_content\": \"修正内容\"}}"
        )

        raw = await self.judge_fact.generate(user_prompt, tier=ModelTier.HIGH, temperature=0.0)
        return json.loads(raw)

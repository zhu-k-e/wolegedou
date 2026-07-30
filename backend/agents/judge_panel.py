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
from backend.schemas.review_feedback import ReviewFeedback
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
            "【反向怀疑】系统会自动检测输出复杂度并在触发时注入"
            "「严格审查模式」指令。收到该指令时，每条必须100%可溯源。\n\n"
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

    # 反向怀疑触发阈值（方案书 4.4.3 节）
    _RS_REFS_THRESHOLD = 5
    _RS_CODE_LINES_THRESHOLD = 20
    _RS_STEPS_THRESHOLD = 8

    def __init__(self, **kwargs):
        self.judge_fact = JudgeFact(**kwargs)
        self.judge_logic = JudgeLogic(**kwargs)
        self.judge_applicability = JudgeApplicability(**kwargs)

    def _detect_reverse_suspicion(self, focused: FocusedOutput) -> bool:
        """反向怀疑检测（方案书 4.4.3 节）

        被动触发式：当聚焦输出内容复杂度过高时，启用严格审查。
        触发条件（任一满足）：
          - knowledge_refs ≥ 5条
          - code_example ≥ 20行
          - reasoning_steps ≥ 8步

        Returns:
            True 表示触发严格审查模式
        """
        refs_count = len(focused.knowledge_refs)
        code_lines = len(focused.code_example.splitlines()) if focused.code_example else 0
        steps_count = len(focused.reasoning_steps)

        triggered = (
            refs_count >= self._RS_REFS_THRESHOLD
            or code_lines >= self._RS_CODE_LINES_THRESHOLD
            or steps_count >= self._RS_STEPS_THRESHOLD
        )
        if triggered:
            logger.info(
                f"反向怀疑触发: refs={refs_count}(阈值{self._RS_REFS_THRESHOLD}), "
                f"code_lines={code_lines}(阈值{self._RS_CODE_LINES_THRESHOLD}), "
                f"steps={steps_count}(阈值{self._RS_STEPS_THRESHOLD})"
            )
        return triggered

    def _check_review_unanimous(self, review_feedback: Optional[ReviewFeedback]) -> bool:
        """检查审核评分是否全票一致（方案书§8.4.2优化4）

        若获胜候选的3位审核员评分分差<0.05，认为审核全票一致。
        此场景下裁判团可走快速通道，仅做溯源标注。
        """
        if not review_feedback:
            return False
        winner = next((c for c in review_feedback.candidates if c.is_winner), None)
        if not winner:
            return False
        scores = [
            winner.scores.fact_accuracy,
            winner.scores.logic_completeness,
            winner.scores.pedagogical_fit,
        ]
        score_range = max(scores) - min(scores)
        unanimous = score_range < 0.05
        if unanimous:
            logger.info(
                f"审核全票一致: V={scores[0]:.2f} S={scores[1]:.2f} E={scores[2]:.2f}, "
                f"分差={score_range:.3f}<0.05"
            )
        return unanimous

    async def judge(
        self,
        focused_output: FocusedOutput,
        profile: StudentProfile,
        question: str = "",
        winning_candidate: Optional[CandidateOutput] = None,
        losing_candidate: Optional[CandidateOutput] = None,
        losing_agent: Optional[DomainAgent] = None,
        winning_agent: Optional[DomainAgent] = None,
        review_feedback: Optional[ReviewFeedback] = None,
    ) -> JudgeVerdict:
        """裁判团完整审查流程

        状态机：
          REVIEWING → COMPARING → PASSED(3:0) 或 DISSENT_RESOLVE(2:1) → REVISING/PASSED

        快速通道（方案书§8.4.2优化4）：
          若审核评分全票一致（3人分差<0.05），仅做溯源标注，跳过完整审查。
        """
        import asyncio

        # === 快速通道：审核评分全票一致时仅做溯源标注 ===
        if self._check_review_unanimous(review_feedback):
            logger.info("裁判团快速通道: 审核评分全票一致，跳过完整审查")
            traceability = await self._annotate_traceability(focused_output)
            verified_count = sum(
                1 for t in traceability if t.verification_status == VerificationStatus.VERIFIED
            )
            overall_rate = verified_count / len(traceability) if traceability else 0.0

            verdict_value = Verdict.PASSED if overall_rate >= 0.9 else Verdict.LOW_CONFIDENCE_PASSED

            return JudgeVerdict(
                verdict=verdict_value,
                judges=[JudgeOpinion(
                    role="快速通道（审核全票一致）",
                    judgment="pass",
                    evidence=[],
                    confidence=0.95,
                )],
                dissent_resolution=None,
                traceability=traceability,
                overall_verification_rate=overall_rate,
            )

        # === 反向怀疑检测（方案书 4.4.3 节） ===
        strict_mode = self._detect_reverse_suspicion(focused_output)

        # === [REVIEWING] 三人独立审查（并行） ===
        judges_tasks = [
            self._judge_single(self.judge_fact, focused_output, profile, strict_mode),
            self._judge_single(self.judge_logic, focused_output, profile, strict_mode),
            self._judge_single(self.judge_applicability, focused_output, profile, strict_mode),
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
            override_reason = None
        # 2:1 分歧
        elif pass_count == 2:
            verdict_value, dissent_resolution = await self._resolve_dissent(
                focused_output, profile, judges, question,
                winning_candidate, losing_candidate,
                losing_agent, winning_agent,
            )
            override_reason = None
        # 0:3 全票失败 → 裁判长终审门控（方案书4.4.2延伸：0:3状态机未定义）
        elif fail_count == 3:
            verdict_value, override_reason = await self._final_review_on_unanimous_fail(
                focused_output, profile, judges
            )
            dissent_resolution = None
        # 1:2 未通过
        else:
            verdict_value = Verdict.REVISE
            dissent_resolution = None
            override_reason = None

        # === 溯源标注（裁判1执行） ===
        traceability = await self._annotate_traceability(focused_output)
        verified_count = sum(1 for t in traceability if t.verification_status == VerificationStatus.VERIFIED)
        overall_rate = verified_count / len(traceability) if traceability else 0.0

        # 严格模式下，验证率未达100%则降级（方案书 4.4.3 节）
        if strict_mode and overall_rate < 1.0 and verdict_value == Verdict.PASSED:
            logger.info(
                f"严格审查: 验证率{overall_rate:.0%}<100%, 降级为LOW_CONFIDENCE_PASSED"
            )
            verdict_value = Verdict.LOW_CONFIDENCE_PASSED

        return JudgeVerdict(
            verdict=verdict_value,
            judges=judges,
            dissent_resolution=dissent_resolution,
            traceability=traceability,
            overall_verification_rate=overall_rate,
            override_reason=override_reason,
        )

    async def _judge_single(
        self,
        judge: BaseAgent,
        focused: FocusedOutput,
        profile: StudentProfile,
        strict_mode: bool = False,
    ) -> JudgeOpinion:
        """单个裁判独立审查

        Args:
            strict_mode: 反向怀疑触发的严格审查模式（方案书 4.4.3 节）
        """
        strict_instruction = ""
        if strict_mode:
            strict_instruction = (
                "\n\n【严格审查模式已触发】该输出内容复杂度较高，"
                "请提高审查标准：\n"
                "1. 每条knowledge_refs必须100%可溯源验证，不可有未验证条目\n"
                "2. 代码必须检查语法正确性、逻辑完整性和边界情况\n"
                "3. 推理链不允许任何跳跃，每步必须有充分依据\n"
                "4. 默认通过阈值从90%提高到95%"
            )

        user_prompt = (
            f"聚焦输出（待审查）：\n{focused.model_dump_json(indent=2)}\n\n"
            f"学情画像：\n{profile.model_dump_json(indent=2)}"
            f"{strict_instruction}"
        )

        raw = await judge.generate(user_prompt, tier=ModelTier.HIGH, temperature=0.0)
        data = await judge.parse_json_safe(raw)
        if data is None:
            data = {"verdict": "failed", "confidence": 0.3, "issues": []}

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
        question: str,
        winning_candidate: Optional[CandidateOutput],
        losing_candidate: Optional[CandidateOutput],
        losing_agent: Optional[DomainAgent],
        winning_agent: Optional[DomainAgent],
    ) -> tuple[Verdict, DissentResolution]:
        """分歧解决（DISSENT_RESOLVE状态）

        对应方案书 4.4.2 节完整版：
          第一层：裁判团分歧解决
            少数方举证 → 多数方回应 → 僵持裁判长裁决
          第二层：候选Agent辩论（与第一层协同）
            落选候选质疑 + 获胜候选辩护 → 辩论证据合并
        """
        # 找出少数方和多数方
        minority = next(j for j in judges if j.judgment == "fail")
        majority = [j for j in judges if j.judgment == "pass"]

        # === 第一层第一步：少数方举证（已有） ===
        minority_evidence = minority.evidence

        # === 第一层第二步：多数方回应（新增） ===
        # 多数方看到少数方证据后，必须回应：接受或反驳
        majority_response_str, majority_reasoning = await self._majority_response(
            minority_evidence, focused
        )

        # 根据多数方回应判断
        if majority_response_str == "accepted":
            # 多数方接受质疑 → 退回修改
            verdict = Verdict.REVISE
        else:
            # 多数方反驳 → 僵持 → 裁判长裁决（新增）
            verdict = await self._chief_judge_arbitrate(
                minority_evidence, majority_reasoning, focused
            )

        # === 第二层：候选Agent辩论（与第一层协同） ===
        candidate_debate = None
        if losing_agent and winning_agent and losing_candidate and winning_candidate:
            # 落选候选质疑
            challenge_evidence = await losing_agent.debate_challenge(
                question=question,
                winning_output=focused,
                minority_opinion="; ".join(minority_evidence),
            )

            # 获胜候选辩护
            defense_evidence = await winning_agent.debate_defense(
                question=question,
                original_output=winning_candidate,
                challenge_evidence=challenge_evidence,
            )

            candidate_debate = CandidateDebate(
                challenging_agent=losing_candidate.agent_id,
                challenge_evidence=challenge_evidence,
                defending_agent=winning_candidate.agent_id,
                defense_evidence=defense_evidence,
            )

            # 辩论证据可能改变裁决（MaW→C转化路径）
            # 如果裁判长说通过，但候选辩论揭示了实质问题 → 改为REVISE
            if verdict == Verdict.PASSED and len(challenge_evidence) > 0:
                logger.info("候选辩论揭示新问题，改判为REVISE")
                verdict = Verdict.REVISE
                majority_response_str = "accepted_after_debate"

        logger.info(
            f"分歧解决完成: verdict={verdict}, "
            f"majority_response={majority_response_str}, "
            f"evidence_count={len(minority_evidence)}"
        )

        return verdict, DissentResolution(
            minority_judge=minority.role,
            evidence_submitted=minority_evidence,
            majority_response=majority_response_str,
            candidate_debate=candidate_debate,
        )

    async def _majority_response(
        self,
        minority_evidence: list[str],
        focused: FocusedOutput,
    ) -> tuple[str, list[str]]:
        """多数方回应：看到少数方证据后判断接受或反驳

        对应方案书 4.4.2 节：多数方（2人）必须回应

        Returns:
            (response: "accepted"/"rejected", reasoning: 多数方理由)
        """
        user_prompt = (
            f"你是裁判团多数方（2名裁判认为通过）。少数方裁判提交了以下质疑证据：\n"
            f"{'; '.join(minority_evidence)}\n\n"
            f"被审查的输出：\n{focused.model_dump_json(indent=2)}\n\n"
            f"请评估少数方的质疑是否成立。\n"
            f"- 如果质疑确实揭示了实质问题（事实错误/逻辑缺陷/不适配）→ 接受(accepted)\n"
            f"- 如果质疑不成立或只是小问题 → 反驳(rejected)\n"
            f"输出JSON: {{\"response\": \"accepted\"或\"rejected\", "
            f"\"reasoning\": [\"理由1\", \"理由2\"]}}"
        )

        raw = await self.judge_logic.generate(
            user_prompt, tier=ModelTier.HIGH, temperature=0.0
        )
        data = await self.judge_logic.parse_json_safe(raw)
        if data is None:
            data = {"response": "rejected", "reasoning": ["JSON解析失败，默认反驳"]}
        response = data.get("response", "rejected")
        reasoning = [_safe_str(r) for r in data.get("reasoning", [])]

        logger.info(f"多数方回应: {response}, reasoning={reasoning}")
        return response, reasoning

    async def _chief_judge_arbitrate(
        self,
        minority_evidence: list[str],
        majority_reasoning: list[str],
        focused: FocusedOutput,
    ) -> Verdict:
        """裁判长（裁判1-事实审查）最终裁决

        对应方案书 4.4.2 节：双方僵持时裁判长裁决，事实准确性优先级最高
        """
        user_prompt = (
            f"你是裁判长（事实审查裁判）。裁判团出现分歧：\n\n"
            f"少数方质疑：{'; '.join(minority_evidence)}\n"
            f"多数方反驳：{'; '.join(majority_reasoning)}\n\n"
            f"被审查的输出：\n{focused.model_dump_json(indent=2)}\n\n"
            f"作为裁判长，请做最终裁决（事实准确性优先级最高）：\n"
            f"- 事实准确且逻辑完整 → passed\n"
            f"- 有可修正的问题 → revise\n"
            f"- 有严重事实错误 → failed\n"
            f"输出JSON: {{\"verdict\": \"passed\"或\"revise\"或\"failed\", "
            f"\"reasoning\": \"裁决理由\"}}"
        )

        raw = await self.judge_fact.generate(
            user_prompt, tier=ModelTier.HIGH, temperature=0.0
        )
        data = await self.judge_fact.parse_json_safe(raw)
        if data is None:
            data = {"verdict": "passed", "reasoning": "JSON解析失败，默认通过"}
        raw_verdict = data.get("verdict", "passed")

        verdict_map = {
            "passed": Verdict.PASSED,
            "revise": Verdict.REVISE,
            "failed": Verdict.FAILED,
        }
        verdict = verdict_map.get(raw_verdict, Verdict.PASSED)

        logger.info(f"裁判长裁决: {verdict}, reasoning={data.get('reasoning', '')}")
        return verdict

    async def _final_review_on_unanimous_fail(
        self,
        focused: FocusedOutput,
        profile: StudentProfile,
        judges: list[JudgeOpinion],
    ) -> tuple[Verdict, Optional[str]]:
        """全票失败终审（方案书4.4.2延伸：0:3状态机未定义的补充处理）

        3名裁判全部不通过时，裁判长做最后一次评估：
        内容是否达到"最低可接受标准"（不至于完全不能提供给学生）。

        设计意图（用户要求）：
          全票失败可以放行，但这种情况必须特别少。
          终审门控确保大部分0:3被挽救（改判），只有终审也确认
          不行的才强制放行 → 真正的强制放行极少。

        Returns:
            (verdict, override_reason)
            - 终审通过 → (LOW_CONFIDENCE_PASSED, None) 挽救成功，正常降级
            - 终审不通过 → (LOW_CONFIDENCE_PASSED, "unanimous_fail_force_pass")
                          仍放行（用户要求），但标记强制放行
        """
        issues_summary = "; ".join(
            f"[{j.role}] {'; '.join(j.evidence)}" for j in judges if j.evidence
        )
        if not issues_summary:
            issues_summary = "（裁判未提供具体证据）"

        user_prompt = (
            f"你是裁判长。3名裁判全部投了不通过（0:3全票失败）。\n\n"
            f"各裁判的问题证据：\n{issues_summary}\n\n"
            f"被审查的输出：\n{focused.model_dump_json(indent=2)}\n\n"
            f"学情画像：\n{profile.model_dump_json(indent=2)}\n\n"
            f"请做最终评估：虽然3名裁判都不通过，这份输出是否达到了"
            f"最低可接受标准（即不至于完全不能提供给学生）？\n"
            f"- 达到最低标准（问题可接受/裁判过于严格）→ pass\n"
            f"- 未达到最低标准（有严重事实错误/严重不适配）→ fail\n"
            f"输出JSON: {{\"final_verdict\": \"pass\"或\"fail\", "
            f"\"reasoning\": \"裁决理由\"}}"
        )

        raw = await self.judge_fact.generate(
            user_prompt, tier=ModelTier.HIGH, temperature=0.0
        )
        data = await self.judge_fact.parse_json_safe(raw)
        if data is None:
            data = {"final_verdict": "fail", "reasoning": "JSON解析失败，默认不通过"}

        final_verdict = data.get("final_verdict", "fail")
        reasoning = data.get("reasoning", "")

        if final_verdict == "pass":
            logger.info(
                f"全票失败终审挽救: 裁判长认为达到最低标准, "
                f"reasoning={reasoning}"
            )
            return Verdict.LOW_CONFIDENCE_PASSED, None
        else:
            logger.error(
                f"⚠️ 全票失败强制放行: 裁判长终审仍不通过, "
                f"输出质量不达标但按策略放行, reasoning={reasoning}"
            )
            return Verdict.LOW_CONFIDENCE_PASSED, "unanimous_fail_force_pass"

    @staticmethod
    def _extract_factual_statements(focused: FocusedOutput) -> list[dict]:
        """从聚焦输出中提取需要溯源的关键事实声明

        除了 knowledge_refs 中的显式引用外，conclusion 和
        reasoning_steps 中也可能包含事实性声明，一并纳入溯源计算。

        每条声明包含：
          - source: 来源标识（knowledge_ref / conclusion / reasoning_step N）
          - statement: 实际要验证的文本
        """
        statements: list[dict] = []
        seen: set[str] = set()

        # 1. knowledge_refs 中的显式引用
        for ref in focused.knowledge_refs:
            stmt = ref.content_summary.strip()
            if stmt and stmt not in seen:
                seen.add(stmt)
                statements.append({
                    "source": ref.source,
                    "statement": stmt,
                    "category": "knowledge_ref",
                })

        # 2. conclusion 中的事实声明
        if focused.conclusion:
            stmt = focused.conclusion.strip()
            if stmt and stmt not in seen:
                seen.add(stmt)
                statements.append({
                    "source": "conclusion",
                    "statement": stmt,
                    "category": "conclusion",
                })

        # 3. reasoning_steps 中的关键事实声明
        for i, step in enumerate(focused.reasoning_steps, start=1):
            stmt = step.strip()
            if stmt and stmt not in seen:
                seen.add(stmt)
                statements.append({
                    "source": f"reasoning_step_{i}",
                    "statement": stmt,
                    "category": "reasoning_step",
                })

        return statements

    async def _annotate_traceability(
        self, focused: FocusedOutput
    ) -> list[TraceabilityItem]:
        """高保真知识溯源标注

        对应方案书 4.4.4 节：综合对 knowledge_refs + conclusion +
        reasoning_steps 中的关键事实声明做溯源，按"已溯源条数 / 总声明数"
        计算 verification_rate。
        这样讲义多步推理不再只溯源 1 条。
        """
        statements = self._extract_factual_statements(focused)
        if not statements:
            return []

        items: list[TraceabilityItem] = []
        for entry in statements:
            result = await self.judge_fact._kb.verify_statement(entry["statement"])

            status_map = {
                "已验证": VerificationStatus.VERIFIED,
                "矛盾": VerificationStatus.CONTRADICTED,
                "待验证": VerificationStatus.UNVERIFIED,
            }
            status = status_map.get(
                result.get("status", "待验证"), VerificationStatus.UNVERIFIED
            )

            items.append(TraceabilityItem(
                statement=entry["statement"][:200],
                source=result.get("source", entry["source"]),
                verification_status=status,
            ))

        logger.debug(
            f"[JudgePanel] 溯源标注: {len(statements)} 条声明"
            f"(knowledge_refs={len(focused.knowledge_refs)}, "
            f"conclusion=1, reasoning_steps={len(focused.reasoning_steps)}), "
            f"已验证={sum(1 for i in items if i.verification_status==VerificationStatus.VERIFIED)}"
        )
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
        data = await self.judge_fact.parse_json_safe(raw)
        return data if data else {"has_error": False, "error_detail": "", "corrected_content": ""}

"""领域知识生成Agent - 模块二

对应方案书第三部分：
  3.2 Agent池构成（10个领域Agent）
  3.3 每个领域Agent的System Prompt框架
  3.4 候选输出机制（含self_confidence自评估）
  3.5 聚焦输出（含审核反馈回流，MAR落地）
"""

from typing import Optional

from loguru import logger

from backend.agents.base_agent import BaseAgent
from backend.agents.agent_registry import get_agent_card
from backend.agents.review_team import _safe_str
from backend.schemas.candidate_output import (
    CandidateOutput,
    FocusedOutputBody,
    SelfConfidence,
)
from backend.schemas.focused_output import FocusedOutput
from backend.schemas.review_feedback import ReviewFeedback
from backend.schemas.student_profile import StudentProfile
from backend.services.llm_client import ModelTier


class DomainAgent(BaseAgent):
    """领域知识生成Agent

    10个领域Agent是同一LLM的不同Prompt角色实例。
    差异来自System Prompt而非模型本身（MetaGPT范式）。

    每个Agent有：
    - 主功能（primary_function）：最擅长
    - 副功能（secondary_functions）：也能回答但不保证最精确
    - domain_tags：领域标签，用于调度员匹配
    """

    def __init__(self, agent_id: str, **kwargs):
        card = get_agent_card(agent_id)
        if not card:
            raise ValueError(f"未知的Agent ID: {agent_id}")

        super().__init__(
            agent_id=agent_id,
            agent_name=card["agent_name"],
            **kwargs,
        )
        self._card = card

    @property
    def primary_function(self) -> str:
        return self._card["primary_function"]

    @property
    def secondary_functions(self) -> list[str]:
        return self._card["secondary_functions"]

    @property
    def domain_tags(self) -> list[str]:
        return self._card["domain_tags"]

    @property
    def system_prompt(self) -> str:
        """对应方案书 3.3 节 System Prompt框架"""
        return (
            f"你是一个专注于{self.primary_function}的AI技能培训助手。\n\n"
            f"【你的核心职责】\n"
            f"- 主功能：{self.primary_function}（你必须最擅长这个方向）\n"
            f"- 覆盖方向：{', '.join(self.secondary_functions)}\n"
            f"- 你面对任何问题都会输出答案，但在{self.primary_function}方向上你的答案最精确\n\n"
            f"【你必须遵守的约束】\n"
            f"1. 所有知识点必须有知识库依据，无法确认的依据请标注'待验证'\n"
            f"2. 输出必须适配学生的知识水平（由学情画像动态填入）\n"
            f"3. 你必须明确指出你所擅长的功能方向\n"
            f"4. 输出时必须附带self_confidence字段，诚实评估信心\n\n"
            f"【输出格式】\n"
            f"输出JSON，包含answer和self_confidence字段。"
        )

    # ============================================================
    # 3.4 候选输出
    # ============================================================

    async def generate_candidate(
        self,
        question: str,
        profile: StudentProfile,
        seg_id: str,
    ) -> CandidateOutput:
        """候选输出：生成答案 + self_confidence自评估

        对应方案书 3.4.4 节：
          self_confidence在同一轮LLM调用中完成，不额外增加调用次数。
          如果问题涉及secondary_functions，confidence应≤0.7。
        """
        user_prompt = (
            f"学生问题：{question}\n"
            f"学情画像：{profile.model_dump_json(indent=2)}\n\n"
            f"请输出JSON，包含以下字段：\n"
            f"{{\n"
            f'  "agent_id": "{self.agent_id}",\n'
            f'  "seg_id": "{seg_id}",\n'
            f'  "answer": {{\n'
            f'    "conclusion": "核心结论",\n'
            f'    "reasoning_steps": ["步骤1", "步骤2", "步骤3"],\n'
            f'    "knowledge_refs": [{{"source": "来源", "content_summary": "摘要"}}],\n'
            f'    "applicable_conditions": "适用条件",\n'
            f'    "code_example": "可选代码示例",\n'
            f'    "difficulty_note": "难度说明"\n'
            f'  }},\n'
            f'  "self_confidence": {{\n'
            f'    "score": 0.0-1.0,\n'
            f'    "weak_points": ["不确定的地方"]\n'
            f'  }}\n'
            f"}}"
        )

        result = await self.generate_and_validate(
            user_prompt=user_prompt,
            model_class=CandidateOutput,
            tier=ModelTier.MID,
            temperature=0.7,
        )

        logger.info(
            f"候选输出: {self.agent_id} seg={seg_id}, "
            f"confidence={result.self_confidence.score}"
        )
        return result

    # ============================================================
    # 3.5 聚焦输出（含审核反馈回流，MAR落地）
    # ============================================================

    async def generate_focused_output(
        self,
        question: str,
        profile: StudentProfile,
        original_output: CandidateOutput,
        review_feedback: Optional[ReviewFeedback] = None,
    ) -> FocusedOutput:
        """聚焦输出：最优Agent收到审核反馈后反思改进

        对应方案书 3.5 节：
          - 不是重新生成，而是在原有会话中继续
          - 审核团队只传"具体问题"给Agent，不传评分数字
          - 如果审核团队没有发现问题（3人全高分），走原始流程
        """
        # 构造审核反馈描述（只传具体问题，不传评分）
        feedback_str = "无（审核团队未发现明显问题）"
        if review_feedback:
            # 找到本Agent的审核结果
            for candidate in review_feedback.candidates:
                if candidate.agent_id == self.agent_id and candidate.is_winner:
                    issues = candidate.issues_found
                    if issues:
                        feedback_str = "\n".join(
                            f"  {issue.reviewer}反馈：{issue.description}"
                            for issue in issues
                        )
                    break

        user_prompt = (
            f"【系统通知】\n"
            f"你在段内评选中获胜。以下是审核团队对你输出的具体反馈，请针对改进。\n\n"
            f"你的原始输出：\n{original_output.answer.model_dump_json(indent=2)}\n\n"
            f"审核反馈（具体问题，不含评分）：\n{feedback_str}\n\n"
            f"请按以下要求改进：\n"
            f"1. 针对审核反馈中的每个问题进行修正\n"
            f"2. 确认conclusion是否准确（1-2句话）\n"
            f"3. 补充reasoning_steps中缺失的步骤（至少3步）\n"
            f"4. 为每条知识点添加knowledge_refs\n"
            f"5. 明确applicable_conditions\n"
            f"6. 如有代码操作，提供code_example\n"
            f"7. 根据学生水平添加difficulty_note\n\n"
            f"学生问题：{question}\n"
            f"学情画像：{profile.model_dump_json(indent=2)}\n\n"
            f"【重要】请严格按以下JSON格式输出，字段在顶层，不要包在answer里：\n"
            f"{{\n"
            f'  "conclusion": "核心结论，1-2句话",\n'
            f'  "reasoning_steps": ["步骤1：...", "步骤2：...", "步骤3：..."],\n'
            f'  "knowledge_refs": [{{"source": "来源文档名+章节", "content_summary": "引用内容摘要"}}],\n'
            f'  "applicable_conditions": "适用场景、不适用场景、前置知识要求",\n'
            f'  "code_example": "可选，可执行代码示例",\n'
            f'  "difficulty_note": "针对学生水平的难度说明"\n'
            f"}}"
        )

        result = await self.generate_and_validate(
            user_prompt=user_prompt,
            model_class=FocusedOutput,
            tier=ModelTier.HIGH,  # 聚焦输出用高档模型
            temperature=0.3,
            max_tokens=2048,
        )

        logger.info(f"聚焦输出完成: {self.agent_id}")
        return result

    # ============================================================
    # 候选Agent辩论（Debate论文落地）
    # ============================================================

    async def debate_challenge(
        self,
        question: str,
        winning_output: FocusedOutput,
        minority_opinion: str,
    ) -> list[str]:
        """落选候选Agent质疑获胜方输出

        对应方案书 4.4.2 节候选Agent辩论：
          落选候选收到anonymized质疑 → 认同提交补充证据 / 不认同提交反驳证据
        """
        user_prompt = (
            f"你是落选候选Agent。裁判团少数方提出了以下质疑：\n"
            f"质疑内容：{minority_opinion}\n\n"
            f"获胜候选的输出：\n{winning_output.model_dump_json(indent=2)}\n\n"
            f"请评估该质疑是否合理，并提交你的证据（认同或反驳）。"
            f"输出JSON: {{\"evidence\": [\"证据1\", \"证据2\"]}}"
        )

        raw = await self.generate(user_prompt, tier=ModelTier.MID, temperature=0.5)

        import json
        try:
            data = json.loads(raw)
            return [_safe_str(item) for item in data.get("evidence", [])]
        except json.JSONDecodeError:
            return [raw.strip()]

    async def debate_defense(
        self,
        question: str,
        original_output: CandidateOutput,
        challenge_evidence: list[str],
    ) -> list[str]:
        """获胜候选Agent辩护

        对应方案书 4.4.2 节：获胜候选必须提交辩护证据
        """
        user_prompt = (
            f"你是获胜候选Agent。落选候选和裁判少数方提出了以下质疑和证据：\n"
            f"质疑证据：{chr(10).join(challenge_evidence)}\n\n"
            f"你的原始输出：\n{original_output.answer.model_dump_json(indent=2)}\n\n"
            f"请提交你的辩护证据。"
            f"输出JSON: {{\"evidence\": [\"辩护证据1\", \"辩护证据2\"]}}"
        )

        raw = await self.generate(user_prompt, tier=ModelTier.MID, temperature=0.5)

        import json
        try:
            data = json.loads(raw)
            return [_safe_str(item) for item in data.get("evidence", [])]
        except json.JSONDecodeError:
            return [raw.strip()]

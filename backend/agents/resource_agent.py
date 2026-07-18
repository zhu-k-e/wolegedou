"""资源生成Agent - 模块二（第11个Agent）

对应方案书 3.6 节：
  3.6.1 触发时机与条件判断
  3.6.2 三种形态详细设计（讲义/实操指南/分阶测试题）
  3.6.4 降维解释与进阶挑战动态追加
"""

import json
from typing import Optional

from loguru import logger

from backend.agents.base_agent import BaseAgent
from backend.schemas.focused_output import FocusedOutput
from backend.schemas.resource_package import (
    ResourcePackage,
    Lecture,
    PracticeGuide,
    Quiz,
    QuizQuestion,
)
from backend.schemas.student_profile import StudentProfile, QuestionType
from backend.services.llm_client import ModelTier


class ResourceAgent(BaseAgent):
    """资源生成Agent

    不参与领域内容生成，只在裁判团通过之后做格式转换。
    按条件触发3种形态：
      - 讲义：必选（始终生成）
      - 实操指南：条件触发（FocusedOutput含code_example字段）
      - 分阶测试题：条件触发（question_type∈{概念理解,操作步骤,架构设计}）
    """

    def __init__(self, **kwargs):
        super().__init__(
            agent_id="agent_011",
            agent_name="资源生成Agent",
            **kwargs,
        )

    @property
    def system_prompt(self) -> str:
        return (
            "你是一个资源生成助手。你的任务是将已通过审核的知识内容"
            "转换为适合学生学习的个性化资源（讲义/实操指南/测试题）。\n"
            "所有输出必须为JSON格式。"
        )

    async def generate_resource_package(
        self,
        task_id: str,
        focused_output: FocusedOutput,
        profile: StudentProfile,
    ) -> ResourcePackage:
        """生成完整资源包

        对应方案书 3.6.3 节生成顺序：
          第1步：定制化讲义（必选）
          第2步：实操指南（条件触发）
          第3步：分阶测试题（条件触发）
        """
        # 第1步：讲义（必选）
        lecture = await self._generate_lecture(focused_output, profile)

        # 第2步：实操指南（条件触发：含code_example字段）
        practice_guide = None
        if focused_output.code_example:
            practice_guide = await self._generate_practice_guide(focused_output, profile)

        # 第3步：分阶测试题（条件触发：question_type∈{概念理解,操作步骤,架构设计}）
        quiz = None
        quiz_trigger_types = {
            QuestionType.CONCEPT, QuestionType.OPERATION, QuestionType.ARCHITECTURE
        }
        if profile.question_type in quiz_trigger_types:
            quiz = await self._generate_quiz(focused_output, profile)

        package = ResourcePackage(
            task_id=task_id,
            lecture=lecture,
            practice_guide=practice_guide,
            quiz=quiz,
            focused_output_ref=task_id,
            profile_ref=profile.session_id or "",
        )

        logger.info(
            f"资源包生成完成: task={task_id}, "
            f"lecture=✓, practice={'✓' if practice_guide else '✗'}, quiz={'✓' if quiz else '✗'}"
        )
        return package

    async def _generate_lecture(
        self, focused: FocusedOutput, profile: StudentProfile
    ) -> Lecture:
        """生成定制化讲义"""
        user_prompt = (
            f"请将以下知识内容转换为Markdown格式的讲义。\n"
            f"学生知识水平：{profile.knowledge_level}\n"
            f"学生背景：{profile.background}\n\n"
            f"知识内容：\n{focused.model_dump_json(indent=2)}\n\n"
            f"个性化适配要求：\n"
            f"- 入门水平：每步后加'通俗理解'段落\n"
            f"- 中级水平：保留专业术语，加简要解释\n"
            f"- 进阶水平：增加'底层原理'扩展段落\n\n"
            f"输出JSON: {{\"title\": \"标题\", \"content_markdown\": \"讲义内容\", "
            f"\"difficulty_note\": \"难度说明\"}}"
        )

        raw = await self.generate(user_prompt, tier=ModelTier.MID, temperature=0.5)
        data = json.loads(raw)

        return Lecture(
            title=data.get("title", "学习讲义"),
            content_markdown=data.get("content_markdown", ""),
            difficulty_note=data.get("difficulty_note", ""),
            knowledge_refs_display=[
                {"source": ref.source, "verification_status": "待验证"}
                for ref in focused.knowledge_refs
            ],
        )

    async def _generate_practice_guide(
        self, focused: FocusedOutput, profile: StudentProfile
    ) -> PracticeGuide:
        """生成实操指南"""
        user_prompt = (
            f"请生成实操指南。\n"
            f"学生背景：{profile.background}\n"
            f"知识内容：\n{focused.model_dump_json(indent=2)}\n\n"
            f"个性化适配：\n"
            f"- 无编程背景：增加环境安装详细步骤\n"
            f"- 有Python基础：跳过基础环境配置\n"
            f"- 有ML基础：增加参数调优说明\n\n"
            f"输出JSON: {{\"goal\": \"目标\", \"env_setup\": \"环境准备\", "
            f"\"steps_markdown\": \"操作步骤\", \"common_issues\": [\"问题1\"]}}"
        )

        raw = await self.generate(user_prompt, tier=ModelTier.MID, temperature=0.5)
        data = json.loads(raw)

        return PracticeGuide(
            goal=data.get("goal", ""),
            env_setup=data.get("env_setup", ""),
            steps_markdown=data.get("steps_markdown", ""),
            common_issues=data.get("common_issues", []),
        )

    async def _generate_quiz(
        self, focused: FocusedOutput, profile: StudentProfile
    ) -> Quiz:
        """生成分阶测试题"""
        user_prompt = (
            f"请生成3-5道分阶测试题。\n"
            f"学生知识水平：{profile.knowledge_level}\n"
            f"知识内容：\n{focused.model_dump_json(indent=2)}\n\n"
            f"难度阶梯：\n"
            f"- 第1题：基础巩固（对应reasoning_steps某一步）\n"
            f"- 第2题：跨步骤综合（应用能力）\n"
            f"- 第3题及以上：加入干扰项或边界条件（进阶挑战）\n\n"
            f"题型（根据knowledge_level）：\n"
            f"- 入门 → 判断题+选择题\n"
            f"- 中级 → 选择题+简答提示题\n"
            f"- 进阶 → 代码补全题+设计分析题\n\n"
            f"输出JSON: {{\"questions\": [{{\"question\": \"题目\", \"type\": \"选择\", "
            f"\"options\": [\"A\",\"B\"], \"answer\": \"答案\", \"explanation\": \"解析\", "
            f"\"difficulty\": \"基础\"}}]}}\n"
            f"【重要】difficulty 只能是以下之一：基础、应用、综合、进阶\n"
            f"【重要】type 只能是以下之一：判断、选择、简答、代码补全、设计分析"
        )

        raw = await self.generate(user_prompt, tier=ModelTier.MID, temperature=0.7)
        data = json.loads(raw)

        questions = [QuizQuestion(**q) for q in data.get("questions", [])]
        return Quiz(questions=questions)

    # ============================================================
    # 3.6.4 降维解释与进阶挑战
    # ============================================================

    async def generate_dimension_reduction(
        self,
        focused: FocusedOutput,
        profile: StudentProfile,
        accuracy: float,
    ) -> Lecture:
        """降维解释：当答题正确率低时重新生成

        对应方案书 3.6.4 节降维Prompt模板
        """
        level_str = profile.knowledge_level.value
        if level_str == "入门":
            strategy = "每步推理加生活类比，删除未解释的专业术语，将5步推理拆为8小步，代码示例加逐行注释"
        elif level_str == "中级":
            strategy = "加过渡概念解释段落，补'前置知识回顾'段落，复杂推理链拆为子步骤，每2步加验证节点"
        else:
            strategy = "复杂多步推理拆为子问题链，每步独立可验证，加中间验证节点，补充推导细节"

        user_prompt = (
            f"学生答题正确率为{accuracy:.0%}，需要降维解释。\n"
            f"降维策略：{strategy}\n\n"
            f"原始知识内容：\n{focused.model_dump_json(indent=2)}\n\n"
            f"请用降维策略重新生成讲义。"
            f"输出JSON: {{\"title\": \"标题\", \"content_markdown\": \"降维讲义\", "
            f"\"difficulty_note\": \"降维版\"}}"
        )

        raw = await self.generate(user_prompt, tier=ModelTier.MID, temperature=0.5)
        data = json.loads(raw)

        return Lecture(
            title=data.get("title", "降维讲义"),
            content_markdown=data.get("content_markdown", ""),
            difficulty_note="降维版 - " + data.get("difficulty_note", ""),
        )

    async def generate_advance_challenge(
        self,
        focused: FocusedOutput,
        profile: StudentProfile,
    ) -> QuizQuestion:
        """进阶挑战：当答题正确率≥85%时追加1道进阶题

        对应方案书 3.6.4 节进阶挑战追加规则
        """
        user_prompt = (
            f"学生答题正确率≥85%，请追加1道进阶挑战题。\n"
            f"知识内容：\n{focused.model_dump_json(indent=2)}\n\n"
            f"进阶策略：\n"
            f"- 题目难度从'应用'级升至'分析/设计'级\n"
            f"- 跨知识点联动\n"
            f"- 开放性增加\n\n"
            f"输出JSON: {{\"question\": \"题目\", \"type\": \"设计分析\", "
            f"\"answer\": \"答案\", \"explanation\": \"解析\", \"difficulty\": \"进阶\"}}"
        )

        raw = await self.generate(user_prompt, tier=ModelTier.MID, temperature=0.7)
        data = json.loads(raw)

        return QuizQuestion(**data)

"""资源生成Agent - 模块二（第11个Agent）

对应方案书 3.6 节：
  3.6.1 触发时机与条件判断
  3.6.2 三种形态详细设计（讲义/实操指南/分阶测试题）
  3.6.4 降维解释与进阶挑战动态追加
"""

from typing import Optional

from loguru import logger

from backend.agents.base_agent import BaseAgent
from backend.schemas.candidate_output import KnowledgeRef
from backend.schemas.focused_output import FocusedOutput
from backend.schemas.resource_package import (
    ResourcePackage,
    Lecture,
    PracticeGuide,
    Quiz,
    QuizQuestion,
    KnowledgeRefDisplay,
)
from backend.schemas.student_profile import StudentProfile
from backend.services.llm_client import ModelTier
from backend.services.code_checker import check_code_in_markdown


class ResourceAgent(BaseAgent):
    """资源生成Agent

    不参与领域内容生成，只在裁判团通过之后做格式转换。
    3种形态生成逻辑（已放宽触发条件，详见各方法注释）：
      - 讲义：必选（始终生成）
      - 实操指南：始终生成（含代码→代码实操步骤；无代码→决策检查清单/应用步骤）
      - 分阶测试题：始终生成（根据question_type自适应题型）

    知识引用溯源（对应方案书 6.6 节）：
      生成讲义后调 KB verify_statement 获取真实核查结果，
      回填 verification_status（已验证/待验证/矛盾）和 source（知识库 chunk 来源）。
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

        代码安全检查（方案书§3.5.1）：
          生成资源前对 code_example 做 ast 语法检查 + 危险操作检测
        """
        # === 代码安全检查（方案书§3.5.1） ===
        # 检查“实际展示给学生看的代码”：讲义和实操指南都是独立 LLM 生成的，
        # 不一定引用 FocusedOutput.code_example，因此改为检查生成后的正文中的代码块，
        # 而非生成阶段那份 code_example（避免讲义没展示代码却冒出语法错误警告）。

        # 第1步：讲义（必选）
        lecture = await self._generate_lecture(focused_output, profile)

        # 检查讲义正文中实际包含的代码块
        lecture_warning = check_code_in_markdown(lecture.content_markdown)
        if lecture_warning:
            logger.warning(
                f"讲义代码块安全检查未通过: task={task_id}, warning={lecture_warning}"
            )
            lecture.content_markdown += (
                f"\n\n> ⚠️ **代码安全检查警告**：检测到以下问题：{lecture_warning}。"
                f"请仔细检查代码示例后再使用。"
            )

        # 第2步：实操指南（始终生成，根据有无代码自适应内容形态）
        # 方案书3.6.2原为"含code_example时触发"，但概念类问题也需要操作指引
        # （决策清单/评估步骤/应用检查表），故放宽为始终生成，由prompt自适应
        practice_guide = await self._generate_practice_guide(focused_output, profile)

        # 检查实操指南步骤中实际包含的代码块
        practice_warning = check_code_in_markdown(practice_guide.steps_markdown)
        if practice_warning:
            logger.warning(
                f"实操指南代码块安全检查未通过: task={task_id}, warning={practice_warning}"
            )
            practice_guide.steps_markdown += (
                f"\n\n> ⚠️ **代码安全检查警告**：{practice_warning}。"
                f"请仔细检查代码后再使用。"
            )

        # 第3步：分阶测试题（始终生成）
        # 方案书3.6.2原触发类型为{概念理解,操作步骤,架构设计}，
        # 但调试排错和全链路规划同样需要测试题（找错题/综合分析题），故放宽为始终生成
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

    async def _build_knowledge_refs_display(
        self,
        knowledge_refs: list[KnowledgeRef],
    ) -> list[KnowledgeRefDisplay]:
        """构建知识引用展示，调 KB verify_statement 获取真实核查结果

        用 content_summary 作为 statement 去核查（它是实际的知识陈述），
        回填真实的 verification_status（已验证/待验证/矛盾）和 source（知识库 chunk 来源）。

        对应方案书 6.6 节裁判团溯源标注：展示给学生的引用必须可溯源。
        KB 不可用或核查异常时降级为"待验证"，不影响主流程。
        """
        display: list[KnowledgeRefDisplay] = []
        for ref in knowledge_refs:
            try:
                # 用 content_summary 作为核查陈述（source 可能是 LLM 编造的文档名）
                statement = ref.content_summary or ref.source
                verify_result = await self._kb.verify_statement(
                    statement=statement, top_k=3
                )
                display.append(KnowledgeRefDisplay(
                    source=verify_result.get("source") or ref.source,
                    verification_status=verify_result.get("status", "待验证"),
                ))
            except Exception as e:
                logger.warning(
                    f"resource_agent verify_statement 失败: {e}，使用默认值"
                )
                display.append(KnowledgeRefDisplay(
                    source=ref.source,
                    verification_status="待验证",
                ))
        return display

    async def _generate_lecture(
        self, focused: FocusedOutput, profile: StudentProfile
    ) -> Lecture:
        """生成定制化讲义"""
        user_prompt = (
            f"请将以下知识内容转换为Markdown格式的讲义。\n"
            f"学生知识水平：{profile.knowledge_level}\n"
            f"学生背景：{profile.background}\n"
            f"学生目标：{profile.current_goal}\n\n"
            f"知识内容：\n{focused.model_dump_json(indent=2)}\n\n"
            f"个性化适配要求（必须严格遵守）：\n"
            f"- 按知识水平适配深度：\n"
            f"  · 入门水平：每步后加'通俗理解'段落\n"
            f"  · 中级水平：保留专业术语，加简要解释\n"
            f"  · 进阶水平：增加'底层原理'扩展段落\n"
            f"- 按背景适配表达方式（重要，裁判会审查）：\n"
            f"  · 无编程背景（如'理科_无编程'）：优先用概念解释、生活类比、"
            f"流程描述讲清楚，避免直接堆代码；技术名词（如Elasticsearch、"
            f"模型蒸馏）首次出现时给一句话通俗解释；如确需代码，必须配逐行"
            f"中文注释并标注'仅帮助理解，无需手动运行'\n"
            f"  · 有编程基础：可展示代码，但需解释关键步骤\n"
            f"- 按目标适配侧重：\n"
            f"  · 目标为'项目落地'：增加落地难点、选型建议、实施路线图\n\n"
            f"输出JSON: {{\"title\": \"标题\", \"content_markdown\": \"讲义内容\", "
            f"\"difficulty_note\": \"难度说明\"}}"
        )

        result = await self.generate_and_validate(
            user_prompt=user_prompt,
            model_class=Lecture,
            tier=ModelTier.MID,
            temperature=0.5,
        )

        # 补充溯源标注：调 KB verify_statement 获取真实核查结果（非硬编码"待验证"）
        result.knowledge_refs_display = await self._build_knowledge_refs_display(
            focused.knowledge_refs
        )
        return result

    async def _generate_practice_guide(
        self, focused: FocusedOutput, profile: StudentProfile
    ) -> PracticeGuide:
        """生成实操指南"""
        user_prompt = (
            f"请生成实操指南。\n"
            f"学生背景：{profile.background}\n"
            f"学生目标：{profile.current_goal}\n"
            f"知识内容：\n{focused.model_dump_json(indent=2)}\n\n"
            f"个性化适配（必须严格遵守，裁判会审查适用性）：\n"
            f"- 无编程背景（如'理科_无编程'）：以概念应用步骤/决策检查清单/"
            f"落地路线图为主，避免需要编程或运维能力的操作步骤（如Elasticsearch"
            f"部署、模型蒸馏）；如确需展示代码，用伪代码或带详细中文注释的极简"
            f"示例，并标注'仅帮助理解，无需手动运行'\n"
            f"- 有Python基础：可跳过基础环境配置，展示可运行代码\n"
            f"- 有ML基础：增加参数调优说明\n\n"
            f"内容形态自适应（重要）：\n"
            f"- 如果知识内容含 code_example：生成代码实操步骤（环境搭建→运行→验证）\n"
            f"- 如果不含 code_example：生成概念应用步骤/决策检查清单"
            f"（如'如何判断是否需要该技术'的评估步骤、'方案选型决策清单'、"
            f"'落地实施路线图'等可操作的步骤化指引）\n\n"
            f"输出JSON: {{\"goal\": \"目标\", \"env_setup\": \"环境准备或前置条件\", "
            f"\"steps_markdown\": \"操作步骤（Markdown含代码块或检查项）\", "
            f"\"expected_output\": \"预期输出（每步操作应得到的结果）\", "
            f"\"common_issues\": [\"问题1\"]}}"
        )

        result = await self.generate_and_validate(
            user_prompt=user_prompt,
            model_class=PracticeGuide,
            tier=ModelTier.MID,
            temperature=0.5,
        )
        return result

    async def _generate_quiz(
        self, focused: FocusedOutput, profile: StudentProfile
    ) -> Quiz:
        """生成分阶测试题"""
        user_prompt = (
            f"请生成3-5道分阶测试题。\n"
            f"学生知识水平：{profile.knowledge_level}\n"
            f"问题类型：{profile.question_type.value}\n"
            f"知识内容：\n{focused.model_dump_json(indent=2)}\n\n"
            f"难度阶梯：\n"
            f"- 第1题：基础巩固（对应reasoning_steps某一步）\n"
            f"- 第2题：跨步骤综合（应用能力）\n"
            f"- 第3题及以上：加入干扰项或边界条件（进阶挑战）\n\n"
            f"题型（根据question_type自适应，所有水平均适用）：\n"
            f"- 概念理解：重点考查概念辨析（判断+选择+简答）\n"
            f"- 操作步骤：重点考查流程顺序和关键操作（选择+简答）\n"
            f"- 调试排错：重点考查错误识别和修复方案（代码找错+简答）\n"
            f"- 架构设计：重点考查组件选型和架构权衡（设计分析+简答）\n"
            f"- 全链路规划：重点考查端到端方案设计（综合分析+设计分析+简答）\n\n"
            f"【硬性要求】无论学生水平如何，3-5道题中必须至少包含1道"
            f"\"简答\"类型题（让学生用自己的话组织答案，考查真实理解而非猜选项）。\n"
            f"简答题的 options 字段返回空数组[]。\n\n"
            f"输出JSON: {{\"questions\": [{{\"question\": \"题目\", \"type\": \"选择\", "
            f"\"options\": [\"A\",\"B\"], \"answer\": \"答案\", \"explanation\": \"解析\", "
            f"\"difficulty\": \"基础\"}}]}}\n"
            f"【重要】difficulty 只能是以下之一：基础、应用、综合、进阶\n"
            f"【重要】type 只能是以下之一：判断、选择、简答、代码补全、设计分析"
        )

        result = await self.generate_and_validate(
            user_prompt=user_prompt,
            model_class=Quiz,
            tier=ModelTier.MID,
            temperature=0.7,
        )
        return result

    # ============================================================
    # 3.6.4 降维解释与进阶挑战
    # ============================================================

    async def generate_dimension_reduction(
        self,
        focused: FocusedOutput,
        profile: StudentProfile,
        accuracy: float,
        task_id: str = "",
    ) -> ResourcePackage:
        """降维解释：当答题正确率低时重新生成完整资源包

        对应方案书 3.6.4 节降维Prompt模板。
        降维后仍输出三种形态（讲义/实操/测试题），而非仅讲义。
        """
        level_str = profile.knowledge_level.value
        if level_str == "入门":
            strategy = "每步推理加生活类比，删除未解释的专业术语，将5步推理拆为8小步，代码示例加逐行注释"
        elif level_str == "中级":
            strategy = "加过渡概念解释段落，补'前置知识回顾'段落，复杂推理链拆为子步骤，每2步加验证节点"
        else:
            strategy = "复杂多步推理拆为子问题链，每步独立可验证，加中间验证节点，补充推导细节"

        # 降维讲义
        lecture_prompt = (
            f"学生答题正确率为{accuracy:.0%}，需要降维解释。\n"
            f"降维策略：{strategy}\n\n"
            f"原始知识内容：\n{focused.model_dump_json(indent=2)}\n\n"
            f"请用降维策略重新生成讲义。"
            f"输出JSON: {{\"title\": \"标题\", \"content_markdown\": \"降维讲义\", "
            f"\"difficulty_note\": \"降维版\"}}"
        )
        lecture = await self.generate_and_validate(
            user_prompt=lecture_prompt,
            model_class=Lecture,
            tier=ModelTier.MID,
            temperature=0.5,
        )
        lecture.difficulty_note = "降维版 - " + lecture.difficulty_note
        lecture.knowledge_refs_display = await self._build_knowledge_refs_display(
            focused.knowledge_refs
        )

        # 降维实操指南（始终生成，根据有无代码自适应）
        practice_prompt = (
            f"学生答题正确率为{accuracy:.0%}，需要降维实操指南。\n"
            f"降维策略：{strategy}\n\n"
            f"原始知识内容：\n{focused.model_dump_json(indent=2)}\n\n"
            f"请用降维策略重新生成实操指南，每步更详细。\n"
            f"内容形态自适应：含代码则生成代码实操步骤，无代码则生成概念应用步骤/决策检查清单。\n"
            f"输出JSON: {{\"goal\": \"目标\", \"env_setup\": \"环境准备或前置条件\", "
            f"\"steps_markdown\": \"操作步骤\", "
            f"\"expected_output\": \"预期输出\", "
            f"\"common_issues\": [\"问题1\"]}}"
        )
        practice_guide = await self.generate_and_validate(
            user_prompt=practice_prompt,
            model_class=PracticeGuide,
            tier=ModelTier.MID,
            temperature=0.5,
        )

        # 降维测试题（始终生成，降低难度）
        quiz_prompt = (
            f"学生答题正确率为{accuracy:.0%}，需要降维测试题。\n"
            f"降维策略：题目难度全部降一级（进阶→应用→基础），减少干扰项。\n\n"
            f"原始知识内容：\n{focused.model_dump_json(indent=2)}\n\n"
            f"请生成3-5道降维测试题。\n"
            f"【硬性要求】必须至少包含1道\"简答\"类型题"
            f"（让学生用自己的话组织答案，options留空数组[]）。\n\n"
            f"输出JSON: {{\"questions\": [{{\"question\": \"题目\", \"type\": \"选择\", "
            f"\"options\": [\"A\",\"B\"], \"answer\": \"答案\", \"explanation\": \"解析\", "
            f"\"difficulty\": \"基础\"}}]}}\n"
            f"【重要】difficulty 只能是以下之一：基础、应用、综合、进阶\n"
            f"【重要】type 只能是以下之一：判断、选择、简答、代码补全、设计分析"
        )
        quiz = await self.generate_and_validate(
            user_prompt=quiz_prompt,
            model_class=Quiz,
            tier=ModelTier.MID,
            temperature=0.7,
        )

        package = ResourcePackage(
            task_id=task_id,
            lecture=lecture,
            practice_guide=practice_guide,
            quiz=quiz,
            focused_output_ref=task_id,
            profile_ref=profile.session_id or "",
        )

        logger.info(
            f"降维资源包生成完成: task={task_id}, accuracy={accuracy:.0%}, "
            f"lecture=✓, practice={'✓' if practice_guide else '✗'}, quiz={'✓' if quiz else '✗'}"
        )
        return package

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
        data = await self.parse_json_safe(raw)
        if data is None:
            data = {"question": "（解析失败）", "type": "设计分析", "answer": "", "explanation": "", "difficulty": "进阶"}

        return QuizQuestion(**data)

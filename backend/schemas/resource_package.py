"""Stage 6: ResourcePackage - 资源包 (SOP链第6阶段产物)

对应方案书 6.2.5 节 Schema
前端统一消费3种形态的个性化学习资源。

3种形态触发逻辑：
  - lecture: 必选（始终生成）
  - practice_guide: 条件触发（FocusedOutput含code_example字段时生成）
  - quiz: 条件触发（question_type∈{概念理解,操作步骤,架构设计}时生成）
"""

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class QuizType(str, Enum):
    JUDGE = "判断"
    CHOICE = "选择"
    SHORT_ANSWER = "简答"
    CODE_COMPLETION = "代码补全"
    DESIGN_ANALYSIS = "设计分析"


class QuizDifficulty(str, Enum):
    BASIC = "基础"
    APPLICATION = "应用"
    COMPREHENSIVE = "综合"
    ADVANCED = "进阶"


class KnowledgeRefDisplay(BaseModel):
    """展示给学生的溯源标注（简化版）"""
    source: str
    verification_status: str


class Lecture(BaseModel):
    """定制化讲义（必选形态）"""
    title: str = Field(description="针对学生问题的标题")
    content_markdown: str = Field(description="Markdown格式讲义内容")
    difficulty_note: str = Field(description="难度说明（含knowledge_level适配）")
    knowledge_refs_display: list[KnowledgeRefDisplay] = Field(
        default_factory=list,
        description="展示给学生的溯源标注（简化版）",
    )


class PracticeGuide(BaseModel):
    """实操指南（条件触发：FocusedOutput含code_example字段时生成）

    对应方案书 3.6.2 节实操指南设计
    """
    goal: str
    env_setup: str = Field(description="环境准备（根据background字段调整）")
    steps_markdown: str = Field(description="步骤化操作（Markdown含代码块）")
    expected_output: str = Field(
        default="",
        description="预期输出（每步操作应得到的结果，帮助学生自查是否正确）",
    )
    common_issues: list[str] = Field(
        default_factory=list, description="常见问题排查"
    )


class QuizQuestion(BaseModel):
    """单道测试题"""
    question: str
    type: QuizType
    options: list[str] = Field(
        default_factory=list, description="仅选择题有"
    )
    answer: str
    explanation: str = Field(description="解析，引用知识库依据")
    difficulty: QuizDifficulty


class Quiz(BaseModel):
    """分阶测试题（条件触发：question_type∈{概念理解,操作步骤,架构设计}时生成）"""
    questions: list[QuizQuestion] = Field(
        min_length=3, max_length=5,
        description="3-5道题，难度阶梯递进",
    )


class ResourcePackage(BaseModel):
    """资源包 - SOP链 Stage 6 产物

    资源生成Agent最终输出的标准化格式。
    """
    task_id: str = Field(description="任务ID，关联SOP链")
    lecture: Lecture = Field(description="定制化讲义（必选形态）")
    practice_guide: Optional[PracticeGuide] = Field(
        None, description="实操指南（条件触发，未触发时为null）"
    )
    quiz: Optional[Quiz] = Field(
        None, description="分阶测试题（条件触发，未触发时为null）"
    )
    focused_output_ref: str = Field(description="关联的FocusedOutput JSON ID")
    profile_ref: str = Field(description="关联的StudentProfile JSON ID")

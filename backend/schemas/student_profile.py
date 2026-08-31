"""Stage 1: StudentProfile - 学情画像 (SOP链第1阶段产物)

对应方案书 2.2.2 节输出Schema
被 Stage 2/3/4/5/6 订阅（所有下游都需要学情信息）
"""

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class KnowledgeLevel(str, Enum):
    ENTRY = "入门"
    INTERMEDIATE = "中级"
    ADVANCED = "进阶"


class Background(str, Enum):
    LIBERAL_ARTS = "文科"
    SCIENCE_NO_CODE = "理科_无编程"
    PYTHON = "有Python基础"
    ML = "有ML基础"


class CurrentGoal(str, Enum):
    QUICK_START = "快速上手应用"
    DEEP_UNDERSTANDING = "深入理解原理"
    PROJECT_DELIVERY = "项目落地"
    ALGORITHM_RESEARCH = "算法研究"


class QuestionType(str, Enum):
    CONCEPT = "概念理解"
    OPERATION = "操作步骤"
    DEBUGGING = "调试排错"
    ARCHITECTURE = "架构设计"
    FULL_PIPELINE = "全链路规划"


class ComplexityEstimate(str, Enum):
    SINGLE_DOMAIN = "单领域"
    CROSS_DOMAIN = "跨领域"
    FULL_PIPELINE = "全链路"


class IntentType(str, Enum):
    GENERATION = "generation"
    NAVIGATION = "navigation"
    CLARIFICATION = "clarification"


class ConfidenceLevel(str, Enum):
    HIGH = "high"
    LOW = "low"


class TestResult(BaseModel):
    """学生可选拓展字段：理论测试成绩"""
    topic: str
    score: float = Field(ge=0.0, le=1.0, description="该知识点正确率 0-1")
    date: str = Field(description="日期 YYYY-MM-DD")


class StudentProfile(BaseModel):
    """学情画像 - SOP链 Stage 1 产物

    由学情诊断Agent生成/增量更新，是整个系统的调度输入。
    """
    knowledge_level: KnowledgeLevel
    background: Background
    current_goal: CurrentGoal
    question_type: QuestionType
    domain_hint: list[str] = Field(
        default_factory=list,
        description="领域关键词，可从限定枚举值中选择多个",
    )
    complexity_estimate: ComplexityEstimate
    intent_type: IntentType
    domain_confidence: dict[str, ConfidenceLevel] = Field(
        default_factory=dict,
        description="对每个domain_hint的置信度评估",
    )
    test_results: list[TestResult] = Field(
        default_factory=list,
        description="可选拓展字段：学生上传的理论测试成绩",
    )

    # 元数据
    session_id: Optional[str] = None
    version: int = 1
    changed_fields: list[str] = Field(default_factory=list)


# domain_hint 限定枚举值
DOMAIN_HINT_ENUMS = [
    "LLM基础", "Prompt工程", "LangChain", "RAG",
    "HuggingFace", "模型微调", "向量数据库", "Agent框架", "项目部署",
]

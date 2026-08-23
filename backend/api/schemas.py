"""API 请求/响应模型"""

from typing import Optional

from pydantic import BaseModel, Field


# ============================================================
# 请求模型
# ============================================================

class AskRequest(BaseModel):
    """学生提问请求"""
    question: str = Field(..., max_length=4000, description="学生当前问题")
    session_id: str = Field(description="会话ID")
    history: Optional[list[dict]] = Field(
        None, description="历史对话（同一session，首次为空）"
    )
    profile: Optional[dict] = Field(
        None,
        description="可选学情画像（学历背景/理论测试结果等）。传入则跳过自动诊断、"
                    "直接驱动生成；字段非法时自动降级为自动诊断，不影响主流程。"
                    "完整字段见 StudentProfile（knowledge_level/background/current_goal/"
                    "question_type/complexity_estimate/intent_type/domain_hint/test_results）。",
    )


class FeedbackRequest(BaseModel):
    """学生反馈请求"""
    task_id: str
    session_id: str
    agent_id: str = Field(description="被反馈的Agent ID")
    function_tag: str = Field(description="功能标签")
    feedback_type: str = Field(
        description="helpful / not_helpful / content_error / difficulty_mismatch"
    )
    comment: Optional[str] = Field(None, max_length=2000, description="可选评论")


class QuizSubmitRequest(BaseModel):
    """答题提交请求"""
    task_id: str
    session_id: str
    answers: list[dict] = Field(
        description="答题结果 [{question: str, user_answer: str, is_correct: bool}]"
    )


class StatusRequest(BaseModel):
    """查询任务状态请求"""
    task_id: str


# ============================================================
# 响应模型
# ============================================================

class AskResponse(BaseModel):
    """提问响应"""
    task_id: str
    session_id: str
    profile: Optional[dict] = None
    resource_package: Optional[dict] = None
    judge_verdict: Optional[dict] = None
    # 裁判团三维度评分（事实准确性/逻辑完整性/教学适用性），供前端多Agent裁判结果面板展示
    review_summary: Optional[dict] = None
    dispatch_info: Optional[dict] = None
    navigation_roadmap: Optional[str] = None
    clarification_options: Optional[list[str]] = None
    error: Optional[str] = None
    # P1-7 数据合规：所有响应明确标注 AI 生成内容
    disclaimer: str = "⚠️ 以上内容由 AI 生成，仅供参考，请以官方文档与权威资料为准。"
    # P1-6 离线缓存：标识本次响应是否来自 demo_cache
    from_cache: bool = False


class StatusResponse(BaseModel):
    """任务状态响应"""
    task_id: str
    state: str
    data: Optional[dict] = None
    result: Optional[dict] = None  # 任务完成时的最终结果（与 /api/ask 返回结构一致）


class FeedbackResponse(BaseModel):
    """反馈响应"""
    success: bool
    message: str
    extension_triggered: Optional[str] = None


class QuizSubmitResponse(BaseModel):
    """答题提交响应"""
    task_id: str
    accuracy: float
    action: str = Field(description="redimension / advance / recheck")
    new_resources: Optional[dict] = None
    advance_question: Optional[dict] = None
    followup_questions: Optional[list[str]] = None


# ============================================================
# 学情诊断报告（方案书 8.2.2 节可视化报告三组件）
# ============================================================

class HeatmapNode(BaseModel):
    """知识盲区热力图节点"""
    domain: str = Field(description="领域名（如 LLM基础）")
    agent_name: str = Field(description="关联的 Agent 名")
    status: str = Field(description="mastered(绿已掌握) / partial(黄部分掌握) / blind(红盲区)")
    importance_score: float = Field(description="Agent Card 历史评分")
    interacted: bool = Field(description="学生是否已交互该领域")


class KnowledgeHeatmap(BaseModel):
    """组件1：知识盲区定位热力图"""
    nodes: list[HeatmapNode]
    blind_count: int = Field(description="盲区领域数")
    summary: str = Field(description="汇总建议")


class DifficultyMatchPoint(BaseModel):
    """资源难度匹配曲线数据点"""
    domain: str = Field(description="知识标签（横轴）")
    student_level: float = Field(description="学生掌握水平 0-1（蓝线）")
    resource_difficulty: float = Field(description="资源难度 0-1（红线）")
    match_status: str = Field(description="matched / too_easy / too_hard")


class DifficultyMatchCurve(BaseModel):
    """组件2：资源难度匹配曲线"""
    points: list[DifficultyMatchPoint]
    overall_match_rate: float = Field(description="整体匹配率 0-1")


class PathStage(BaseModel):
    """学习路径阶段节点"""
    stage: int = Field(description="阶段序号")
    title: str = Field(description="阶段标题")
    domains: list[str] = Field(description="涉及领域")
    estimated_hours: int = Field(description="预计学习时间（小时）")
    student_status: str = Field(description="mastered / partial / blind / not_reached")
    recommended: bool = Field(description="是否推荐优先学习（盲区联动）")


class LearningPath(BaseModel):
    """组件3：学习路径规划图"""
    stages: list[PathStage]


class LearningReport(BaseModel):
    """学情诊断报告（8.2.2 节三组件）"""
    session_id: str
    profile_summary: dict = Field(description="画像摘要")
    knowledge_heatmap: KnowledgeHeatmap
    difficulty_match: DifficultyMatchCurve
    learning_path: LearningPath

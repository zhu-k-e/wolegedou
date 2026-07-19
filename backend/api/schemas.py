"""API 请求/响应模型"""

from typing import Optional

from pydantic import BaseModel, Field


# ============================================================
# 请求模型
# ============================================================

class AskRequest(BaseModel):
    """学生提问请求"""
    question: str = Field(description="学生当前问题")
    session_id: str = Field(description="会话ID")
    history: Optional[list[dict]] = Field(
        None, description="历史对话（同一session，首次为空）"
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
    comment: Optional[str] = None


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
    dispatch_info: Optional[dict] = None
    navigation_roadmap: Optional[str] = None
    clarification_options: Optional[list[str]] = None
    error: Optional[str] = None


class StatusResponse(BaseModel):
    """任务状态响应"""
    task_id: str
    state: str
    data: Optional[dict] = None


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
    followup_questions: Optional[list[str]] = None

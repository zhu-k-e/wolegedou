"""Stage 3: ReviewFeedback - 审核反馈 (SOP链第3阶段产物)

对应方案书 6.2.2 节 Schema
被 Stage 4 订阅（聚焦输出基于审核反馈改进，MAR反馈回流的载体）
"""

from typing import Optional

from pydantic import BaseModel, Field


class ReviewerScores(BaseModel):
    """审核团队三人评分"""
    fact_accuracy: float = Field(ge=0.0, le=1.0, description="Verifier: 事实准确率")
    logic_completeness: float = Field(ge=0.0, le=1.0, description="Skeptic: 逻辑健全性")
    pedagogical_fit: float = Field(ge=0.0, le=1.0, description="Evaluator: 教学适配度")


class IssueFound(BaseModel):
    """审核发现的具体问题"""
    reviewer: str = Field(description="Verifier / Skeptic / Evaluator")
    severity: str = Field(description="high / medium / low")
    location: str = Field(description="问题位置，如 knowledge_refs[1]")
    description: str = Field(description="具体问题描述")


class CandidateReview(BaseModel):
    """单个候选的审核结果"""
    agent_id: str
    scores: ReviewerScores
    issues_found: list[IssueFound] = Field(
        default_factory=list,
        description="发现的具体问题列表，传给获胜Agent做反思改进",
    )
    is_winner: bool = Field(description="是否为本段最优")


class ReviewFeedback(BaseModel):
    """审核反馈 - SOP链 Stage 3 产物

    审核团队3人评分结果的标准化输出。
    issues_found 传给获胜Agent做反思改进（MAR反馈回流）。
    """
    seg_id: str = Field(description="段标识")
    candidates: list[CandidateReview] = Field(description="各候选的审核结果")
    cross_segment_issues: Optional[list[IssueFound]] = Field(
        None, description="跨段问题（仅多段场景）"
    )

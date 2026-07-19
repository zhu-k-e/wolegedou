"""Stage 2: CandidateOutput - 候选输出 (SOP链第2阶段产物)

对应方案书 6.2.4 节 Schema
被 Stage 3 订阅（审核团队基于候选输出评分）
"""

from typing import Optional

from pydantic import BaseModel, Field


class KnowledgeRef(BaseModel):
    """知识库引用条目"""
    source: str = Field(description="知识库来源文档名称+章节")
    content_summary: str = Field(description="引用的核心内容摘要")


class FocusedOutputBody(BaseModel):
    """聚焦输出内容体（候选输出和聚焦输出共用此结构）"""
    conclusion: Optional[str] = Field(None, description="核心结论，1-2句话")
    reasoning_steps: list[str] = Field(
        default_factory=list,
        description="推理步骤，每步都是可执行的操作或可读的概念解释",
    )
    knowledge_refs: list[KnowledgeRef] = Field(
        default_factory=list,
        description="每条知识点的知识库依据",
    )
    applicable_conditions: Optional[str] = Field(
        None, description="适用条件：适用场景、不适用场景、前置知识要求"
    )
    code_example: Optional[str] = Field(
        None, description="可选：可执行的代码示例"
    )
    difficulty_note: Optional[str] = Field(
        None, description="针对本学生知识水平的难度说明"
    )


class SelfConfidence(BaseModel):
    """DyLAN自评估：Agent诚实评估自身对当前问题的擅长程度"""
    score: float = Field(ge=0.0, le=1.0, description="信心分 0-1")
    weak_points: list[str] = Field(
        default_factory=list,
        description="Agent不确定的具体方面",
    )


class CandidateOutput(BaseModel):
    """候选输出 - SOP链 Stage 2 产物

    每段2个候选Agent并行输出，含self_confidence自评估。
    审核团队评分时只看 answer 内容，不看 self_confidence。
    """
    agent_id: str = Field(description="候选Agent ID")
    seg_id: str = Field(description="段标识（如 seg_1）")
    answer: FocusedOutputBody = Field(description="候选Agent的回答内容")
    self_confidence: SelfConfidence = Field(
        description="DyLAN自评估：信心分+不确定的方面"
    )

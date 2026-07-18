"""Stage 5: JudgeVerdict - 裁判裁决 (SOP链第5阶段产物)

对应方案书 6.2.3 节 Schema
被 Stage 6 订阅（资源生成基于裁决结果生成）

包含分歧解决和候选辩论的完整记录。
"""

from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class Verdict(str, Enum):
    """裁判团最终裁定（英文枚举值，前端展示时映射为中文）"""
    PASSED = "passed"                       # 通过
    REVISE = "revise"                       # 修改通过
    LOW_CONFIDENCE_PASSED = "low_confidence_passed"  # 低置信度通过
    FAILED = "failed"                       # 未通过


class VerificationStatus(str, Enum):
    VERIFIED = "已验证"
    UNVERIFIED = "待验证"
    CONTRADICTED = "矛盾"


class JudgeOpinion(BaseModel):
    """单个裁判的独立审查意见"""
    role: str = Field(description="事实审查 / 逻辑审查 / 适用性审查")
    judgment: str = Field(description="pass / fail")
    evidence: list[str] = Field(default_factory=list, description="证据列表")
    confidence: float = Field(
        ge=0.0, le=1.0,
        description="系统内部记录，对外隐藏",
    )


class CandidateDebate(BaseModel):
    """候选Agent辩论记录（Debate论文核心落地）"""
    challenging_agent: str = Field(description="落选候选Agent ID")
    challenge_evidence: list[str] = Field(default_factory=list)
    defending_agent: str = Field(description="获胜候选Agent ID")
    defense_evidence: list[str] = Field(default_factory=list)


class DissentResolution(BaseModel):
    """分歧解决记录（仅2:1分歧时填写）"""
    minority_judge: str = Field(description="少数方裁判角色")
    evidence_submitted: list[str] = Field(
        default_factory=list, description="少数方提交的证据"
    )
    majority_response: str = Field(description="accepted / rejected")
    candidate_debate: Optional[CandidateDebate] = Field(
        None, description="候选Agent辩论记录"
    )


class TraceabilityItem(BaseModel):
    """溯源标注条目"""
    statement: str = Field(description="被标注的知识陈述")
    source: str = Field(description="知识库来源文档+章节")
    verification_status: VerificationStatus


class JudgeVerdict(BaseModel):
    """裁判裁决 - SOP链 Stage 5 产物

    裁判团裁决结果的标准化输出，包含分歧解决和候选辩论的完整记录。
    """
    verdict: Verdict = Field(description="最终裁定")
    judges: list[JudgeOpinion] = Field(
        description="3名裁判的独立审查意见",
    )
    dissent_resolution: Optional[DissentResolution] = Field(
        None, description="分歧解决记录（仅2:1分歧时填写）"
    )
    traceability: list[TraceabilityItem] = Field(
        default_factory=list, description="溯源标注"
    )
    overall_verification_rate: float = Field(
        ge=0.0, le=1.0, description="整体溯源验证率"
    )

"""Stage 4: FocusedOutput - 聚焦输出 (SOP链第4阶段产物)

对应方案书 3.5 节 Schema
被 Stage 5 订阅（裁判团基于聚焦输出审查）

聚焦输出是最优Agent收到审核反馈后反思改进的产物（MAR落地）。
"""

from pydantic import Field, field_validator

from backend.schemas.candidate_output import FocusedOutputBody, KnowledgeRef


class FocusedOutput(FocusedOutputBody):
    """聚焦输出 - SOP链 Stage 4 产物

    最优Agent被选中后，收到审核反馈的具体问题，
    针对性改进后按此Schema完整输出。

    继承 FocusedOutputBody，但将 required 字段设为必填。
    """
    conclusion: str = Field(description="针对学生问题的核心结论，1-2句话")
    reasoning_steps: list[str] = Field(
        min_length=3,
        description="推理步骤，至少3步",
    )
    knowledge_refs: list[KnowledgeRef] = Field(
        description="每条知识点的知识库依据，无法确认则标注待验证"
    )
    applicable_conditions: str = Field(
        description="适用条件：适用场景、不适用场景、前置知识要求"
    )
    # code_example 和 difficulty_note 仍为可选

    @field_validator("reasoning_steps")
    @classmethod
    def validate_min_steps(cls, v):
        if len(v) < 3:
            raise ValueError("reasoning_steps 至少需要3步")
        return v

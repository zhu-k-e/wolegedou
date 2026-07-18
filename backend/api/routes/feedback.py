"""/feedback 接口 - 学生反馈

更新贡献记忆 + 触发延伸路径
"""

from fastapi import APIRouter

from backend.api.schemas import FeedbackRequest, FeedbackResponse
from backend.services.memory_service import get_memory_service
from backend.core.orchestrator import Orchestrator
from backend.api.routes.ask import get_orchestrator

router = APIRouter()


@router.post("/feedback", response_model=FeedbackResponse)
async def submit_feedback(request: FeedbackRequest) -> FeedbackResponse:
    """学生反馈

    反馈类型：
      helpful → accuracy +0.02
      not_helpful → accuracy -0.02
      content_error → 记录，人工复核 + 触发RECHECK
      difficulty_mismatch → 触发REDIMENSION（不与Agent表现挂钩）
    """
    memory_service = get_memory_service()

    # 更新贡献记忆
    memory_service.apply_student_feedback(
        session_id=request.session_id,
        agent_id=request.agent_id,
        function_tag=request.function_tag,
        feedback_type=request.feedback_type,
        comment=request.comment,
    )

    # 触发延伸路径
    extension_triggered = None
    if request.feedback_type == "content_error":
        orchestrator = get_orchestrator()
        await orchestrator.handle_extension(
            task_id=request.task_id,
            event_type="feedback_error",
            event_data={"feedback": request.comment or ""},
        )
        extension_triggered = "recheck"
    elif request.feedback_type == "difficulty_mismatch":
        orchestrator = get_orchestrator()
        await orchestrator.handle_extension(
            task_id=request.task_id,
            event_type="feedback_difficulty",
            event_data={"feedback": request.comment or ""},
        )
        extension_triggered = "redimension"

    return FeedbackResponse(
        success=True,
        message=f"反馈已记录: {request.feedback_type}",
        extension_triggered=extension_triggered,
    )

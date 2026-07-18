"""/quiz_submit 接口 - 答题验证

计算正确率 + 触发降维/进阶
"""

from fastapi import APIRouter

from backend.api.schemas import QuizSubmitRequest, QuizSubmitResponse
from backend.core.orchestrator import Orchestrator
from backend.api.routes.ask import get_orchestrator

router = APIRouter()


@router.post("/quiz_submit", response_model=QuizSubmitResponse)
async def submit_quiz(request: QuizSubmitRequest) -> QuizSubmitResponse:
    """答题验证

    对应方案书 6.1.3 节延伸路径：
      正确率<60% → REDIMENSION（降维解释）
      正确率60%-85% → REDIMENSION（轻度降维）
      正确率≥85% → ADVANCE（进阶挑战）
    """
    # 计算正确率
    total = len(request.answers)
    correct = sum(1 for a in request.answers if a.get("is_correct", False))
    accuracy = correct / total if total > 0 else 0.0

    # 触发延伸路径
    orchestrator = get_orchestrator()
    result = await orchestrator.handle_extension(
        task_id=request.task_id,
        event_type="quiz_submit",
        event_data={
            "accuracy": accuracy,
            "answers": request.answers,
            "session_id": request.session_id,
        },
    )

    action = result.get("action", "redimension" if accuracy < 0.85 else "advance")
    followup_questions = result.get("followup_questions")

    return QuizSubmitResponse(
        task_id=request.task_id,
        accuracy=round(accuracy, 4),
        action=action,
        followup_questions=followup_questions,
    )

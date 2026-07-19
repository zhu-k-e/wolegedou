"""/ask 接口 - 主流程入口

学生提交问题，触发FSM编排器完整流程。
"""

from fastapi import APIRouter

from backend.api.schemas import AskRequest, AskResponse
from backend.core.orchestrator import Orchestrator

router = APIRouter()

# 编排器单例
_orchestrator: Orchestrator | None = None


def get_orchestrator() -> Orchestrator:
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = Orchestrator()
    return _orchestrator


@router.post("/ask", response_model=AskResponse)
async def ask(request: AskRequest) -> AskResponse:
    """学生提问 - 主流程入口

    触发FSM编排器：
      PROFILING → DISPATCHING → GENERATING → REVIEWING
      → FOCUSING → JUDGING → FORMATTING → COMPLETE

    响应时间：
      单领域 ~20s, 跨领域 ~27s, 全链路 ~38s
    """
    orchestrator = get_orchestrator()
    result = await orchestrator.process_question(
        question=request.question,
        session_id=request.session_id,
        history=request.history,
    )

    return AskResponse(**result)

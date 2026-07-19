"""/status 接口 - 查询当前任务FSM状态

前端通过此接口或WebSocket获取FSM状态。
"""

from fastapi import APIRouter

from backend.api.schemas import StatusResponse

router = APIRouter()

# 任务状态缓存（实际实现中可用Redis或内存字典）
# WebSocket推送时同步更新此缓存
_task_states: dict[str, dict] = {}


def update_task_state(task_id: str, state: str, data: dict | None = None):
    """更新任务状态缓存（供WebSocket推送时调用）"""
    _task_states[task_id] = {"state": state, "data": data or {}}


@router.get("/status/{task_id}", response_model=StatusResponse)
async def get_status(task_id: str) -> StatusResponse:
    """查询任务当前FSM状态"""
    state_info = _task_states.get(task_id, {"state": "UNKNOWN", "data": {}})
    return StatusResponse(
        task_id=task_id,
        state=state_info["state"],
        data=state_info.get("data"),
    )

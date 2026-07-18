"""WebSocket 端点 - 实时推送FSM状态给前端

对应方案书 8.2.3 节协同过程实时展示：
  后端编排器每个FSM状态转换时，通过WebSocket推送状态给前端
  前端用动画展示"当前FSM状态：XXX"
"""

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from loguru import logger

from backend.services.ws_manager import ws_manager

router = APIRouter()


@router.websocket("/ws/{task_id}")
async def websocket_endpoint(websocket: WebSocket, task_id: str):
    """WebSocket连接

    前端连接后，编排器的每次FSM状态变更都会推送：

    消息格式:
    {
        "type": "fsm_state",
        "task_id": "task_xxx",
        "state": "PROFILING",
        "data": {"profile": {...}}
    }
    """
    await ws_manager.connect(websocket, task_id)
    try:
        while True:
            # 保持连接，接收前端可能的控制消息
            data = await websocket.receive_text()
            logger.debug(f"WebSocket收到消息: task_id={task_id}, data={data}")

    except WebSocketDisconnect:
        ws_manager.disconnect(websocket, task_id)
        logger.info(f"WebSocket断开: task_id={task_id}")

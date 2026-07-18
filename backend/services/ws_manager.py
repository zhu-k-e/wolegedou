"""WebSocket连接管理器 - 实时推送FSM状态给前端

对应方案书 8.2.3 节协同过程实时展示：
  后端编排器每个FSM状态转换时，通过WebSocket推送状态给前端
"""

import json
from typing import Optional

from fastapi import WebSocket
from loguru import logger


class WSManager:
    """WebSocket连接管理器

    支持按task_id管理多个连接（一个任务可能有多个前端页面观察）。
    """

    def __init__(self):
        # task_id -> set[WebSocket]
        self._connections: dict[str, set[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, task_id: str):
        """接受WebSocket连接并关联到task_id"""
        await websocket.accept()
        if task_id not in self._connections:
            self._connections[task_id] = set()
        self._connections[task_id].add(websocket)
        logger.info(f"WebSocket已连接, task_id={task_id}, 当前连接数={len(self._connections[task_id])}")

    def disconnect(self, websocket: WebSocket, task_id: str):
        """断开WebSocket连接"""
        if task_id in self._connections:
            self._connections[task_id].discard(websocket)
            if not self._connections[task_id]:
                del self._connections[task_id]
            logger.debug(f"WebSocket已断开, task_id={task_id}")

    async def push_state(self, task_id: str, state: str, data: Optional[dict] = None):
        """推送FSM状态变更给指定task_id的所有连接

        Args:
            task_id: 任务ID
            state: 当前FSM状态名
            data: 附加数据（如学情画像JSON、候选输出摘要等）
        """
        message = {
            "type": "fsm_state",
            "task_id": task_id,
            "state": state,
            "data": data or {},
        }

        if task_id not in self._connections:
            logger.debug(f"task_id={task_id} 无WebSocket连接，跳过推送")
            return

        disconnected = set()
        for ws in self._connections[task_id]:
            try:
                await ws.send_json(message)
            except Exception as e:
                logger.warning(f"WebSocket推送失败: {e}")
                disconnected.add(ws)

        # 清理断开的连接
        for ws in disconnected:
            self._connections[task_id].discard(ws)

    async def push_event(self, task_id: str, event_type: str, data: dict):
        """推送自定义事件（如审核评分完成、裁判裁决完成等）"""
        message = {
            "type": event_type,
            "task_id": task_id,
            "data": data,
        }

        if task_id not in self._connections:
            return

        for ws in list(self._connections[task_id]):
            try:
                await ws.send_json(message)
            except Exception:
                self._connections[task_id].discard(ws)


# 全局单例
ws_manager = WSManager()

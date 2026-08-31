"""跨进程任务上下文快照（供 feedback/quiz 延伸路径在多 worker 下共享）

背景（体检发现 #4）：
    orchestrator 的 _task_contexts 是进程内字典。当 uvicorn 以多进程（reload / 多 worker）
    运行时，/feedback、/quiz 请求可能打到没有该任务上下文的 worker，导致 recheck / 降维 /
    进阶等延伸路径静默跳过（仅走 heuristic 兜底）。

本模块把延伸路径必需的 profile + merged_focused_output 持久化到 JSON 文件（同机多进程共享）。
主生成流程结束时写一次；handle_extension 在内存 ctx 缺失时从快照恢复。

降级保证：快照写入/读取失败均只打 warning 并回退到原 heuristic 兜底，行为不劣于现状。
"""

import json
import os
from pathlib import Path
from types import SimpleNamespace

from loguru import logger

from backend.config import get_settings
from backend.schemas.focused_output import FocusedOutput
from backend.schemas.student_profile import StudentProfile


_STORE_DIR: Path | None = None


def _store_dir() -> Path:
    global _STORE_DIR
    if _STORE_DIR is None:
        settings = get_settings()
        _STORE_DIR = settings.project_root / "data" / "task_contexts"
        _STORE_DIR.mkdir(parents=True, exist_ok=True)
    return _STORE_DIR


def save_extension_context(task_id: str, profile, focused_output) -> None:
    """持久化延伸路径所需的 profile + merged_focused_output（原子写）"""
    if profile is None or focused_output is None:
        return
    try:
        payload = {
            "profile": profile.model_dump(),
            "focused_output": focused_output.model_dump(),
        }
        path = _store_dir() / f"{task_id}.json"
        tmp = path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(payload, ensure_ascii=False, default=str),
            encoding="utf-8",
        )
        os.replace(tmp, path)  # 原子替换，避免半写文件
    except Exception as e:
        logger.warning(f"持久化延伸上下文失败(task={task_id}): {e}")


def load_extension_context(task_id: str):
    """从快照恢复最小上下文（仅含延伸路径读取的 profile + merged_focused_output）

    返回 SimpleNamespace 或 None（快照不可用/损坏时）。
    """
    path = _store_dir() / f"{task_id}.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        profile = StudentProfile.model_validate(data["profile"])
        focused_output = FocusedOutput.model_validate(data["focused_output"])
        return SimpleNamespace(
            profile=profile, merged_focused_output=focused_output
        )
    except Exception as e:
        logger.warning(f"加载延伸上下文失败(task={task_id}): {e}")
        return None

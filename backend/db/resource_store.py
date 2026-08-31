"""生成资源落库（task_resources 表）

在 /api/ask 返回层与异步任务完成时静默写入最终生成的讲义/实操指南/测试题文本。
仅做持久化，不改任何生成逻辑，不增加调用时间（单次 INSERT，失败不影响主流程）。

用途：
  1. validate_metrics.py 结合 tests/test_cases_100.json 真值做事实比对（覆盖率/适配率）；
  2. 导出"输入画像 → 多智能体协同中间数据 → 最终生成资源"完整示例，作为竞赛测试数据套装。
"""

import json
from typing import Optional

from loguru import logger

from backend.db.database import execute_sql

_TASK_RESOURCES_DDL = """
CREATE TABLE IF NOT EXISTS task_resources (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id              TEXT NOT NULL UNIQUE,
    session_id           TEXT NOT NULL,
    question             TEXT,
    lecture              TEXT,
    practice_guide       TEXT,
    quiz                 TEXT,
    knowledge_refs       TEXT,
    created_at           TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
"""


def ensure_task_resources_table() -> None:
    """幂等建表（与 init_db 中 DDL 保持一致；metrics 脚本与独立运行也可调用）"""
    execute_sql(_TASK_RESOURCES_DDL)


def _to_text(obj) -> Optional[str]:
    """把讲义/指南/测试题组件统一转成可存储文本。

    - pydantic 模型 → model_dump JSON
    - dict / list / tuple → JSON（list 元素可能是 pydantic 模型，逐个展开）
    - 其他 → str

    注意：list 必须走 JSON 而不是 str()，否则得到 Python repr（单引号），
    下游 json.loads 会解析失败（knowledge_refs 曾因此全部 parse_err）。
    """
    if obj is None:
        return None
    if hasattr(obj, "model_dump"):
        try:
            return json.dumps(obj.model_dump(), ensure_ascii=False)
        except Exception:
            return str(obj)
    if isinstance(obj, (dict, list, tuple)):
        try:
            return json.dumps(obj, ensure_ascii=False, default=_json_default)
        except Exception:
            return str(obj)
    return str(obj)


def _json_default(o):
    """json.dumps 兜底：pydantic 模型 / 任意对象 → 可序列化形式"""
    if hasattr(o, "model_dump"):
        return o.model_dump()
    return str(o)


def save_task_resources(
    task_id: str,
    session_id: str,
    result: dict,
    question: Optional[str] = None,
) -> None:
    """从 result 提取资源包文本并落库（幂等：同 task_id 覆盖写）。

    兼容 result["resource_package"] 为 dict 或 pydantic ResourcePackage。
    响应层资源包键名使用 lecture / guide / quiz（practice_guide 别名也兼容）。
    """
    if not task_id:
        return
    rp = result.get("resource_package")
    if not rp:
        return
    if hasattr(rp, "model_dump"):
        rp = rp.model_dump()
    if not isinstance(rp, dict):
        return

    lecture = rp.get("lecture")
    guide = rp.get("guide") or rp.get("practice_guide")
    quiz = rp.get("quiz")
    knowledge_refs = None
    if isinstance(lecture, dict):
        knowledge_refs = lecture.get("knowledge_refs_display")
    elif hasattr(lecture, "model_dump"):
        knowledge_refs = lecture.model_dump().get("knowledge_refs_display")

    ensure_task_resources_table()
    execute_sql(
        """INSERT INTO task_resources
           (task_id, session_id, question, lecture, practice_guide, quiz, knowledge_refs)
           VALUES (?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(task_id) DO UPDATE SET
               session_id=excluded.session_id,
               question=excluded.question,
               lecture=excluded.lecture,
               practice_guide=excluded.practice_guide,
               quiz=excluded.quiz,
               knowledge_refs=excluded.knowledge_refs
        """,
        (
            task_id,
            session_id,
            question,
            _to_text(lecture),
            _to_text(guide),
            _to_text(quiz),
            _to_text(knowledge_refs),
        ),
    )
    logger.debug(f"资源已落库: task_id={task_id}")

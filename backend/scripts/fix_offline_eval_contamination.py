"""一次性修复脚本：将历史 benchmark 贡献记忆标记为 offline_eval，
并回退被 benchmark 污染的 agent_performance.count。

注意：
- accuracy 和 rework_rate 是 EMA 更新，无法精确反推，保持当前值不动。
- count 可按 contribution_memory 记录数精确扣减。
- importance_score 会根据新的 count 重新计算并写回。
"""

from __future__ import annotations

import shutil
import sqlite3
import sys
from pathlib import Path
from datetime import datetime

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from backend.db.repositories import agent_repo
from backend.services.memory_service import MemoryService


def main() -> None:
    db_path = PROJECT_ROOT / "data" / "wolegedou.db"
    backup_path = db_path.with_suffix(
        f".db.backup.offline_eval_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    )

    print(f"[1/5] 备份数据库 -> {backup_path}")
    shutil.copy2(db_path, backup_path)

    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    print("[2/5] 查找 benchmark 任务产生的 contribution_memory 记录")
    cur.execute("""
        SELECT task_id FROM task_metrics
        WHERE session_id LIKE 'bm_%%'
    """)
    bm_task_ids = [r["task_id"] for r in cur.fetchall()]
    print(f"      benchmark 任务数: {len(bm_task_ids)}")
    if not bm_task_ids:
        print("      没有 benchmark 任务，无需修复")
        con.close()
        return

    placeholders = ",".join("?" * len(bm_task_ids))

    # 统计每个 (agent_id, function_tag) 被 benchmark 污染的次数
    cur.execute(f"""
        SELECT agent_id, function_tag, COUNT(*) AS c
        FROM contribution_memory
        WHERE task_id IN ({placeholders})
        GROUP BY agent_id, function_tag
    """, bm_task_ids)
    bm_counts = [(r["agent_id"], r["function_tag"], r["c"]) for r in cur.fetchall()]
    print(f"      受影响记录数: {sum(c for _, _, c in bm_counts)}")

    print("[3/5] 回退 agent_performance.count")
    affected_tags: set[tuple[str, str]] = set()
    for agent_id, function_tag, c in bm_counts:
        cur.execute(
            "SELECT count FROM agent_performance WHERE agent_id = ? AND function_tag = ?",
            (agent_id, function_tag),
        )
        row = cur.fetchone()
        if not row:
            print(f"      WARN: agent_performance 中无 {agent_id}/{function_tag}，跳过")
            continue
        old_count = row["count"]
        new_count = max(0, old_count - c)
        cur.execute(
            "UPDATE agent_performance SET count = ? WHERE agent_id = ? AND function_tag = ?",
            (new_count, agent_id, function_tag),
        )
        affected_tags.add((agent_id, function_tag))
        print(f"      {agent_id}/{function_tag}: count {old_count} -> {new_count} (-{c})")

    print("[4/5] 将 benchmark 贡献记忆标记为 offline_eval")
    cur.execute(f"""
        UPDATE contribution_memory
        SET task_type = 'offline_eval'
        WHERE task_id IN ({placeholders})
    """, bm_task_ids)
    print(f"      更新行数: {cur.rowcount}")

    con.commit()
    con.close()

    print("[5/5] 重新计算受影响的 importance_score")
    ms = MemoryService()
    for agent_id, function_tag in sorted(affected_tags):
        score = ms.compute_importance_score(agent_id, function_tag)
        perf = agent_repo.get_agent_performance(agent_id, function_tag)
        if perf:
            agent_repo.update_agent_performance(
                agent_id,
                function_tag,
                accuracy=perf["accuracy"],
                count=perf["count"],
                rework_rate=perf["rework_rate"],
                importance_score=score,
                is_suspended=perf["is_suspended"],
            )
        print(f"      {agent_id}/{function_tag}: importance_score -> {score:.4f}")

    print("\n修复完成。数据库备份在:", backup_path)


if __name__ == "__main__":
    main()

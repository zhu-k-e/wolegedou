"""数据库迁移脚本：为 session_id 相关表添加外键约束

问题背景：
  student_profiles / task_resource_stats / task_metrics / student_feedback
  四张表原先没有 FK 到 session 表，导致孤儿记录（session_id 不在 session 表中）。
  SQLite 不支持 ALTER TABLE ADD FOREIGN KEY，需要重建表。

迁移策略（SQLite 标准表重建流程）：
  1. 临时关闭 FK
  2. 创建带 FK 的新表
  3. 从旧表复制数据（只复制有对应 session 的行 → 自动清理孤儿）
  4. 删除旧表
  5. 重命名新表
  6. 重建索引
  7. 验证 FK 完整性
  8. 重新开启 FK

用法：
  python -m backend.db.migrate_add_fk          # 执行迁移
  python -m backend.db.migrate_add_fk --check  # 仅检查不执行
"""

import sqlite3
from loguru import logger

from backend.db.database import get_connection


# 需要加 FK 的表 → 新表 DDL（含 FK 约束）
# 顺序很重要：先迁移有数据的表，后迁移无数据的表
TABLES_TO_MIGRATE = {
    "student_profiles": """
        CREATE TABLE {name} (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id          TEXT NOT NULL,
            version             INTEGER NOT NULL,
            knowledge_level     TEXT NOT NULL,
            background          TEXT NOT NULL,
            current_goal        TEXT NOT NULL,
            question_type       TEXT NOT NULL,
            domain_hint         TEXT NOT NULL,
            complexity_estimate TEXT NOT NULL,
            intent_type         TEXT NOT NULL,
            domain_confidence   TEXT NOT NULL,
            created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(session_id, version),
            FOREIGN KEY(session_id) REFERENCES session(session_id)
        )
    """,
    "student_feedback": """
        CREATE TABLE {name} (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id    TEXT NOT NULL,
            agent_id      TEXT NOT NULL,
            function_tag  TEXT NOT NULL,
            feedback_type TEXT NOT NULL,
            comment       TEXT,
            created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(session_id) REFERENCES session(session_id),
            FOREIGN KEY(agent_id) REFERENCES agent_cards(agent_id)
        )
    """,
    "task_resource_stats": """
        CREATE TABLE {name} (
            id                   INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id              TEXT NOT NULL,
            session_id           TEXT NOT NULL,
            domain               TEXT,
            knowledge_level      TEXT,
            quiz_difficulties    TEXT,
            lecture_difficulty_note TEXT,
            created_at           TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(session_id) REFERENCES session(session_id)
        )
    """,
    "task_metrics": """
        CREATE TABLE {name} (
            id                   INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id              TEXT NOT NULL,
            session_id           TEXT NOT NULL,
            verdict              TEXT,
            verification_rate    REAL,
            traceability_total   INTEGER DEFAULT 0,
            traceability_verified INTEGER DEFAULT 0,
            knowledge_refs_count INTEGER DEFAULT 0,
            fact_accuracy        REAL,
            logic_completeness   REAL,
            pedagogical_fit      REAL,
            review_score         REAL,
            created_at           TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(session_id) REFERENCES session(session_id)
        )
    """,
}

# 每个表需要重建的索引（名称 → DDL）
INDEXES = {
    "student_profiles": [
        "CREATE INDEX IF NOT EXISTS idx_profiles_session ON student_profiles(session_id)",
    ],
    "student_feedback": [
        "CREATE INDEX IF NOT EXISTS idx_feedback_session ON student_feedback(session_id)",
    ],
    "task_resource_stats": [
        "CREATE INDEX IF NOT EXISTS idx_resource_stats_session ON task_resource_stats(session_id)",
    ],
    "task_metrics": [
        "CREATE INDEX IF NOT EXISTS idx_metrics_session ON task_metrics(session_id)",
    ],
}


def _has_fk_to_session(conn: sqlite3.Connection, table: str) -> bool:
    """检查表是否已有 FK 到 session 表"""
    rows = conn.execute(f"PRAGMA foreign_key_list({table})").fetchall()
    for r in rows:
        # Row: (id, seq, table, from, to, on_update, on_delete, match)
        if r[2] == "session":
            return True
    return False


def _count_orphans(conn: sqlite3.Connection, table: str) -> int:
    """统计孤儿记录数（session_id 不在 session 表中）"""
    row = conn.execute(
        f"""SELECT COUNT(*) FROM {table} t
            LEFT JOIN session s ON t.session_id = s.session_id
            WHERE s.session_id IS NULL"""
    ).fetchone()
    return row[0]


def _migrate_table(conn: sqlite3.Connection, table: str, new_ddl: str) -> tuple[int, int]:
    """重建单张表（加 FK），返回 (迁移行数, 清理孤儿数)

    流程：
    1. 统计孤儿
    2. 创建 _new 临时表（带 FK）
    3. 从旧表复制有效数据（过滤孤儿）
    4. 删除旧表
    5. 重命名 _new → 原名
    6. 重建索引
    """
    # 统计孤儿
    orphans = _count_orphans(conn, table)
    total = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    migrated = total - orphans

    logger.info(f"  [{table}] 总记录 {total}，孤儿 {orphans}，将迁移 {migrated} 条")

    # 创建临时新表
    tmp_name = f"_migration_{table}"
    conn.execute(f"DROP TABLE IF EXISTS {tmp_name}")
    conn.execute(new_ddl.format(name=tmp_name))

    # 复制有效数据（只复制 session 存在的行）
    conn.execute(
        f"""INSERT INTO {tmp_name}
            SELECT t.* FROM {table} t
            INNER JOIN session s ON t.session_id = s.session_id"""
    )

    # 删除旧表
    conn.execute(f"DROP TABLE {table}")

    # 重命名
    conn.execute(f"ALTER TABLE {tmp_name} RENAME TO {table}")

    # 重建索引
    for idx_ddl in INDEXES.get(table, []):
        conn.execute(idx_ddl)

    return migrated, orphans


def run_migration(check_only: bool = False) -> None:
    """执行迁移（或仅检查）"""
    conn = get_connection()

    # 先检查哪些表需要迁移
    needs_migration = []
    for table, ddl in TABLES_TO_MIGRATE.items():
        # 确认表存在
        exists = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone()
        if not exists:
            logger.info(f"  [{table}] 表不存在，跳过（init_db 会创建带 FK 的新表）")
            continue

        if _has_fk_to_session(conn, table):
            logger.info(f"  [{table}] 已有 FK 到 session，无需迁移")
            continue

        orphans = _count_orphans(conn, table)
        logger.info(f"  [{table}] 需要迁移（孤儿记录 {orphans} 条）")
        needs_migration.append((table, ddl))

    if not needs_migration:
        logger.info("所有表已有 FK 约束，无需迁移")
        return

    if check_only:
        logger.info(f"--check 模式：{len(needs_migration)} 张表待迁移，不执行")
        return

    # 执行迁移
    logger.info(f"开始迁移 {len(needs_migration)} 张表...")

    # 临时关闭 FK 约束（重建过程中需要）
    conn.execute("PRAGMA foreign_keys = OFF")

    try:
        conn.execute("BEGIN TRANSACTION")

        total_migrated = 0
        total_orphans = 0
        for table, ddl in needs_migration:
            migrated, orphans = _migrate_table(conn, table, ddl)
            total_migrated += migrated
            total_orphans += orphans

        # 验证 FK 完整性
        violations = conn.execute("PRAGMA foreign_key_check").fetchall()
        if violations:
            # 回滚
            conn.rollback()
            logger.error(f"FK 完整性检查失败，已回滚！违规项: {violations}")
            raise RuntimeError(f"foreign_key_check 发现 {len(violations)} 处违规")

        conn.commit()
        logger.info(f"迁移完成：迁移 {total_migrated} 条记录，清理 {total_orphans} 条孤儿")

    except Exception as e:
        conn.rollback()
        logger.error(f"迁移失败，已回滚: {e}")
        raise
    finally:
        # 重新开启 FK
        conn.execute("PRAGMA foreign_keys = ON")

    # 迁移后验证
    logger.info("迁移后验证：")
    for table in TABLES_TO_MIGRATE:
        has_fk = _has_fk_to_session(conn, table)
        orphans = _count_orphans(conn, table)
        status = "✅" if has_fk and orphans == 0 else "❌"
        logger.info(f"  {status} {table}: FK={'有' if has_fk else '无'}, 孤儿={orphans}")


if __name__ == "__main__":
    import sys
    check = "--check" in sys.argv
    run_migration(check_only=check)

"""数据库初始化脚本 - 创建全部9张表 + 种子数据

对应方案书 5.1.1 节 SQLite表结构
"""

from loguru import logger

from backend.db.database import get_connection, execute_sql
from backend.agents.agent_registry import AGENT_CARDS
from backend.config import get_settings


# ============================================================
# DDL: 9张表
# ============================================================

DDL_STATEMENTS = [
    # 1. Agent卡片表（静态信息）
    """
    CREATE TABLE IF NOT EXISTS agent_cards (
        agent_id           TEXT PRIMARY KEY,
        agent_name         TEXT NOT NULL,
        primary_function   TEXT NOT NULL,
        secondary_functions TEXT NOT NULL,   -- JSON array
        domain_tags        TEXT NOT NULL,    -- JSON array
        status             TEXT DEFAULT 'active',  -- active / eliminated
        created_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,

    # 2. Agent表现表（动态表现，per-function-tag粒度）
    """
    CREATE TABLE IF NOT EXISTS agent_performance (
        id                INTEGER PRIMARY KEY AUTOINCREMENT,
        agent_id          TEXT NOT NULL,
        function_tag      TEXT NOT NULL,
        accuracy          REAL DEFAULT 0.5,
        count             INTEGER DEFAULT 0,
        rework_rate       REAL DEFAULT 0.0,
        importance_score  REAL DEFAULT 0.5,
        is_suspended      BOOLEAN DEFAULT 0,
        updated_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(agent_id, function_tag),
        FOREIGN KEY(agent_id) REFERENCES agent_cards(agent_id)
    )
    """,

    # 3. 贡献记忆表
    """
    CREATE TABLE IF NOT EXISTS contribution_memory (
        id                   INTEGER PRIMARY KEY AUTOINCREMENT,
        task_id              TEXT NOT NULL,
        agent_id             TEXT NOT NULL,
        function_tag         TEXT NOT NULL,
        task_type            TEXT NOT NULL,   -- 单领域/跨领域/全链路/offline_eval
        segment              TEXT,
        review_score         REAL,
        importance_score     REAL,
        referee_verdict      TEXT,            -- passed/revise/low_confidence_passed/failed
        referee_modifications INTEGER DEFAULT 0,
        rework_type          TEXT,            -- none/minor/major
        created_at           TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(agent_id) REFERENCES agent_cards(agent_id)
    )
    """,

    # 4. 学生反馈表
    """
    CREATE TABLE IF NOT EXISTS student_feedback (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id    TEXT NOT NULL,
        agent_id      TEXT NOT NULL,
        function_tag  TEXT NOT NULL,
        feedback_type TEXT NOT NULL,  -- helpful/not_helpful/content_error/difficulty_mismatch
        comment       TEXT,
        created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(agent_id) REFERENCES agent_cards(agent_id)
    )
    """,

    # 5. 系统配置表
    """
    CREATE TABLE IF NOT EXISTS system_config (
        key        TEXT PRIMARY KEY,
        value      TEXT NOT NULL,   -- JSON value
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,

    # 6. 学情画像历史表
    """
    CREATE TABLE IF NOT EXISTS student_profiles (
        id                  INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id          TEXT NOT NULL,
        version             INTEGER NOT NULL,
        knowledge_level     TEXT NOT NULL,
        background          TEXT NOT NULL,
        current_goal        TEXT NOT NULL,
        question_type       TEXT NOT NULL,
        domain_hint         TEXT NOT NULL,    -- JSON数组
        complexity_estimate TEXT NOT NULL,
        intent_type         TEXT NOT NULL,
        domain_confidence   TEXT NOT NULL,    -- JSON对象
        created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(session_id, version)
    )
    """,

    # 7. 淘汰日志表
    """
    CREATE TABLE IF NOT EXISTS elimination_log (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        agent_id     TEXT NOT NULL,
        function_tag TEXT,
        reason       TEXT NOT NULL,
        restored_at  TEXT,
        created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(agent_id) REFERENCES agent_cards(agent_id)
    )
    """,

    # 8. 离线评估队列表
    """
    CREATE TABLE IF NOT EXISTS offline_evaluation_queue (
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        agent_id         TEXT NOT NULL,
        function_tag     TEXT,
        evaluation_round INTEGER DEFAULT 0,
        last_accuracy    REAL,
        status           TEXT DEFAULT 'pending',  -- pending/passed/failed
        created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(agent_id) REFERENCES agent_cards(agent_id)
    )
    """,

    # 9. 人工复核队列表
    """
    CREATE TABLE IF NOT EXISTS human_review_queue (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT NOT NULL,
        agent_id   TEXT NOT NULL,
        reason     TEXT NOT NULL,
        status     TEXT DEFAULT 'pending',  -- pending/resolved
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,

    # 索引
    "CREATE INDEX IF NOT EXISTS idx_perf_agent_tag ON agent_performance(agent_id, function_tag)",
    "CREATE INDEX IF NOT EXISTS idx_memory_agent_tag ON contribution_memory(agent_id, function_tag)",
    "CREATE INDEX IF NOT EXISTS idx_profiles_session ON student_profiles(session_id)",
    "CREATE INDEX IF NOT EXISTS idx_feedback_session ON student_feedback(session_id)",
]


def init_database():
    """初始化数据库：创建全部表 + 写入种子数据"""
    conn = get_connection()
    try:
        # 创建表
        for ddl in DDL_STATEMENTS:
            conn.execute(ddl)
        conn.commit()
        logger.info(f"数据库表已创建/确认存在（{len(DDL_STATEMENTS)}条DDL）")

        # 写入系统配置种子数据
        _seed_system_config(conn)

        # 写入Agent卡片种子数据
        _seed_agent_cards(conn)

        conn.commit()
        logger.info("种子数据写入完成")

    except Exception as e:
        conn.rollback()
        logger.error(f"数据库初始化失败: {e}")
        raise
    finally:
        conn.close()


def _seed_system_config(conn):
    """写入系统配置初始值"""
    import json

    settings = get_settings()
    configs = {
        "alpha": json.dumps(settings.alpha_initial),
        "ema_smooth": json.dumps(settings.ema_smooth),
        "elimination_threshold": json.dumps(settings.elimination_threshold),
        "elimination_consecutive_count": json.dumps(settings.elimination_consecutive_count),
        # 审核权重
        "review_weights": json.dumps({"w1": 0.35, "w2": 0.35, "w3": 0.30}),
    }

    for key, value in configs.items():
        conn.execute(
            "INSERT OR IGNORE INTO system_config (key, value) VALUES (?, ?)",
            (key, value),
        )


def _seed_agent_cards(conn):
    """写入11个Agent卡片 + 初始化performance表"""
    import json

    for card in AGENT_CARDS:
        # 插入agent_cards
        conn.execute(
            """
            INSERT OR IGNORE INTO agent_cards
                (agent_id, agent_name, primary_function, secondary_functions, domain_tags, status)
            VALUES (?, ?, ?, ?, ?, 'active')
            """,
            (
                card["agent_id"],
                card["agent_name"],
                card["primary_function"],
                json.dumps(card["secondary_functions"], ensure_ascii=False),
                json.dumps(card["domain_tags"], ensure_ascii=False),
            ),
        )

        # 为每个function_tag初始化agent_performance（冷启动默认值）
        all_tags = [card["primary_function"]] + card["secondary_functions"]
        for tag in all_tags:
            conn.execute(
                """
                INSERT OR IGNORE INTO agent_performance
                    (agent_id, function_tag, accuracy, count, rework_rate, importance_score, is_suspended)
                VALUES (?, ?, 0.5, 0, 0.0, 0.5, 0)
                """,
                (card["agent_id"], tag),
            )

    logger.info(f"已写入 {len(AGENT_CARDS)} 个Agent卡片及对应performance记录")


if __name__ == "__main__":
    init_database()

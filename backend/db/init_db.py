"""数据库初始化脚本 - 创建全部13张表 + 种子数据

对应方案书 5.1.1 节 SQLite表结构
"""

from loguru import logger

from backend.db.database import get_connection, execute_sql
from backend.agents.agent_registry import AGENT_CARDS
from backend.config import get_settings


# ============================================================
# DDL: 12张表
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
        FOREIGN KEY(session_id) REFERENCES session(session_id),
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
        test_results        TEXT NOT NULL DEFAULT '[]',  -- JSON数组：理论测试成绩
        created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(session_id, version),
        FOREIGN KEY(session_id) REFERENCES session(session_id)
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

    # 10. 离线演示缓存表（P1-6，方案书附录E）
    # 现场无网络时，/api/ask 优先查此表命中则不走 LLM
    """
    CREATE TABLE IF NOT EXISTS demo_cache (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        question_hash TEXT NOT NULL UNIQUE,       -- sha256(normalized_question)
        question_text TEXT NOT NULL,              -- 原始问题（便于人工核对）
        answer_json   TEXT NOT NULL,              -- 完整 AskResponse 序列化
        profile_json  TEXT,                       -- 命中时的学情画像（可选）
        hit_count     INTEGER DEFAULT 0,
        created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,

    # 11a. 会话表（P1-7，方案书 7.4 节数据合规）
    # 会话隔离：按 session_id 隔离，不同学生数据互不可见
    # 正式纳入 init_db DDL（原由 compliance.py 运行时动态建，现统一管理）
    """
    CREATE TABLE IF NOT EXISTS session (
        session_id  TEXT PRIMARY KEY,
        created_at  TEXT
    )
    """,

    # 11b. 会话历史表（P1-7，方案书 7.4 节数据合规）
    # 数据保留：expires_at 到期自动清除（默认 30 天）
    # 注意：task_id 是 orchestrator 运行时生成的临时字符串 ID（如 task_xxx），
    #       不持久化到任何表，因此不设外键（原 REFERENCES demo_cache(id) 是错误定义）
    """
    CREATE TABLE IF NOT EXISTS conversations (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id  TEXT NOT NULL,
        task_id     TEXT,
        role        TEXT NOT NULL,                -- user / assistant / system
        content     TEXT NOT NULL,
        is_ai_generated BOOLEAN DEFAULT 0,        -- 标注 AI 生成内容
        created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        expires_at  TIMESTAMP NOT NULL,           -- 过期时间，cleanup 按此清理
        FOREIGN KEY(session_id) REFERENCES session(session_id)
    )
    """,

    # 12. 任务资源难度统计表（8.2.2 节可视化报告组件2数据源）
    # 记录每次任务的 quiz difficulty 分布，供"资源难度匹配曲线"读取
    """
    CREATE TABLE IF NOT EXISTS task_resource_stats (
        id                   INTEGER PRIMARY KEY AUTOINCREMENT,
        task_id              TEXT NOT NULL,
        session_id           TEXT NOT NULL,
        domain               TEXT,                  -- 涉及的知识领域（如 RAG）
        knowledge_level      TEXT,                  -- 学生当时水平 ENTRY/INTERMEDIATE/ADVANCED
        quiz_difficulties    TEXT,                  -- JSON: {"基础":2,"应用":1,"综合":1,"进阶":0}
        lecture_difficulty_note TEXT,               -- 讲义难度说明文本
        created_at           TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(session_id) REFERENCES session(session_id)
    )
    """,

    # 13. 任务指标表（第七部分量化指标验证数据源）
    # 记录每次任务的裁判裁决指标 + 审核评分，供 validate_metrics.py 读取
    # 对应方案书 7.1 节赛题指标映射 + 7.2.3 节验证方法
    """
    CREATE TABLE IF NOT EXISTS task_metrics (
        id                   INTEGER PRIMARY KEY AUTOINCREMENT,
        task_id              TEXT NOT NULL,
        session_id           TEXT NOT NULL,
        verdict              TEXT,                  -- passed/revise/low_confidence_passed/failed
        verification_rate    REAL,                  -- judge_verdict.overall_verification_rate (0-1)
        traceability_total   INTEGER DEFAULT 0,    -- 溯源标注总条数
        traceability_verified INTEGER DEFAULT 0,  -- 状态为"已验证"的条数
        knowledge_refs_count INTEGER DEFAULT 0,    -- 聚焦输出引用的知识库条目数
        fact_accuracy        REAL,                  -- Verifier 事实准确率 (0-1)
        logic_completeness   REAL,                  -- Skeptic 逻辑健全性 (0-1)
        pedagogical_fit      REAL,                  -- Evaluator 教学适配度 (0-1)
        review_score         REAL,                  -- 三项均值 (0-1)
        override_reason      TEXT,                  -- 强制放行原因（unanimous_fail_force_pass/revision_limit_force_pass）
        created_at           TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(session_id) REFERENCES session(session_id)
    )
    """,

    # 14. 生成资源落库表（事实比对指标 + 测试数据套装数据源）
    # 持久化每次任务最终生成的讲义/实操指南/测试题文本，供 validate_metrics.py
    # 结合 tests/test_cases_100.json 真值做事实比对（覆盖率/适配率），以及导出
    # "输入画像→最终生成资源"完整示例。仅在 /api/ask 返回层静默写入，不改生成逻辑、
    # 不增加调用时间。
    """
    CREATE TABLE IF NOT EXISTS task_resources (
        id                   INTEGER PRIMARY KEY AUTOINCREMENT,
        task_id              TEXT NOT NULL UNIQUE,  -- 与 task_metrics.task_id 对应
        session_id           TEXT NOT NULL,
        question             TEXT,                  -- 原始问题（便于与测试用例真值关联）
        lecture              TEXT,                  -- 讲义 Markdown 全文
        practice_guide       TEXT,                  -- 实操指南 Markdown 全文
        quiz                 TEXT,                  -- 测试题 JSON 全文
        knowledge_refs       TEXT,                  -- 溯源标注 JSON（权威来源）
        created_at           TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(session_id) REFERENCES session(session_id)
    )
    """,

    # 索引
    "CREATE INDEX IF NOT EXISTS idx_perf_agent_tag ON agent_performance(agent_id, function_tag)",
    "CREATE INDEX IF NOT EXISTS idx_resource_stats_session ON task_resource_stats(session_id)",
    "CREATE INDEX IF NOT EXISTS idx_metrics_session ON task_metrics(session_id)",
    "CREATE INDEX IF NOT EXISTS idx_memory_agent_tag ON contribution_memory(agent_id, function_tag)",
    "CREATE INDEX IF NOT EXISTS idx_profiles_session ON student_profiles(session_id)",
    "CREATE INDEX IF NOT EXISTS idx_feedback_session ON student_feedback(session_id)",
    "CREATE INDEX IF NOT EXISTS idx_demo_cache_hash ON demo_cache(question_hash)",
    "CREATE INDEX IF NOT EXISTS idx_conv_session ON conversations(session_id)",
    "CREATE INDEX IF NOT EXISTS idx_conv_expires ON conversations(expires_at)",
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

        # 安全加列（已有数据库兼容）
        _safe_add_column(conn, "task_metrics", "override_reason", "TEXT")
        _safe_add_column(conn, "student_profiles", "test_results", "TEXT")

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
    # P1-5: 连接复用模式，不主动 close（由连接池统一管理）


def _safe_add_column(conn, table: str, column: str, col_type: str):
    """安全加列：检查列是否存在，不存在才 ALTER TABLE（已有数据库兼容）"""
    cursor = conn.execute(f"PRAGMA table_info({table})")
    existing_cols = {row[1] for row in cursor.fetchall()}
    if column not in existing_cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
        conn.commit()
        logger.info(f"数据库迁移: {table} 加列 {column} {col_type}")


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

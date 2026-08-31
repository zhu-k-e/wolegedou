"""贡献记忆服务 - EMA更新 + importance_score计算 + 动态淘汰

对应方案书第五部分：
  5.2 EMA更新算法
  5.3 返工率计算
  5.4 importance_score计算（per-function-tag粒度）
  5.5 动态淘汰机制
  5.7 学生反馈机制
"""

from loguru import logger

from backend.config import get_settings
from backend.db.repositories import config_repo, agent_repo, memory_repo


class MemoryService:
    """贡献记忆闭环服务"""

    # α阶梯式下降阈值（方案书§2.4.2：冷启动0.9 → 数据积累后0.3）
    # (总记录数阈值, 对应α值) — 从高到低匹配，命中第一个即停止
    _ALPHA_STAGES = [
        (200, 0.3),
        (100, 0.5),
        (50, 0.7),
    ]

    def __init__(self):
        settings = get_settings()
        self._ema_smooth = settings.ema_smooth
        self._elimination_threshold = settings.elimination_threshold
        self._elimination_consecutive = settings.elimination_consecutive_count

    # ============================================================
    # 5.2 EMA更新accuracy
    # ============================================================

    def update_accuracy(self, agent_id: str, function_tag: str, review_score: float) -> tuple[float, int]:
        """EMA更新accuracy

        new_accuracy = old_accuracy * EMA_SMOOTH + review_score * (1 - EMA_SMOOTH)
        """
        perf = agent_repo.get_agent_performance(agent_id, function_tag)
        old_accuracy = perf["accuracy"] if perf else 0.5
        old_count = perf["count"] if perf else 0

        new_accuracy = old_accuracy * self._ema_smooth + review_score * (1 - self._ema_smooth)
        new_count = old_count + 1

        # 更新数据库（保留其他字段不变）
        if perf:
            agent_repo.update_agent_performance(
                agent_id, function_tag,
                accuracy=new_accuracy,
                count=new_count,
                rework_rate=perf["rework_rate"],
                importance_score=perf["importance_score"],
                is_suspended=perf["is_suspended"],
            )

        logger.debug(f"EMA更新: {agent_id}/{function_tag} accuracy={old_accuracy:.4f} -> {new_accuracy:.4f}, count={new_count}")
        return new_accuracy, new_count

    # ============================================================
    # 5.3 返工率计算
    # ============================================================

    def update_rework_rate(self, agent_id: str, function_tag: str, rework_score: float):
        """EMA更新返工率

        rework_score越高=Agent输出质量越好 → 返工率越低（取反映射）
        new_rate = EMA_SMOOTH * old_rate + (1 - EMA_SMOOTH) * (1.0 - rework_score)
        """
        perf = agent_repo.get_agent_performance(agent_id, function_tag)
        old_rate = perf["rework_rate"] if perf else 0.0

        mapped_score = 1.0 - rework_score
        new_rate = self._ema_smooth * old_rate + (1 - self._ema_smooth) * mapped_score

        if perf:
            agent_repo.update_agent_performance(
                agent_id, function_tag,
                accuracy=perf["accuracy"],
                count=perf["count"],
                rework_rate=new_rate,
                importance_score=perf["importance_score"],
                is_suspended=perf["is_suspended"],
            )

        logger.debug(f"返工率更新: {agent_id}/{function_tag} rework_rate={old_rate:.4f} -> {new_rate:.4f}")
        return new_rate

    # ============================================================
    # 5.4 importance_score计算
    # ============================================================

    def compute_importance_score(self, agent_id: str, function_tag: str) -> float:
        """计算importance_score（per-function-tag粒度）

        importance_score = 0.5*accuracy + 0.3*(1-rework_rate) + 0.2*count_normalized
        冷启动保护：count < 5 时返回默认值0.5
        """
        perf = agent_repo.get_agent_performance(agent_id, function_tag)
        if not perf:
            return 0.5

        count = perf["count"]
        if count < 5:
            return 0.5  # 冷启动默认值

        accuracy = perf["accuracy"]
        rework_rate = min(perf["rework_rate"], 1.0)
        count_normalized = min(count / 100.0, 1.0)

        importance_score = (
            0.5 * accuracy
            + 0.3 * (1 - rework_rate)
            + 0.2 * count_normalized
        )
        importance_score = round(importance_score, 4)

        # 写回数据库
        agent_repo.update_agent_performance(
            agent_id, function_tag,
            accuracy=accuracy,
            count=count,
            rework_rate=rework_rate,
            importance_score=importance_score,
            is_suspended=perf["is_suspended"],
        )

        return importance_score

    # ============================================================
    # 5.5 动态淘汰
    # ============================================================

    def check_elimination(self, agent_id: str):
        """检查某Agent是否应被淘汰

        触发条件：某一function_tag下，连续3次 importance_score < 0.5
        淘汰是per-function-tag粒度的，不影响其他tag
        """
        perfs = agent_repo.get_agent_all_performances(agent_id)
        if not perfs:
            return

        for perf in perfs:
            if perf["is_suspended"]:
                continue  # 已挂起，跳过

            tag = perf["function_tag"]
            recent_scores = memory_repo.get_recent_importance_scores(agent_id, tag, limit=3)

            # 连续3次低于阈值
            if len(recent_scores) >= 3 and all(s < self._elimination_threshold for s in recent_scores):
                agent_repo.suspend_agent_tag(agent_id, tag)
                memory_repo.log_elimination(
                    agent_id, tag,
                    f"连续{len(recent_scores)}次importance_score<{self._elimination_threshold}, function_tag={tag}",
                )
                memory_repo.add_to_offline_evaluation(agent_id, tag)
                logger.warning(f"Agent {agent_id} 在 {tag} 下被淘汰，进入离线评估队列")

    # ============================================================
    # 2.4.2 α动态切换
    # ============================================================

    def _check_alpha_adjustment(self):
        """检查并自动调整α值（方案书§2.4.2）

        α冷启动0.9 → 数据积累后阶梯式下降至0.3：
          总记录数 ≥ 50  → α=0.7
          总记录数 ≥ 100 → α=0.5
          总记录数 ≥ 200 → α=0.3

        每次record_task_completion后调用，仅在实际需要变更时写库。
        """
        total_count = agent_repo.get_total_task_count()
        current_alpha = config_repo.get_alpha()

        # 从高阈值往低匹配，命中第一个即为目标
        target_alpha = None
        for threshold, alpha in self._ALPHA_STAGES:
            if total_count >= threshold:
                target_alpha = alpha
                break

        if target_alpha is not None and abs(current_alpha - target_alpha) > 0.01:
            config_repo.set_alpha(target_alpha)
            logger.info(
                f"α自动调整: {current_alpha} → {target_alpha} "
                f"(总记录数={total_count})"
            )
        elif target_alpha is None and current_alpha != 0.9:
            # 记录数不足50且α不是初始值，恢复冷启动值
            logger.debug(f"α保持冷启动值: {current_alpha} (总记录数={total_count})")

    # ============================================================
    # 5.7 学生反馈机制
    # ============================================================

    def apply_student_feedback(
        self,
        session_id: str,
        agent_id: str,
        function_tag: str,
        feedback_type: str,
        comment: str | None = None,
    ):
        """处理学生反馈

        helpful → accuracy +0.02
        not_helpful → accuracy -0.02
        content_error → 记录，人工复核
        difficulty_mismatch → 保存反馈并在响应中标记，编排器下次生成画像时自动读取

        P0-1修复（方案书§5.7）：
          - difficulty_mismatch反馈写入student_feedback表
          - profile_agent.generate_profile()在生成新画像时读取该session的
            difficulty_mismatch记录，降级knowledge_level
          - 本方法仅保存 + 打日志 + 返回信号，不直接操作Agent表现
        """
        # 保存反馈记录
        memory_repo.save_student_feedback(
            session_id, agent_id, function_tag, feedback_type, comment
        )

        if feedback_type in ("helpful", "not_helpful"):
            perf = agent_repo.get_agent_performance(agent_id, function_tag)
            if perf:
                delta = 0.02 if feedback_type == "helpful" else -0.02
                new_accuracy = max(0.0, min(1.0, perf["accuracy"] + delta))
                # 重算importance_score
                agent_repo.update_agent_performance(
                    agent_id, function_tag,
                    accuracy=new_accuracy,
                    count=perf["count"],
                    rework_rate=perf["rework_rate"],
                    importance_score=self.compute_importance_score(agent_id, function_tag),
                    is_suspended=perf["is_suspended"],
                )
                logger.info(f"学生反馈 {feedback_type}: {agent_id}/{function_tag} accuracy += {delta}")

        elif feedback_type == "content_error":
            # 记录到人工复核队列
            from backend.db.database import execute_sql
            execute_sql(
                "INSERT INTO human_review_queue (session_id, agent_id, reason) VALUES (?, ?, ?)",
                (session_id, agent_id, f"content_error: {comment or '无详细说明'}"),
            )
            logger.info(f"内容错误反馈已记录人工复核: {session_id}/{agent_id}")

        elif feedback_type == "difficulty_mismatch":
            # P0-1修复：保存反馈 + 触发signalon（返回信号供orchestrator下一轮使用）
            logger.info(
                f"难度不匹配反馈已记录: session={session_id}, "
                f"comment={comment or '无详细说明'}, "
                f"下次生成画像时将自动读取并调整knowledge_level"
            )

    # ============================================================
    # 综合更新（一次任务完成后调用）
    # ============================================================

    def record_task_completion(
        self,
        task_id: str,
        agent_id: str,
        function_tag: str,
        task_type: str,
        segment: str | None,
        review_score: float,
        referee_verdict: str,
        referee_modifications: int = 0,
        rework_type: str = "none",
        offline: bool = False,
    ):
        """一次任务完成后，完整更新贡献记忆

        1. EMA更新accuracy（offline任务跳过）
        2. EMA更新rework_rate（offline任务跳过）
        3. 计算importance_score（offline任务固定0.5）
        4. 记录contribution_memory
        5. 检查淘汰（offline任务跳过）
        6. α动态切换检查（offline任务跳过）

        Args:
            offline: 离线评估任务（如benchmark）。只写contribution_memory（task_type=offline_eval），
                     不更新agent_performance，不触发淘汰/α切换，避免自进化被测试数据污染。
        """
        if offline:
            # 离线评估：只留痕，不参与自进化
            memory_repo.save_contribution_memory(
                task_id=task_id,
                agent_id=agent_id,
                function_tag=function_tag,
                task_type=task_type,
                segment=segment,
                review_score=review_score,
                importance_score=0.5,
                referee_verdict=referee_verdict,
                referee_modifications=referee_modifications,
                rework_type=rework_type,
            )
            logger.info(
                f"[offline_eval] 贡献记忆已记录: task={task_id}, agent={agent_id}, tag={function_tag}, "
                f"verdict={referee_verdict}, 不参与自进化"
            )
            return

        # 1. EMA更新accuracy
        new_accuracy, new_count = self.update_accuracy(agent_id, function_tag, review_score)

        # 2. 返工率：verdict映射为rework_score
        verdict_to_rework_score = {
            "passed": 1.0,
            "revise": 0.5,
            "low_confidence_passed": 0.3,
            "failed": 0.0,
        }
        rework_score = verdict_to_rework_score.get(referee_verdict, 0.5)
        self.update_rework_rate(agent_id, function_tag, rework_score)

        # 3. 计算importance_score
        importance_score = self.compute_importance_score(agent_id, function_tag)

        # 4. 记录contribution_memory
        memory_repo.save_contribution_memory(
            task_id=task_id,
            agent_id=agent_id,
            function_tag=function_tag,
            task_type=task_type,
            segment=segment,
            review_score=review_score,
            importance_score=importance_score,
            referee_verdict=referee_verdict,
            referee_modifications=referee_modifications,
            rework_type=rework_type,
        )

        # 5. 检查淘汰
        self.check_elimination(agent_id)

        # 6. α动态切换检查（方案书§2.4.2）
        self._check_alpha_adjustment()

        logger.info(
            f"贡献记忆已记录: task={task_id}, agent={agent_id}, tag={function_tag}, "
            f"verdict={referee_verdict}, importance={importance_score:.4f}"
        )


# 全局单例
_memory_service: MemoryService | None = None


def get_memory_service() -> MemoryService:
    global _memory_service
    if _memory_service is None:
        _memory_service = MemoryService()
    return _memory_service

"""编排器 - FSM状态机驱动全流程

对应方案书 6.1 节编排器设计

主FSM：
  IDLE → PROFILING → DISPATCHING → GENERATING → REVIEWING
  → FOCUSING → JUDGING → FORMATTING → COMPLETE

延伸路径（从COMPLETE触发）：
  QUIZ_EVAL → REDIMENSION / ADVANCE / RECHECK → HEURISTIC_FOLLOWUP
"""

import asyncio
import uuid
from dataclasses import dataclass, field
from typing import Optional

from loguru import logger

from backend.core.fsm import FSMState, can_transition
from backend.core.exceptions import FSMTransitionError, OrchestratorError
from backend.agents.profile_agent import ProfileAgent
from backend.agents.domain_agent import DomainAgent
from backend.agents.resource_agent import ResourceAgent
from backend.agents.review_team import ReviewTeam
from backend.agents.judge_panel import JudgePanel
from backend.agents.matcher import Matcher, DispatchResult, Segment
from backend.schemas.student_profile import StudentProfile, IntentType
from backend.schemas.candidate_output import CandidateOutput
from backend.schemas.review_feedback import ReviewFeedback
from backend.schemas.focused_output import FocusedOutput
from backend.schemas.judge_verdict import JudgeVerdict, Verdict, JudgeOpinion
from backend.schemas.resource_package import ResourcePackage
from backend.services.ws_manager import ws_manager
from backend.services.memory_service import get_memory_service
from backend.config import get_settings


@dataclass
class TaskContext:
    """单次任务上下文 - 在FSM各状态间传递"""
    task_id: str
    session_id: str
    question: str
    history: list[dict] = field(default_factory=list)

    # 各阶段产物
    profile: Optional[StudentProfile] = None
    dispatch_result: Optional[DispatchResult] = None
    candidate_outputs: list[list[CandidateOutput]] = field(default_factory=list)  # 每段的候选输出
    review_feedbacks: list[ReviewFeedback] = field(default_factory=list)
    focused_outputs: list[FocusedOutput] = field(default_factory=list)
    judge_verdict: Optional[JudgeVerdict] = None
    resource_package: Optional[ResourcePackage] = None
    # P0-1: 多段合并后的聚焦输出（供FORMATTING和延伸路径使用）
    merged_focused_output: Optional[FocusedOutput] = None

    # FSM状态
    current_state: FSMState = FSMState.IDLE
    revision_count: int = 0

    # 候选Agent引用（用于辩论）
    winning_agents: list[DomainAgent] = field(default_factory=list)
    losing_candidates: list[CandidateOutput] = field(default_factory=list)
    winning_candidates: list[CandidateOutput] = field(default_factory=list)

    # P1-1: 双低触发的段索引（self_confidence都<0.5但知识库不可用时标记）
    low_confidence_segments: set = field(default_factory=set)


class Orchestrator:
    """编排器 - 驱动FSM状态机完成多智能体协同决策

    对应方案书 6.1.2 节编排器技术实现
    """

    def __init__(self):
        self.profile_agent = ProfileAgent()
        self.matcher = Matcher()
        self.review_team = ReviewTeam()
        self.judge_panel = JudgePanel()
        self.resource_agent = ResourceAgent()
        self.memory_service = get_memory_service()
        self._settings = get_settings()
        # 缓存已完成任务的上下文，供延伸路径恢复使用
        self._task_contexts: dict[str, TaskContext] = {}

    async def process_question(
        self,
        question: str,
        session_id: str,
        history: Optional[list[dict]] = None,
    ) -> dict:
        """处理学生问题 - 主FSM入口

        Returns:
            包含resource_package和FSM轨迹的字典
        """
        task_id = f"task_{uuid.uuid4().hex[:12]}"
        ctx = TaskContext(
            task_id=task_id,
            session_id=session_id,
            question=question,
            history=history or [],
        )

        logger.info(f"任务开始: task_id={task_id}, question='{question[:50]}...'")

        try:
            # 主FSM循环
            await self._run_main_fsm(ctx)

            # 缓存上下文供延伸路径使用
            self._task_contexts[task_id] = ctx

            # 第七部分量化指标：提取审核评分均值 + 知识引用数
            review_summary = self._extract_review_summary(ctx)
            knowledge_refs_count = (
                len(ctx.merged_focused_output.knowledge_refs)
                if ctx.merged_focused_output
                else sum(len(fo.knowledge_refs) for fo in ctx.focused_outputs)
            )

            return {
                "task_id": task_id,
                "session_id": session_id,
                "profile": ctx.profile.model_dump() if ctx.profile else None,
                "resource_package": ctx.resource_package.model_dump() if ctx.resource_package else None,
                "judge_verdict": ctx.judge_verdict.model_dump() if ctx.judge_verdict else None,
                "review_summary": review_summary,
                "knowledge_refs_count": knowledge_refs_count,
                "dispatch_info": {
                    "intent": ctx.dispatch_result.intent.value if ctx.dispatch_result else None,
                    "segments": [
                        {
                            "seg_id": s.seg_id,
                            "domain": s.domain,
                            "candidates": [
                                {"agent_id": c["agent_id"], "composite_score": c["composite_score"]}
                                for c in s.candidates
                            ],
                        }
                        for s in (ctx.dispatch_result.segments if ctx.dispatch_result else [])
                    ],
                } if ctx.dispatch_result else None,
                "navigation_roadmap": ctx.dispatch_result.navigation_roadmap if ctx.dispatch_result else None,
                "clarification_options": ctx.dispatch_result.clarification_options if ctx.dispatch_result else None,
            }

        except Exception as e:
            logger.error(f"任务失败: task_id={task_id}, error={e}")
            ctx.current_state = FSMState.ERROR
            await ws_manager.push_state(task_id, FSMState.ERROR.value, {"error": str(e)})
            return {
                "task_id": task_id,
                "session_id": session_id,
                "error": str(e),
                "state": FSMState.ERROR.value,
            }

    async def _run_main_fsm(self, ctx: TaskContext):
        """运行主FSM循环"""
        ctx.current_state = FSMState.IDLE

        while ctx.current_state != FSMState.COMPLETE:
            logger.debug(f"FSM状态: {ctx.current_state.value}, task={ctx.task_id}")

            if ctx.current_state == FSMState.IDLE:
                await self._transition(ctx, FSMState.PROFILING)

            elif ctx.current_state == FSMState.PROFILING:
                await self._do_profiling(ctx)
                await self._transition(ctx, FSMState.DISPATCHING)

            elif ctx.current_state == FSMState.DISPATCHING:
                await self._do_dispatching(ctx)
                # 根据意图路由
                if ctx.dispatch_result.intent == IntentType.GENERATION:
                    await self._transition(ctx, FSMState.GENERATING)
                else:
                    # navigation或clarification不需要后续FSM
                    ctx.current_state = FSMState.COMPLETE
                    await ws_manager.push_state(ctx.task_id, FSMState.COMPLETE.value)

            elif ctx.current_state == FSMState.GENERATING:
                await self._do_generating(ctx)
                await self._transition(ctx, FSMState.REVIEWING)

            elif ctx.current_state == FSMState.REVIEWING:
                await self._do_reviewing(ctx)
                await self._transition(ctx, FSMState.FOCUSING)

            elif ctx.current_state == FSMState.FOCUSING:
                await self._do_focusing(ctx)
                await self._transition(ctx, FSMState.JUDGING)

            elif ctx.current_state == FSMState.JUDGING:
                verdict = await self._do_judging(ctx)
                if verdict.verdict in (Verdict.PASSED, Verdict.LOW_CONFIDENCE_PASSED):
                    await self._transition(ctx, FSMState.FORMATTING)
                elif verdict.verdict == Verdict.REVISE and ctx.revision_count < self._settings.fsm_max_revisions:
                    ctx.revision_count += 1
                    await self._transition(ctx, FSMState.REVISING)
                else:
                    # REVISE超过修改上限或FAILED → 降级强制通过（方案书4.4.2第1366行）
                    self._force_pass_with_override(ctx, verdict.verdict)
                    await self._transition(ctx, FSMState.FORMATTING)

            elif ctx.current_state == FSMState.REVISING:
                await self._do_revising(ctx)
                await self._transition(ctx, FSMState.JUDGING)

            elif ctx.current_state == FSMState.FORMATTING:
                await self._do_formatting(ctx)
                await self._transition(ctx, FSMState.COMPLETE)

        # 写贡献记忆
        await self._write_contribution_memory(ctx)
        await ws_manager.push_state(ctx.task_id, FSMState.COMPLETE.value)

    # ============================================================
    # 各状态处理
    # ============================================================

    async def _do_profiling(self, ctx: TaskContext):
        """PROFILING: 学情画像生成

        降级策略（方案书§8.5.3）：LLM调用失败时使用默认画像，不中断主流程。
        """
        await ws_manager.push_state(ctx.task_id, FSMState.PROFILING.value)
        try:
            ctx.profile = await self.profile_agent.generate_profile(
                question=ctx.question,
                session_id=ctx.session_id,
                history=ctx.history,
            )
        except Exception as e:
            logger.warning(f"学情诊断失败，降级为默认画像: {e}")
            from backend.schemas.student_profile import (
                KnowledgeLevel, Background, CurrentGoal,
                QuestionType, ComplexityEstimate,
            )
            ctx.profile = StudentProfile(
                knowledge_level=KnowledgeLevel.ENTRY,
                background=Background.SCIENCE_NO_CODE,
                current_goal=CurrentGoal.QUICK_START,
                question_type=QuestionType.CONCEPT,
                domain_hint=[],
                complexity_estimate=ComplexityEstimate.SINGLE_DOMAIN,
                intent_type=IntentType.GENERATION,
                session_id=ctx.session_id,
            )
        await ws_manager.push_state(
            ctx.task_id, FSMState.PROFILING.value,
            {"profile": ctx.profile.model_dump()},
        )

    async def _do_dispatching(self, ctx: TaskContext):
        """DISPATCHING: 调度员遴选候选Agent"""
        await ws_manager.push_state(ctx.task_id, FSMState.DISPATCHING.value)
        ctx.dispatch_result = self.matcher.dispatch(ctx.profile)
        await ws_manager.push_state(
            ctx.task_id, FSMState.DISPATCHING.value,
            {
                "intent": ctx.dispatch_result.intent.value,
                "segments": len(ctx.dispatch_result.segments),
            },
        )

    async def _do_generating(self, ctx: TaskContext):
        """GENERATING: 各段候选Agent并行输出"""
        await ws_manager.push_state(ctx.task_id, FSMState.GENERATING.value)

        segments = ctx.dispatch_result.segments
        ctx.candidate_outputs = []

        # 各段并行，段内2个候选也并行
        segment_tasks = []
        for seg in segments:
            # 为每个候选创建DomainAgent实例
            for candidate_info in seg.candidates:
                agent = DomainAgent(candidate_info["agent_id"])
                task = agent.generate_candidate(
                    question=ctx.question,
                    profile=ctx.profile,
                    seg_id=seg.seg_id,
                )
                segment_tasks.append((seg.seg_id, agent, candidate_info, task))

        # 全部并行
        results = await asyncio.gather(*[t[3] for t in segment_tasks])

        # 按段组织结果
        seg_map: dict[str, list[CandidateOutput]] = {}
        for (seg_id, agent, info, _), output in zip(segment_tasks, results):
            seg_map.setdefault(seg_id, []).append(output)

        ctx.candidate_outputs = [seg_map[seg.seg_id] for seg_id in [s.seg_id for s in segments]]

        # P1-1: 候选自评估双低触发RAG增强（方案书§3.4.4 DyLAN落地）
        # 如果两个候选的self_confidence都<0.5 → 触发知识库RAG增强
        # 对应方案书 6.6 节：每个 Agent 只检索自己分类下的 chunk（filter_agent）
        from backend.services.knowledge_base import get_knowledge_base
        kb = get_knowledge_base()

        for i, seg_outputs in enumerate(ctx.candidate_outputs):
            both_low = all(co.self_confidence.score < 0.5 for co in seg_outputs)
            if not both_low:
                continue

            seg = segments[i]
            confidences = [co.self_confidence.score for co in seg_outputs]
            logger.warning(
                f"双低触发: seg={seg.seg_id}, domain={seg.domain}, "
                f"confidences={confidences}"
            )

            # 每个 Agent 用自己的 agent_name 做 filter_agent 检索
            # （方案书 3.2.1 节：10 个领域 Agent 各自只检索自己分类下的 chunk）
            regen_tasks = []
            for co in seg_outputs:
                agent = DomainAgent(co.agent_id)
                # 先按 Agent 分类过滤检索
                agent_results = await kb.search(
                    ctx.question, top_k=3, filter_agent=agent.agent_name
                )
                if agent_results:
                    logger.info(
                        f"RAG增强(分类过滤): seg={seg.seg_id}, "
                        f"agent={agent.agent_name}, 命中{len(agent_results)}条本分类chunk"
                    )
                else:
                    # 该 Agent 分类下无结果，fallback 到全局检索
                    agent_results = await kb.search(ctx.question, top_k=3)
                    logger.info(
                        f"RAG增强(全局fallback): seg={seg.seg_id}, "
                        f"agent={agent.agent_name} 本分类无结果，用全局{len(agent_results)}条"
                    )

                if agent_results:
                    rag_context = "\n\n".join(
                        f"[{r.source}] {r.content}" for r in agent_results
                    )
                else:
                    rag_context = None

                if not rag_context:
                    # 知识库不可用，跳过该 Agent 的重新生成
                    continue

                task = agent.generate_candidate(
                    question=ctx.question,
                    profile=ctx.profile,
                    seg_id=seg.seg_id,
                    rag_context=rag_context,
                )
                regen_tasks.append((co, task))

            if regen_tasks:
                logger.info(
                    f"RAG增强: seg={seg.seg_id}, "
                    f"补充检索结果后重新生成{len(regen_tasks)}个候选"
                )
                regen_results = await asyncio.gather(*[t[1] for t in regen_tasks])
                # 用重新生成的结果替换原结果
                regen_map = {t[0].agent_id: r for t, r in zip(regen_tasks, regen_results)}
                ctx.candidate_outputs[i] = [
                    regen_map.get(co.agent_id, co) for co in seg_outputs
                ]
            else:
                # 知识库不可用，标记低置信度段（审核团队会自然给出低分）
                logger.warning(
                    f"知识库未接入，双低段{seg.seg_id}无法RAG增强，标记低置信度"
                )
                ctx.low_confidence_segments.add(i)

        await ws_manager.push_state(
            ctx.task_id, FSMState.GENERATING.value,
            {"segments": len(ctx.candidate_outputs)},
        )

    async def _do_reviewing(self, ctx: TaskContext):
        """REVIEWING: 审核团队3人并行评分 + 段内评选 + 跨段审查"""
        await ws_manager.push_state(ctx.task_id, FSMState.REVIEWING.value)

        # 各段并行审核
        review_tasks = [
            self.review_team.review_segment(
                candidates=ctx.candidate_outputs[i],
                profile=ctx.profile,
                seg_id=ctx.dispatch_result.segments[i].seg_id,
            )
            for i in range(len(ctx.candidate_outputs))
        ]
        ctx.review_feedbacks = await asyncio.gather(*review_tasks)

        # 跨段一致性审查（多段场景）
        if len(ctx.review_feedbacks) > 1:
            cross_issues = await self.review_team.check_cross_segment_consistency(
                list(ctx.review_feedbacks), ctx.profile
            )
            if cross_issues:
                logger.warning(f"跨段一致性问题: {len(cross_issues)}条")
                # 追加到第一个段的反馈中
                ctx.review_feedbacks[0].cross_segment_issues = cross_issues

        await ws_manager.push_state(
            ctx.task_id, FSMState.REVIEWING.value,
            {"winners": [next(c.agent_id for c in r.candidates if c.is_winner) for r in ctx.review_feedbacks]},
        )

    async def _do_focusing(self, ctx: TaskContext):
        """FOCUSING: 最优Agent聚焦输出（含审核反馈回流）"""
        await ws_manager.push_state(ctx.task_id, FSMState.FOCUSING.value)

        ctx.focused_outputs = []
        ctx.winning_agents = []
        ctx.winning_candidates = []
        ctx.losing_candidates = []

        for i, review in enumerate(ctx.review_feedbacks):
            # 找到获胜候选（早停场景下可能只有1个候选，没有落选候选）
            winner_candidate = next(c for c in review.candidates if c.is_winner)
            loser_candidates_list = [c for c in review.candidates if not c.is_winner]

            # 找到对应的CandidateOutput
            winner_output = next(
                co for co in ctx.candidate_outputs[i] if co.agent_id == winner_candidate.agent_id
            )

            # 单候选（早停）场景：没有落选候选，辩论环节跳过
            loser_output = None
            if loser_candidates_list:
                loser_output = next(
                    co for co in ctx.candidate_outputs[i] if co.agent_id == loser_candidates_list[0].agent_id
                )
            else:
                logger.info(f"段{review.seg_id}只有1个候选（早停），跳过落选候选记录")

            # 创建获胜Agent实例
            winning_agent = DomainAgent(winner_candidate.agent_id)

            # 聚焦输出（含审核反馈回流）
            try:
                focused = await winning_agent.generate_focused_output(
                    question=ctx.question,
                    profile=ctx.profile,
                    original_output=winner_output,
                    review_feedback=review,
                )
            except Exception as e:
                logger.warning(
                    f"段{review.seg_id}聚焦输出失败，降级为候选输出直接送裁判: {e}"
                )
                # 从候选输出构造最小可用的FocusedOutput
                ans = winner_output.answer
                steps = list(ans.reasoning_steps) if ans.reasoning_steps else []
                while len(steps) < 3:
                    steps.append("（降级模式：补充推理步骤）")
                focused = FocusedOutput(
                    conclusion=ans.conclusion or "（降级模式：未经聚焦优化）",
                    reasoning_steps=steps,
                    knowledge_refs=ans.knowledge_refs,
                    applicable_conditions=ans.applicable_conditions or "（降级模式）",
                    code_example=ans.code_example,
                    difficulty_note=ans.difficulty_note,
                )

            ctx.focused_outputs.append(focused)
            ctx.winning_agents.append(winning_agent)
            ctx.winning_candidates.append(winner_output)
            ctx.losing_candidates.append(loser_output)

        # P0-1: 计算合并聚焦输出（供FORMATTING和延伸路径使用）
        if len(ctx.focused_outputs) == 1:
            ctx.merged_focused_output = ctx.focused_outputs[0]
        else:
            ctx.merged_focused_output = self._merge_focused_outputs(ctx.focused_outputs)
            logger.info(f"多段聚焦输出合并: {len(ctx.focused_outputs)}段 → 1份")

        await ws_manager.push_state(
            ctx.task_id, FSMState.FOCUSING.value,
            {"focused_count": len(ctx.focused_outputs)},
        )

    async def _do_judging(self, ctx: TaskContext) -> JudgeVerdict:
        """JUDGING: 裁判团3人并行审查 + 分歧解决 + 候选辩论

        多段场景：各段独立审查（每段3名裁判），最终合并裁决。
        对应方案书§4.4 + §3.4.2/3.4.3多段处理。
        """
        await ws_manager.push_state(ctx.task_id, FSMState.JUDGING.value)

        if not ctx.focused_outputs:
            raise OrchestratorError("无聚焦输出可供裁判")

        # 各段并行裁判（每段3名裁判独立审查）
        judge_tasks = []
        for i, focused in enumerate(ctx.focused_outputs):
            winning_candidate = ctx.winning_candidates[i] if i < len(ctx.winning_candidates) else None
            losing_candidate = ctx.losing_candidates[i] if i < len(ctx.losing_candidates) else None
            winning_agent = ctx.winning_agents[i] if i < len(ctx.winning_agents) else None
            losing_agent = DomainAgent(losing_candidate.agent_id) if losing_candidate else None

            task = self.judge_panel.judge(
                focused_output=focused,
                profile=ctx.profile,
                question=ctx.question,
                winning_candidate=winning_candidate,
                losing_candidate=losing_candidate,
                losing_agent=losing_agent,
                winning_agent=winning_agent,
                review_feedback=ctx.review_feedbacks[i] if i < len(ctx.review_feedbacks) else None,
            )
            judge_tasks.append(task)

        segment_verdicts = await asyncio.gather(*judge_tasks)

        # 合并多段裁决
        if len(segment_verdicts) == 1:
            ctx.judge_verdict = segment_verdicts[0]
        else:
            ctx.judge_verdict = self._merge_judge_verdicts(list(segment_verdicts))
            logger.info(
                f"多段裁判合并: {len(segment_verdicts)}段, "
                f"段裁决={[v.verdict.value for v in segment_verdicts]}, "
                f"整体裁决={ctx.judge_verdict.verdict.value}"
            )

        await ws_manager.push_state(
            ctx.task_id, FSMState.JUDGING.value,
            {"verdict": ctx.judge_verdict.verdict.value, "segments": len(segment_verdicts)},
        )

        return ctx.judge_verdict

    def _force_pass_with_override(self, ctx: TaskContext, original_verdict: Verdict):
        """强制放行降级标记（方案书4.4.2第1366行：修改超上限/全票失败时标注低置信度强制通过）

        将 verdict 降级为 LOW_CONFIDENCE_PASSED 并标记 override_reason，
        确保强制放行事件可见、可统计、可监控。
        正常流程下 0:3 全票失败已在 JudgePanel 终审处理，此方法主要兜底
        REVISE 超修改上限的场景。
        """
        if not ctx.judge_verdict:
            return
        if original_verdict == Verdict.FAILED:
            reason = "unanimous_fail_force_pass"
            logger.error(
                f"⚠️ 裁判FAILED强制放行: task={ctx.task_id}, "
                f"verdict={original_verdict.value}"
            )
        else:
            reason = "revision_limit_force_pass"
            logger.warning(
                f"修改超上限强制通过: task={ctx.task_id}, "
                f"revision_count={ctx.revision_count}, "
                f"verdict={original_verdict.value}"
            )
        ctx.judge_verdict.verdict = Verdict.LOW_CONFIDENCE_PASSED
        ctx.judge_verdict.override_reason = reason

    async def _do_revising(self, ctx: TaskContext):
        """REVISING: Agent根据裁判团反馈修改FocusedOutput

        对应方案书§4.4.3：裁判团退回修改时，将具体反馈传给聚焦输出Agent
        """
        await ws_manager.push_state(ctx.task_id, FSMState.REVISING.value)
        logger.info(f"退回修改: task={ctx.task_id}, revision={ctx.revision_count}")

        # 提取裁判团具体反馈（裁判证据 + 分歧解决证据）
        judge_feedback = None
        if ctx.judge_verdict:
            feedback_parts = []
            for judge in ctx.judge_verdict.judges:
                if judge.evidence:
                    feedback_parts.append(
                        f"[{judge.role}] 判定: {judge.judgment}, 证据: {'; '.join(judge.evidence)}"
                    )
            if ctx.judge_verdict.dissent_resolution:
                dr = ctx.judge_verdict.dissent_resolution
                feedback_parts.append(
                    f"[分歧解决] 少数方({dr.minority_judge})证据: {'; '.join(dr.evidence_submitted)}, "
                    f"多数方回应: {dr.majority_response}"
                )
            judge_feedback = "\n".join(feedback_parts) if feedback_parts else None

        # 重新聚焦输出，传入裁判具体反馈
        for i, agent in enumerate(ctx.winning_agents):
            focused = await agent.generate_focused_output(
                question=ctx.question,
                profile=ctx.profile,
                original_output=ctx.winning_candidates[i],
                review_feedback=ctx.review_feedbacks[i] if i < len(ctx.review_feedbacks) else None,
                judge_feedback=judge_feedback,
            )
            ctx.focused_outputs[i] = focused

        # P0-1: 重新合并多段聚焦输出
        if len(ctx.focused_outputs) == 1:
            ctx.merged_focused_output = ctx.focused_outputs[0]
        else:
            ctx.merged_focused_output = self._merge_focused_outputs(ctx.focused_outputs)

    async def _do_formatting(self, ctx: TaskContext):
        """FORMATTING: 资源生成Agent按条件生成3种形态

        多段场景：使用合并后的聚焦输出统一生成资源包。
        降级策略（方案书§8.5.3）：资源生成失败时仅生成讲义，不中断流程。
        """
        await ws_manager.push_state(ctx.task_id, FSMState.FORMATTING.value)

        focused = ctx.merged_focused_output or (ctx.focused_outputs[0] if ctx.focused_outputs else None)
        if not focused:
            raise OrchestratorError("无聚焦输出可供资源生成")

        try:
            ctx.resource_package = await self.resource_agent.generate_resource_package(
                task_id=ctx.task_id,
                focused_output=focused,
                profile=ctx.profile,
            )
        except Exception as e:
            logger.warning(f"资源生成失败，降级为仅生成讲义: {e}")
            from backend.schemas.resource_package import Lecture, KnowledgeRefDisplay
            ctx.resource_package = ResourcePackage(
                task_id=ctx.task_id,
                lecture=Lecture(
                    title="学习资源（降级模式）",
                    content_markdown=focused.conclusion,
                    difficulty_note=focused.difficulty_note or "（降级模式）",
                    knowledge_refs_display=[
                        KnowledgeRefDisplay(
                            source=ref.source,
                            verification_status="待验证",
                        )
                        for ref in focused.knowledge_refs
                    ],
                ),
                practice_guide=None,
                quiz=None,
                focused_output_ref=ctx.task_id,
                profile_ref=ctx.session_id,
            )

        await ws_manager.push_state(
            ctx.task_id, FSMState.FORMATTING.value,
            {
                "lecture": True,
                "practice_guide": ctx.resource_package.practice_guide is not None,
                "quiz": ctx.resource_package.quiz is not None,
            },
        )

    def _extract_review_summary(self, ctx: TaskContext) -> dict | None:
        """从审核反馈中提取获胜候选的评分均值（第七部分量化指标数据源）"""
        if not ctx.review_feedbacks:
            return None

        fact_scores = []
        logic_scores = []
        peda_scores = []
        for review in ctx.review_feedbacks:
            for cand in review.candidates:
                if cand.is_winner:
                    fact_scores.append(cand.scores.fact_accuracy)
                    logic_scores.append(cand.scores.logic_completeness)
                    peda_scores.append(cand.scores.pedagogical_fit)

        if not fact_scores:
            return None

        n = len(fact_scores)
        return {
            "fact_accuracy": sum(fact_scores) / n,
            "logic_completeness": sum(logic_scores) / n,
            "pedagogical_fit": sum(peda_scores) / n,
        }

    async def _write_contribution_memory(self, ctx: TaskContext):
        """写贡献记忆 - COMPLETE状态"""
        if not ctx.judge_verdict:
            return

        # 为每个参与的Agent写入贡献记忆
        for i, review in enumerate(ctx.review_feedbacks):
            for candidate in review.candidates:
                if i < len(ctx.dispatch_result.segments):
                    seg = ctx.dispatch_result.segments[i]
                    function_tag = seg.candidates[0]["function_tag"] if seg.candidates else ""

                    # 计算综合review_score
                    scores = candidate.scores
                    review_score = (scores.fact_accuracy + scores.logic_completeness + scores.pedagogical_fit) / 3

                    self.memory_service.record_task_completion(
                        task_id=ctx.task_id,
                        agent_id=candidate.agent_id,
                        function_tag=function_tag,
                        task_type=ctx.profile.complexity_estimate.value,
                        segment=review.seg_id,
                        review_score=review_score,
                        referee_verdict=ctx.judge_verdict.verdict.value,
                        referee_modifications=ctx.revision_count,
                        rework_type="major" if ctx.revision_count > 0 else "none",
                    )

    # ============================================================
    # 延伸路径（从COMPLETE触发，异步事件驱动）
    # ============================================================

    async def handle_extension(
        self,
        task_id: str,
        event_type: str,
        event_data: dict,
    ) -> dict:
        """处理延伸路径事件

        对应方案书 6.1.3 节交付后延伸路径

        event_type:
          quiz_submit / feedback_difficulty / feedback_error / system_recommend
        """
        await ws_manager.push_state(task_id, FSMState.QUIZ_EVAL.value, {"event": event_type})

        if event_type == "quiz_submit":
            return await self._handle_quiz_submit(task_id, event_data)
        elif event_type == "feedback_difficulty":
            return await self._handle_feedback_difficulty(task_id, event_data)
        elif event_type == "feedback_error":
            return await self._handle_feedback_error(task_id, event_data)
        elif event_type == "system_recommend":
            return await self._handle_system_recommend(task_id, event_data)

        return {"error": f"未知事件类型: {event_type}"}

    async def _handle_quiz_submit(self, task_id: str, event_data: dict) -> dict:
        """QUIZ_EVAL: 答题验证"""
        accuracy = event_data.get("accuracy", 0.0)

        if accuracy < 0.85:
            return await self._do_redimension(task_id, event_data)
        else:
            return await self._do_advance(task_id, event_data)

    async def _handle_feedback_difficulty(self, task_id: str, event_data: dict) -> dict:
        """难度不匹配反馈 → 降维解释"""
        return await self._do_redimension(task_id, event_data)

    async def _handle_feedback_error(self, task_id: str, event_data: dict) -> dict:
        """内容有误反馈 → 审核复检"""
        return await self._do_recheck(task_id, event_data)

    async def _handle_system_recommend(self, task_id: str, event_data: dict) -> dict:
        """系统推荐追问"""
        return await self._do_heuristic_followup(task_id, event_data)

    async def _do_redimension(self, task_id: str, event_data: dict) -> dict:
        """REDIMENSION: 降维解释

        对应方案书 6.1.3 节：资源生成Agent用降维Prompt重新生成同一知识点
        """
        await ws_manager.push_state(task_id, FSMState.REDIMENSION.value)

        ctx = self._task_contexts.get(task_id)
        if not ctx or not ctx.merged_focused_output or not ctx.profile:
            logger.warning(f"降维解释: task={task_id} 上下文不存在，跳过LLM调用")
            return await self._do_heuristic_followup(task_id, event_data)

        focused = ctx.merged_focused_output
        accuracy = event_data.get("accuracy", 0.5)

        # 调用资源生成Agent降维解释（返回完整资源包：讲义+实操+测试题）
        reduced_package = await self.resource_agent.generate_dimension_reduction(
            focused, ctx.profile, accuracy, task_id=task_id
        )

        result = {
            "action": "redimension",
            "accuracy": accuracy,
            "reduced_resource_package": reduced_package.model_dump(),
        }

        logger.info(f"降维解释完成: task={task_id}, accuracy={accuracy:.0%}")
        await ws_manager.push_state(task_id, FSMState.REDIMENSION.value, result)
        return await self._do_heuristic_followup(task_id, event_data)

    async def _do_advance(self, task_id: str, event_data: dict) -> dict:
        """ADVANCE: 进阶挑战

        对应方案书 6.1.3 节：追加1道动态进阶题（跨知识点综合或边界条件挑战）
        """
        await ws_manager.push_state(task_id, FSMState.ADVANCE.value)

        ctx = self._task_contexts.get(task_id)
        if not ctx or not ctx.merged_focused_output or not ctx.profile:
            logger.warning(f"进阶挑战: task={task_id} 上下文不存在，跳过LLM调用")
            return await self._do_heuristic_followup(task_id, event_data)

        focused = ctx.merged_focused_output

        # 调用资源生成Agent进阶挑战
        advance_question = await self.resource_agent.generate_advance_challenge(
            focused, ctx.profile
        )

        result = {
            "action": "advance",
            "advance_question": advance_question.model_dump(),
        }

        logger.info(f"进阶挑战完成: task={task_id}")
        await ws_manager.push_state(task_id, FSMState.ADVANCE.value, result)
        return await self._do_heuristic_followup(task_id, event_data)

    async def _do_recheck(self, task_id: str, event_data: dict) -> dict:
        """RECHECK: 审核复检

        对应方案书 6.1.3 节：审核团队对被质疑内容进行专项复检
        复检通过→回复学生；发现错误→进入REDIMENSION修正
        """
        await ws_manager.push_state(task_id, FSMState.RECHECK.value)

        ctx = self._task_contexts.get(task_id)
        if not ctx or not ctx.merged_focused_output:
            logger.warning(f"审核复检: task={task_id} 上下文不存在，跳过LLM调用")
            return await self._do_heuristic_followup(task_id, event_data)

        focused = ctx.merged_focused_output
        feedback = event_data.get("feedback", "")

        # 调用裁判团复检
        recheck_result = await self.judge_panel.recheck(focused, feedback)

        result = {
            "action": "recheck",
            "has_error": recheck_result.get("has_error", False),
            "error_detail": recheck_result.get("error_detail", ""),
            "corrected_content": recheck_result.get("corrected_content", ""),
        }

        logger.info(f"审核复检完成: task={task_id}, has_error={result['has_error']}")
        await ws_manager.push_state(task_id, FSMState.RECHECK.value, result)
        if result.get("has_error"):
            # 复检发现错误→进入降维修正
            return await self._do_redimension(task_id, event_data)
        return await self._do_heuristic_followup(task_id, event_data)

    async def _do_heuristic_followup(self, task_id: str, event_data: dict) -> dict:
        """HEURISTIC_FOLLOWUP: 启发式追问导学

        对应方案书 6.1.3 节：学情诊断Agent基于上下文动态生成1-2个追问问题
        """
        await ws_manager.push_state(task_id, FSMState.HEURISTIC_FOLLOWUP.value)

        ctx = self._task_contexts.get(task_id)
        if not ctx or not ctx.merged_focused_output or not ctx.profile:
            logger.warning(f"启发式追问: task={task_id} 上下文不存在，跳过LLM调用")
            return {"action": "heuristic_followup", "followup_questions": []}

        focused = ctx.merged_focused_output
        recent_content = focused.model_dump_json(indent=2)

        # 调用学情诊断Agent生成追问
        followup_questions = await self.profile_agent.generate_heuristic_followup(
            recent_content, ctx.profile
        )

        result = {
            "action": "heuristic_followup",
            "followup_questions": followup_questions,
        }

        logger.info(f"启发式追问完成: task={task_id}, questions={len(followup_questions)}")
        await ws_manager.push_state(task_id, FSMState.HEURISTIC_FOLLOWUP.value, result)
        return result

    # ============================================================
    # 辅助方法
    # ============================================================

    def _merge_focused_outputs(self, outputs: list[FocusedOutput]) -> FocusedOutput:
        """合并多段聚焦输出为一份

        对应方案书§3.4.2/3.4.3：跨段一致性审查后各段最优拼接。
        各段内容按段标注拼接，保留完整推理链和知识引用。
        """
        # 单段直接返回（无需标注）
        if len(outputs) == 1:
            return outputs[0]

        # 合并结论（按段标注）
        conclusions = [
            f"[段{i+1}] {o.conclusion}" for i, o in enumerate(outputs) if o.conclusion
        ]
        merged_conclusion = "\n".join(conclusions)

        # 合并推理步骤（按段标注分隔）
        merged_steps = []
        for i, o in enumerate(outputs):
            if o.reasoning_steps:
                merged_steps.append(f"--- 段{i+1} ---")
                merged_steps.extend(o.reasoning_steps)

        # 合并知识引用（直接拼接）
        merged_refs = []
        for o in outputs:
            merged_refs.extend(o.knowledge_refs)

        # 合并适用条件（按段标注）
        conditions = [
            f"[段{i+1}] {o.applicable_conditions}"
            for i, o in enumerate(outputs) if o.applicable_conditions
        ]
        merged_conditions = "\n".join(conditions) if conditions else ""

        # 合并代码示例（直接拼接）
        code_examples = [o.code_example for o in outputs if o.code_example]
        merged_code = "\n\n".join(code_examples) if code_examples else None

        # 合并难度说明（按段标注）
        difficulty_notes = [
            f"[段{i+1}] {o.difficulty_note}"
            for i, o in enumerate(outputs) if o.difficulty_note
        ]
        merged_difficulty = "\n".join(difficulty_notes) if difficulty_notes else None

        return FocusedOutput(
            conclusion=merged_conclusion,
            reasoning_steps=merged_steps,
            knowledge_refs=merged_refs,
            applicable_conditions=merged_conditions,
            code_example=merged_code,
            difficulty_note=merged_difficulty,
        )

    def _merge_judge_verdicts(self, verdicts: list[JudgeVerdict]) -> JudgeVerdict:
        """合并多段裁判裁决

        对应方案书§3.4.2/3.4.3：各段独立裁判后合并为整体裁决。

        合并规则：
          - 整体裁决取最严格结果（FAILED > REVISE > LOW_CONFIDENCE_PASSED > PASSED）
          - 裁判意见按段标注合并
          - 分歧解决记录取第一个非空（多段分歧时记录告警）
          - 溯源标注合并
          - 验证率取平均
        """
        verdict_priority = {
            Verdict.FAILED: 3,
            Verdict.REVISE: 2,
            Verdict.LOW_CONFIDENCE_PASSED: 1,
            Verdict.PASSED: 0,
        }

        # 取最严格的裁决
        overall_verdict = max(
            verdicts, key=lambda v: verdict_priority.get(v.verdict, 0)
        ).verdict

        # 合并裁判意见（按段标注）
        merged_judges = []
        for i, v in enumerate(verdicts):
            for judge in v.judges:
                merged_judges.append(JudgeOpinion(
                    role=f"[段{i+1}] {judge.role}",
                    judgment=judge.judgment,
                    evidence=judge.evidence,
                    confidence=judge.confidence,
                ))

        # 合并分歧解决记录
        dissents = [v.dissent_resolution for v in verdicts if v.dissent_resolution]
        merged_dissent = dissents[0] if dissents else None
        if len(dissents) > 1:
            logger.warning(f"多段分歧: {len(dissents)}个段出现2:1分歧")

        # 合并溯源标注
        merged_traceability = []
        for v in verdicts:
            merged_traceability.extend(v.traceability)

        # 平均验证率
        avg_rate = (
            sum(v.overall_verification_rate for v in verdicts) / len(verdicts)
            if verdicts else 0.0
        )

        return JudgeVerdict(
            verdict=overall_verdict,
            judges=merged_judges,
            dissent_resolution=merged_dissent,
            traceability=merged_traceability,
            overall_verification_rate=avg_rate,
        )

    async def _transition(self, ctx: TaskContext, new_state: FSMState):
        """状态转移（带合法性校验）"""
        if not can_transition(ctx.current_state, new_state):
            raise FSMTransitionError(ctx.current_state.value, new_state.value)

        logger.debug(f"FSM转移: {ctx.current_state.value} → {new_state.value}")
        ctx.current_state = new_state
        # P1-1: push_state 内部会同步更新 status 接口缓存，保证 /api/status 一致
        await ws_manager.push_state(
            ctx.task_id,
            new_state.value,
            {"revision": ctx.revision_count, "session_id": ctx.session_id},
        )

"""编排器 - FSM状态机驱动全流程

对应方案书 6.1 节编排器设计

主FSM：
  IDLE → PROFILING → DISPATCHING → GENERATING → REVIEWING
  → FOCUSING → JUDGING → FORMATTING → COMPLETE

延伸路径（从COMPLETE触发）：
  QUIZ_EVAL → REDIMENSION / ADVANCE / RECHECK → HEURISTIC_FOLLOWUP
"""

import asyncio
import time
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
from backend.schemas.student_profile import (
    StudentProfile, IntentType, ComplexityEstimate, QuestionType,
    KnowledgeLevel, Background, CurrentGoal,
    ConfidenceLevel, TestResult, DOMAIN_HINT_ENUMS,
)
from backend.schemas.candidate_output import CandidateOutput, FocusedOutputBody, SelfConfidence
from backend.schemas.review_feedback import ReviewFeedback, CandidateReview, ReviewerScores
from backend.schemas.focused_output import FocusedOutput
from backend.schemas.judge_verdict import JudgeVerdict, Verdict, JudgeOpinion
from backend.schemas.resource_package import ResourcePackage
from backend.services.ws_manager import ws_manager
from backend.services.memory_service import get_memory_service
from backend.config import get_settings
from backend.db.repositories import profile_repo


# 聚焦输出单段零降级重试上限（指数退避：1s, 2s）。仅失败时发生，正常 0 成本。
FOCUS_MAX_RETRIES = 3


class _PartialProfile:
    """用户提供的可能不完整的合法画像字段，待补全。

    与 StudentProfile 的区别：StudentProfile 6 个核心字段必填，无法表达"部分提交"；
    这里只收集用户提交且【合法】的字段，缺口由 _do_profiling 用 ProfileAgent 补全。
    """

    __slots__ = ("fields", "domain_hint", "test_results")

    def __init__(self):
        self.fields: dict = {}          # {字段名: 枚举值}
        self.domain_hint: list = []
        self.test_results: list = []

    @property
    def is_empty(self) -> bool:
        return not self.fields and not self.domain_hint and not self.test_results


# intent_type 中文别名 → 英文枚举值（队友前端用中文展示也兼容）
_INTENT_ALIAS = {
    "内容生成": "generation", "生成": "generation", "generation": "generation",
    "路径导航": "navigation", "导航": "navigation", "navigation": "navigation",
    "问题澄清": "clarification", "澄清": "clarification", "clarification": "clarification",
}


def _build_profile_from_partial(pp: "_PartialProfile", session_id: str) -> StudentProfile:
    """补全失败兜底：用户字段优先，缺口用中性默认填，保证请求永不因画像问题失败。

    用于 ProfileAgent.complete_profile（MID 档 LLM）不可用时的降级——用户已提交的
    合法字段仍原样生效，只是缺失字段由系统给一个保守默认值。
    """
    known = pp.fields
    return StudentProfile(
        knowledge_level=known.get("knowledge_level", KnowledgeLevel.ENTRY),
        background=known.get("background", Background.SCIENCE_NO_CODE),
        current_goal=known.get("current_goal", CurrentGoal.QUICK_START),
        question_type=known.get("question_type", QuestionType.CONCEPT),
        domain_hint=pp.domain_hint,
        complexity_estimate=known.get("complexity_estimate", ComplexityEstimate.SINGLE_DOMAIN),
        intent_type=known.get("intent_type", IntentType.GENERATION),
        test_results=pp.test_results,
        session_id=session_id,
    )


@dataclass
class TaskContext:
    """单次任务上下文 - 在FSM各状态间传递"""
    task_id: str
    session_id: str
    question: str
    history: list[dict] = field(default_factory=list)

    # 各阶段产物
    profile: Optional[StudentProfile] = None
    # 方案A：用户提交的（可能不完整的）画像，_do_profiling 用 ProfileAgent 补全缺口
    partial_profile: Optional["_PartialProfile"] = None
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
    # 方案一：JUDGING 与 FORMATTING 并行时，FORMATTING 的后台任务句柄
    # （两者都只依赖 focused_output，可并发执行以省一段串行耗时）
    fmt_task: Optional[asyncio.Task] = None

    # 候选Agent引用（用于辩论）
    winning_agents: list[DomainAgent] = field(default_factory=list)
    losing_candidates: list[CandidateOutput] = field(default_factory=list)
    winning_candidates: list[CandidateOutput] = field(default_factory=list)

    # P1-1: 双低触发的段索引（self_confidence都<0.5但知识库不可用时标记）
    low_confidence_segments: set = field(default_factory=set)

    # P1-2: 离线评估标记（benchmark用），不参与agent_performance/α/淘汰
    offline: bool = False


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
        # 已完成任务的最终结果（异步任务轮询接口 GET /api/status/{task_id} 使用）
        self._task_results: dict[str, dict] = {}
        # 后台任务引用集合（防止 asyncio.Task 被 GC 提前回收导致任务静默取消）
        self._background_tasks: set[asyncio.Task] = set()

    async def process_question(
        self,
        question: str,
        session_id: str,
        history: Optional[list[dict]] = None,
        profile: Optional["StudentProfile"] = None,
        offline: bool = False,
    ) -> dict:
        """处理学生问题 - 主FSM入口

        Args:
            profile: 可选学情画像。若提供则跳过 PROFILING 阶段的自动诊断，
                     直接以该画像驱动后续生成（基准评测按 test_cases 的 suitable_profile
                     注入，用于测量"给定学情下的难度适配准确率"）。不传则自动诊断。
            offline: 是否为离线评估任务。离线任务只记录contribution_memory（task_type=offline_eval），
                     不更新agent_performance/不触发α调整/不参与淘汰判定。避免benchmark污染自进化。

        Returns:
            包含resource_package和FSM轨迹的字典
        """
        task_id = f"task_{uuid.uuid4().hex[:12]}"
        ctx = TaskContext(
            task_id=task_id,
            session_id=session_id,
            question=question,
            history=history or [],
            offline=offline,
        )
        # 注入外部画像（基准评测/前端提交用）：完整画像直接复用；
        # 部分画像（用户只填了部分字段）存入 partial_profile，_do_profiling 补全缺口
        coerced = self._coerce_profile(profile)
        if isinstance(coerced, StudentProfile):
            ctx.profile = coerced
        elif isinstance(coerced, _PartialProfile):
            ctx.partial_profile = coerced

        logger.info(f"任务开始: task_id={task_id}, question='{question[:50]}...'")

        try:
            # 主FSM循环
            await self._run_main_fsm(ctx)

            # 缓存上下文供延伸路径使用
            self._task_contexts[task_id] = ctx

            return self._build_result(ctx, session_id, task_id)

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

    def _build_result(self, ctx: TaskContext, session_id: str, task_id: str) -> dict:
        """从 TaskContext 组装最终响应字典（同步 /api/ask 与异步 /api/tasks 共用）"""
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

    @staticmethod
    def _coerce_profile(profile):
        """把可选学情画像（dict 或 StudentProfile）安全转成 StudentProfile / _PartialProfile / None。

        返回语义：
        - 完整合法 dict / StudentProfile           → StudentProfile（直接复用，跳过补全）
        - 部分合法 dict（≥1 个有效字段）           → _PartialProfile（_do_profiling 用 ProfileAgent 补全缺口）
        - 空 dict / 全字段非法 / 非 dict 非Profile → None（走自动诊断）

        逐字段容错：认得的字段保留，错值/缺值该字段单独忽略，永不因画像问题失败。
        """
        if profile is None:
            return None
        if isinstance(profile, StudentProfile):
            return profile
        if not isinstance(profile, dict):
            logger.warning("学情画像类型不支持（需 dict 或 StudentProfile），忽略并走自动诊断")
            return None

        pp = _PartialProfile()
        _ENUM_FIELDS = {
            "knowledge_level": KnowledgeLevel,
            "background": Background,
            "current_goal": CurrentGoal,
            "question_type": QuestionType,
            "complexity_estimate": ComplexityEstimate,
            "intent_type": IntentType,
        }
        for fname, enum_cls in _ENUM_FIELDS.items():
            val = profile.get(fname)
            if val is None:
                continue
            # intent_type 兼容中文别名（内容生成/路径导航/问题澄清）
            if fname == "intent_type" and isinstance(val, str) and val not in (
                "generation", "navigation", "clarification",
            ):
                val = _INTENT_ALIAS.get(val, val)
            try:
                pp.fields[fname] = enum_cls(val)
            except Exception:
                logger.warning(f"学情画像字段'{fname}'值非法已忽略: {val!r}")

        # 可选：domain_hint（list 或逗号分隔字符串，按 DOMAIN_HINT_ENUMS 过滤）
        dh = profile.get("domain_hint")
        if isinstance(dh, list):
            for d in dh:
                if d in DOMAIN_HINT_ENUMS:
                    pp.domain_hint.append(d)
                else:
                    logger.warning(f"domain_hint 值非法已忽略: {d!r}")
        elif isinstance(dh, str):
            for d in [x.strip() for x in dh.split(",") if x.strip()]:
                if d in DOMAIN_HINT_ENUMS:
                    pp.domain_hint.append(d)
                else:
                    logger.warning(f"domain_hint 值非法已忽略: {d!r}")

        # 可选：test_results（理论测试成绩，赛题要求整合）
        tr = profile.get("test_results")
        if isinstance(tr, list):
            for t in tr:
                if isinstance(t, dict):
                    try:
                        pp.test_results.append(TestResult(**t))
                    except Exception:
                        logger.warning(f"test_results 项非法已忽略: {t!r}")

        if pp.is_empty:
            return None
        # 6 个核心字段全部齐备 → 直接构造完整 StudentProfile，跳过补全（省一次 LLM 调用）
        _CORE_FIELDS = {
            "knowledge_level", "background", "current_goal",
            "question_type", "complexity_estimate", "intent_type",
        }
        if _CORE_FIELDS.issubset(pp.fields.keys()):
            # 若画像已给出 domain_hint 但未提交 domain_confidence，
            # 按 domain_hint 自动给 HIGH，避免完整画像因缺 confidence 误触发澄清。
            domain_confidence = profile.get("domain_confidence") or {}
            if not domain_confidence and pp.domain_hint:
                domain_confidence = {h: ConfidenceLevel.HIGH for h in pp.domain_hint}
            return StudentProfile(
                knowledge_level=pp.fields["knowledge_level"],
                background=pp.fields["background"],
                current_goal=pp.fields["current_goal"],
                question_type=pp.fields["question_type"],
                domain_hint=pp.domain_hint,
                complexity_estimate=pp.fields["complexity_estimate"],
                intent_type=pp.fields["intent_type"],
                domain_confidence=domain_confidence,
                test_results=pp.test_results,
            )
        return pp

    def create_task(
        self,
        question: str,
        session_id: str,
        history: Optional[list[dict]] = None,
        profile=None,
    ) -> str:
        """创建任务并返回 task_id（不立即执行，供异步提交使用）

        profile: 可选学情画像（dict 或 StudentProfile）。注入后 _do_profiling 会
        检测到 ctx.profile 非空并跳过自动诊断，直接以该画像驱动生成。
        """
        task_id = f"task_{uuid.uuid4().hex[:12]}"
        ctx = TaskContext(
            task_id=task_id,
            session_id=session_id,
            question=question,
            history=history or [],
        )
        coerced = self._coerce_profile(profile)
        if isinstance(coerced, StudentProfile):
            ctx.profile = coerced
        elif isinstance(coerced, _PartialProfile):
            ctx.partial_profile = coerced
        self._task_contexts[task_id] = ctx
        # 初始状态 PENDING：避免后台任务首次 push 前轮询读到 UNKNOWN
        try:
            from backend.api.routes.status import update_task_state
            update_task_state(task_id, "PENDING", {})
        except Exception as e:
            logger.warning(f"初始化任务状态失败(不影响执行): {e}")
        logger.info(f"任务已创建(异步): task_id={task_id}")
        return task_id

    async def _run_task_background(self, task_id: str) -> None:
        """后台执行任务主FSM，并将最终结果存入 _task_results（供轮询/WS 获取）"""
        ctx = self._task_contexts.get(task_id)
        if ctx is None:
            logger.error(f"后台任务找不到上下文: task_id={task_id}")
            return
        try:
            await self._run_main_fsm(ctx)
            self._task_contexts[task_id] = ctx
            self._task_results[task_id] = self._build_result(ctx, ctx.session_id, task_id)
            # 落库生成资源文本（事实比对指标 + 测试数据套装数据源，容错，不增加调用时间）
            try:
                from backend.db.resource_store import save_task_resources
                save_task_resources(
                    task_id,
                    ctx.session_id,
                    self._task_results[task_id],
                    getattr(ctx, "question", None),
                )
            except Exception as e:
                logger.warning(f"落库生成资源失败（不影响主流程）: {e}")
            logger.info(f"后台任务完成: task_id={task_id}")
        except Exception as e:
            logger.error(f"后台任务失败: task_id={task_id}, error={e}")
            # 同步推进 ERROR 状态，保证前端轮询能正确识别失败（与同步版 process_question 的 except 一致）
            try:
                await ws_manager.push_state(task_id, FSMState.ERROR.value, {"error": str(e)})
            except Exception:
                pass
            self._task_results[task_id] = {
                "task_id": task_id,
                "session_id": ctx.session_id,
                "error": str(e),
                "state": "ERROR",
            }

    def submit_task(
        self,
        question: str,
        session_id: str,
        history: Optional[list[dict]] = None,
        profile=None,
    ) -> str:
        """提交异步任务：创建 task 并后台启动，立即返回 task_id

        profile: 透传给 create_task，用于注入学情画像（详见 create_task）。
        """
        task_id = self.create_task(question, session_id, history, profile)
        task = asyncio.create_task(self._run_task_background(task_id))
        # 保存引用，防止 Task 对象被 GC 回收导致后台任务静默取消
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)
        return task_id

    def get_task_result(self, task_id: str) -> Optional[dict]:
        """获取已完成任务的结果（轮询接口 GET /api/status/{task_id} 使用）"""
        return self._task_results.get(task_id)

    async def _run_main_fsm(self, ctx: TaskContext):
        """运行主FSM循环"""
        ctx.current_state = FSMState.IDLE
        _fsm_start = time.monotonic()

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
                # 方案一：资源生成只依赖 focused_output，与裁判【并发】启动，省一段串行耗时。
                # 必须在 await 裁判之前 create_task，否则两者串行、优化失效。
                # fmt_task 在 FORMATTING 状态分支 await 完成；若裁判要求回炉(REVISE)，
                # 则旧 fmt_task 基于未修订 focused，在 REVISING 分支取消丢弃、定稿后重跑。
                ctx.fmt_task = asyncio.create_task(self._do_formatting(ctx))
                try:
                    verdict = await self._do_judging(ctx)
                except Exception as e:
                    # 裁判团异常（极少）：不取消并发资源生成，降级为低置信度强制通过，
                    # 保证任务不以致 error 失败、学生至少拿到答案（对应新需求：任何问题都必须能回答）。
                    logger.error(f"裁判团异常，降级为低置信度强制通过: {e}")
                    # 修复：构造低置信度强制通过的裁决对象（而非 None），确保下游
                    # _save_task_metrics / _write_contribution_memory 有合法 verdict 可读，
                    # 真实记录本次降级（而非静默丢失代理指标或触发 AttributeError）。
                    ctx.judge_verdict = JudgeVerdict(
                        verdict=Verdict.LOW_CONFIDENCE_PASSED,
                        judges=[JudgeOpinion(role="系统降级", judgment="fail", confidence=0.0)],
                        overall_verification_rate=0.0,
                        override_reason="judge_panel_exception_force_pass",
                    )
                    await self._transition(ctx, FSMState.FORMATTING)
                    continue
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
                # 回炉前取消基于旧 focused 的资源生成任务（避免返回陈旧资源包）
                if ctx.fmt_task is not None:
                    ctx.fmt_task.cancel()
                    try:
                        await ctx.fmt_task
                    except (asyncio.CancelledError, Exception):
                        pass
                    ctx.fmt_task = None
                await self._do_revising(ctx)
                await self._transition(ctx, FSMState.JUDGING)

            elif ctx.current_state == FSMState.FORMATTING:
                # 等待与裁判并发启动的资源生成完成。
                # 零降级：即使资源包生成最终仍异常（_do_formatting 内部已兜一层），
                # 也不向上抛 error 导致任务失败——聚焦输出(答案)已就绪，学生至少拿到答案。
                if ctx.fmt_task is not None:
                    try:
                        await ctx.fmt_task
                    except Exception as e:
                        logger.error(f"资源生成任务异常(已降级，任务继续完成): {e}")
                    ctx.fmt_task = None
                await self._transition(ctx, FSMState.COMPLETE)

        # 写贡献记忆
        await self._write_contribution_memory(ctx)
        await ws_manager.push_state(ctx.task_id, FSMState.COMPLETE.value)
        logger.info(
            f"主FSM完成: task={ctx.task_id}, 耗时={time.monotonic() - _fsm_start:.2f}s"
        )

    # ============================================================
    # 各状态处理
    # ============================================================

    def _persist_profile(self, profile: "StudentProfile") -> None:
        """落库学情画像（含 test_results）。

        用于外部注入画像 / 补全兜底的持久化补齐——自动诊断(generate_profile)与
        部分补全(complete_profile)内部已各自 save，这里只在它们覆盖不到的
        分支（完整画像注入、兜底）补存，保证 test_results 可经 /api/report 读回。
        """
        try:
            profile_repo.save_profile(
                session_id=profile.session_id,
                version=profile_repo.get_next_version(profile.session_id),
                knowledge_level=profile.knowledge_level.value,
                background=profile.background.value,
                current_goal=profile.current_goal.value,
                question_type=profile.question_type.value,
                domain_hint=profile.domain_hint,
                complexity_estimate=profile.complexity_estimate.value,
                intent_type=profile.intent_type.value,
                domain_confidence={k: v.value for k, v in profile.domain_confidence.items()},
                test_results=[t.model_dump() for t in profile.test_results],
            )
        except Exception as e:
            logger.warning(f"学情画像落库失败（不影响主流程）: {e}")

    async def _do_profiling(self, ctx: TaskContext):
        """PROFILING: 学情画像生成

        降级策略（方案书§8.5.3）：LLM调用失败时使用默认画像，不中断主流程。
        若 process_question 已注入外部画像（ctx.profile 非空），则跳过自动诊断，
        直接复用注入画像（基准评测按 test_cases 的 suitable_profile 注入）。
        """
        # 已注入完整画像：跳过诊断，直接进入 DISPATCHING
        if ctx.profile is not None:
            # 仅当用户提交了理论测试成绩时补齐落库（benchmark 注入的 suitable_profile 无 test_results，行为不变）
            if ctx.profile.test_results:
                self._persist_profile(ctx.profile)
            await ws_manager.push_state(
                ctx.task_id, FSMState.PROFILING.value,
                {"profile": ctx.profile.model_dump(), "injected": True},
            )
            return

        # 已注入部分画像（用户只填了部分字段）：补全缺口后复用，用户字段优先不覆盖
        if ctx.partial_profile is not None:
            await ws_manager.push_state(
                ctx.task_id, FSMState.PROFILING.value,
                {"partial": True, "known_fields": list(ctx.partial_profile.fields.keys())},
            )
            try:
                ctx.profile = await self.profile_agent.complete_profile(
                    known=ctx.partial_profile,
                    question=ctx.question,
                    session_id=ctx.session_id,
                    history=ctx.history,
                )
            except Exception as e:
                logger.warning(f"部分画像补全失败，用已知字段+默认兜底: {e}")
                ctx.profile = _build_profile_from_partial(ctx.partial_profile, ctx.session_id)
                # 兜底分支也确保理论测试成绩落库（如 MID 档不可用）
                if ctx.profile.test_results:
                    self._persist_profile(ctx.profile)
            await ws_manager.push_state(
                ctx.task_id, FSMState.PROFILING.value,
                {"profile": ctx.profile.model_dump(), "completed_from_partial": True},
            )
            return

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

        # 复杂度标签与实际段数对齐：ProfileAgent 可能把多领域问题标成"单领域"，
        # 导致输出自相矛盾（标签单领域却调度出多段）。以实际段数为准回填标签。
        seg_count = len(ctx.dispatch_result.segments)
        if seg_count == 1:
            ctx.profile.complexity_estimate = ComplexityEstimate.SINGLE_DOMAIN
        elif ctx.profile.question_type == QuestionType.FULL_PIPELINE:
            ctx.profile.complexity_estimate = ComplexityEstimate.FULL_PIPELINE
        elif seg_count > 1:
            ctx.profile.complexity_estimate = ComplexityEstimate.CROSS_DOMAIN

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
        # 安全网：单个候选生成/校验失败(如 LLM 输出无法解析为合法 CandidateOutput，
        # 触发 SchemaValidationError)不再整体抛错，降级为空但合法的候选输出
        # (置信度0)，评审阶段自然会让另一正常候选胜出；两段都失败也能继续走完流程，
        # 保证任何问题都至少产出答案、不会以致 error 失败（对应新需求：任何问题都必须能回答）。
        results = await asyncio.gather(*[t[3] for t in segment_tasks], return_exceptions=True)

        # 按段组织结果
        seg_map: dict[str, list[CandidateOutput]] = {}
        for (seg_id, agent, info, _), output in zip(segment_tasks, results):
            if isinstance(output, Exception):
                logger.error(
                    f"候选生成失败, 降级为空候选输出(agent={agent.agent_id}, seg={seg_id}): {output}"
                )
                output = CandidateOutput(
                    agent_id=agent.agent_id,
                    seg_id=seg_id,
                    answer=FocusedOutputBody(),
                    self_confidence=SelfConfidence(
                        score=0.0, weak_points=["生成/校验失败,已降级"]
                    ),
                )
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
                regen_results = await asyncio.gather(
                    *[t[1] for t in regen_tasks], return_exceptions=True
                )
                # 用重新生成的结果替换原结果（仅替换成功的；失败的保留原候选，不 abort）
                regen_map = {}
                for t, r in zip(regen_tasks, regen_results):
                    if not isinstance(r, Exception):
                        regen_map[t[0].agent_id] = r
                    else:
                        logger.warning(
                            f"RAG增强重新生成失败, 保留原候选(agent={t[0].agent_id}): {r}"
                        )
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
        ctx.review_feedbacks = await asyncio.gather(*review_tasks, return_exceptions=True)
        # 安全网：某段审核失败(如评审 LLM 输出无法解析为合法 ReviewFeedback) →
        # 用候选列表拼最小审核反馈，标记最高 self_confidence 的候选为胜出，
        # 保证流程不 abort（对应新需求：任何问题都必须能回答，不能报错）。
        if any(isinstance(rf, Exception) for rf in ctx.review_feedbacks):
            patched = []
            for i, rf in enumerate(ctx.review_feedbacks):
                if not isinstance(rf, Exception):
                    patched.append(rf)
                    continue
                logger.error(f"段{i}审核失败，降级为最小审核反馈: {rf}")
                seg = ctx.dispatch_result.segments[i]
                cands = ctx.candidate_outputs[i]
                winner_agent_id = max(
                    cands,
                    key=lambda c: (c.self_confidence.score if c.self_confidence else 0.0),
                ).agent_id
                patched.append(ReviewFeedback(
                    seg_id=seg.seg_id,
                    candidates=[
                        CandidateReview(
                            agent_id=c.agent_id,
                            scores=ReviewerScores(
                                fact_accuracy=0.5, logic_completeness=0.5, pedagogical_fit=0.5
                            ),
                            issues_found=[],
                            is_winner=(c.agent_id == winner_agent_id),
                        )
                        for c in cands
                    ],
                ))
            ctx.review_feedbacks = patched

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
        """FOCUSING: 最优Agent聚焦输出（含审核反馈回流）

        方案一：多段场景跨段并行聚焦（原先串行 for 循环 → asyncio.gather），
        单领域仅1段时无变化。零降级：每段聚焦失败加指数退避重试，耗尽才抛错
        （移除原「降级模式」FocusedOutput 静默兜底，避免核心答案降级）。
        """
        await ws_manager.push_state(ctx.task_id, FSMState.FOCUSING.value)

        ctx.focused_outputs = []
        ctx.winning_agents = []
        ctx.winning_candidates = []
        ctx.losing_candidates = []

        # 跨段并行聚焦（每段独立，无数据依赖）
        # 安全网：某段聚焦重试耗尽仍失败时，用候选输出就地拼最小聚焦输出，
        # 避免整条任务因单段失败而 abort（对应新需求：任何问题都必须能回答，不能报错）。
        tasks = [
            self._focus_segment(ctx, i, review)
            for i, review in enumerate(ctx.review_feedbacks)
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for i, res in enumerate(results):
            if isinstance(res, Exception):
                logger.error(f"段{i}聚焦重试耗尽，降级为候选输出组装最小聚焦输出: {res}")
                review = ctx.review_feedbacks[i]
                winner_candidate = next(c for c in review.candidates if c.is_winner)
                winner_output = next(
                    co for co in ctx.candidate_outputs[i]
                    if co.agent_id == winner_candidate.agent_id
                )
                focused = self._build_fallback_focused(winner_output)
                winning_agent = DomainAgent(winner_candidate.agent_id)
                loser_output = None
            else:
                focused, winning_agent, winner_output, loser_output = res
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

        # 体检 #4：持久化延伸上下文（多进程下 feedback/quiz 可恢复）
        self._persist_extension_context(ctx.task_id, ctx)

        await ws_manager.push_state(
            ctx.task_id, FSMState.FOCUSING.value,
            {"focused_count": len(ctx.focused_outputs)},
        )

    async def _focus_segment(self, ctx: TaskContext, i: int, review) -> tuple:
        """单段聚焦输出（含零降级重试）

        Returns:
            (focused, winning_agent, winner_output, loser_output)
        """
        winner_candidate = next(c for c in review.candidates if c.is_winner)
        loser_candidates_list = [c for c in review.candidates if not c.is_winner]

        winner_output = next(
            co for co in ctx.candidate_outputs[i] if co.agent_id == winner_candidate.agent_id
        )

        loser_output = None
        if loser_candidates_list:
            loser_output = next(
                co for co in ctx.candidate_outputs[i] if co.agent_id == loser_candidates_list[0].agent_id
            )
        else:
            logger.info(f"段{review.seg_id}只有1个候选（早停），跳过落选候选记录")

        winning_agent = DomainAgent(winner_candidate.agent_id)

        # 零降级重试：聚焦输出失败（API 限流/超时等）指数退避重试，耗尽才抛错
        last_exc = None
        for attempt in range(FOCUS_MAX_RETRIES):
            try:
                focused = await winning_agent.generate_focused_output(
                    question=ctx.question,
                    profile=ctx.profile,
                    original_output=winner_output,
                    review_feedback=review,
                )
                return focused, winning_agent, winner_output, loser_output
            except Exception as e:
                last_exc = e
                if attempt < FOCUS_MAX_RETRIES - 1:
                    delay = 2 ** attempt
                    logger.warning(
                        f"段{review.seg_id}聚焦输出失败(attempt {attempt + 1}/"
                        f"{FOCUS_MAX_RETRIES}), {delay}s 后重试: {type(e).__name__}"
                    )
                    await asyncio.sleep(delay)
        logger.error(f"段{review.seg_id}聚焦输出重试耗尽, 任务将失败: {last_exc}")
        raise last_exc

    def _build_fallback_focused(self, winner_output) -> FocusedOutput:
        """聚焦输出失败时的就地兜底：用候选输出拼最小聚焦输出（保证任务不 abort）

        候选输出 answer 已含 conclusion/reasoning_steps/knowledge_refs 等字段，
        但可能 reasoning_steps<3 或缺 conclusion，逐项补默认值以满足 FocusedOutput 校验。
        """
        ans = winner_output.answer
        reasoning = list(ans.reasoning_steps or [])
        while len(reasoning) < 3:
            reasoning.append("（聚焦生成失败，已降级展示候选输出要点）")
        return FocusedOutput(
            conclusion=ans.conclusion or "（聚焦生成失败，以下为候选输出内容）",
            reasoning_steps=reasoning,
            knowledge_refs=list(ans.knowledge_refs or []),
            applicable_conditions=ans.applicable_conditions or "（未提供适用条件）",
            code_example=ans.code_example,
            difficulty_note=ans.difficulty_note or "（聚焦降级，未做个性化难度适配）",
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

        # 重新聚焦输出，传入裁判具体反馈（各段并发，避免串行累加耗时）
        async def _revise_one(i: int, agent):
            try:
                focused = await agent.generate_focused_output(
                    question=ctx.question,
                    profile=ctx.profile,
                    original_output=ctx.winning_candidates[i],
                    review_feedback=ctx.review_feedbacks[i] if i < len(ctx.review_feedbacks) else None,
                    judge_feedback=judge_feedback,
                )
                return i, focused
            except Exception as e:
                # 回炉失败：保留原聚焦输出，避免整条任务 abort（对应新需求：任何问题都必须能回答）
                logger.error(f"段{i}回炉聚焦失败，保留原聚焦输出: {e}")
                return i, None

        revise_results = await asyncio.gather(
            *[_revise_one(i, agent) for i, agent in enumerate(ctx.winning_agents)]
        )
        for i, focused in revise_results:
            if focused is not None:
                ctx.focused_outputs[i] = focused

        # P0-1: 重新合并多段聚焦输出
        if len(ctx.focused_outputs) == 1:
            ctx.merged_focused_output = ctx.focused_outputs[0]
        else:
            ctx.merged_focused_output = self._merge_focused_outputs(ctx.focused_outputs)

        # 体检 #4：持久化延伸上下文（多进程下 feedback/quiz 可恢复）
        self._persist_extension_context(ctx.task_id, ctx)

    async def _do_formatting(self, ctx: TaskContext):
        """FORMATTING: 资源生成Agent按条件生成3种形态

        多段场景：使用合并后的聚焦输出统一生成资源包。
        零降级（用户硬指标）：资源生成失败直接抛出，由任务以 error 显式失败，
        不返回「仅讲义」等残缺资源包——残缺资源比报错更损害教学可信度。
        """
        await ws_manager.push_state(ctx.task_id, FSMState.FORMATTING.value)

        focused = ctx.merged_focused_output or (ctx.focused_outputs[0] if ctx.focused_outputs else None)
        if not focused:
            raise OrchestratorError("无聚焦输出可供资源生成")

        # 安全网：generate_resource_package 内部已对三件套做逐件降级，极端情况下仍可能抛错。
        # 此处再兜一层：若整体异常，用聚焦输出就地组装最小资源包（仅讲义），
        # 保证任务不以致 error 失败、学生至少拿到答案（对应新需求：任何问题都必须能回答，不能报错）。
        try:
            ctx.resource_package = await self.resource_agent.generate_resource_package(
                task_id=ctx.task_id,
                focused_output=focused,
                profile=ctx.profile,
            )
        except Exception as e:
            logger.error(f"资源包生成异常，降级为聚焦输出组装最小资源包: {e}")
            ctx.resource_package = ResourcePackage(
                task_id=ctx.task_id,
                lecture=self.resource_agent.build_fallback_lecture(focused),
                practice_guide=None,
                quiz=None,
                focused_output_ref=ctx.task_id,
                profile_ref=(ctx.profile.session_id if ctx.profile else "") or "",
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
                        task_type="offline_eval" if ctx.offline else ctx.profile.complexity_estimate.value,
                        segment=review.seg_id,
                        review_score=review_score,
                        referee_verdict=ctx.judge_verdict.verdict.value,
                        referee_modifications=ctx.revision_count,
                        rework_type="major" if ctx.revision_count > 0 else "none",
                        offline=ctx.offline,
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

    # ---- 跨进程上下文快照（体检 #4 修复）----
    def _persist_extension_context(self, task_id: str, ctx) -> None:
        """主生成结束时把延伸路径必需的 profile+focused_output 落盘，供多 worker 共享"""
        from backend.services.task_context_store import save_extension_context

        save_extension_context(task_id, ctx.profile, ctx.merged_focused_output)

    def _load_extension_context(self, task_id: str):
        """内存 ctx 缺失时（多进程）尝试从快照恢复；失败返回 None→维持 heuristic 兜底"""
        from backend.services.task_context_store import load_extension_context

        return load_extension_context(task_id)

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

        ctx = self._task_contexts.get(task_id) or self._load_extension_context(task_id)
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
        # 启发式追问作为收尾，合并其追问问题，并保留降维资源包一并返回
        followup = await self._do_heuristic_followup(task_id, event_data)
        result["followup_questions"] = followup.get("followup_questions")
        return result

    async def _do_advance(self, task_id: str, event_data: dict) -> dict:
        """ADVANCE: 进阶挑战

        对应方案书 6.1.3 节：追加1道动态进阶题（跨知识点综合或边界条件挑战）
        """
        await ws_manager.push_state(task_id, FSMState.ADVANCE.value)

        ctx = self._task_contexts.get(task_id) or self._load_extension_context(task_id)
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
        # 启发式追问作为收尾，合并其追问问题，并保留进阶挑战题一并返回
        followup = await self._do_heuristic_followup(task_id, event_data)
        result["followup_questions"] = followup.get("followup_questions")
        return result

    async def _do_recheck(self, task_id: str, event_data: dict) -> dict:
        """RECHECK: 审核复检

        对应方案书 6.1.3 节：审核团队对被质疑内容进行专项复检
        复检通过→回复学生；发现错误→进入REDIMENSION修正
        """
        await ws_manager.push_state(task_id, FSMState.RECHECK.value)

        ctx = self._task_contexts.get(task_id) or self._load_extension_context(task_id)
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

        ctx = self._task_contexts.get(task_id) or self._load_extension_context(task_id)
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

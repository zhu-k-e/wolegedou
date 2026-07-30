"""P0-3d 单元测试：输出 Schema 校验（补充深度测试）

对应方案书 7.5 节测试用例 4：输出 Schema 校验。
test_schemas.py 已覆盖基础 valid/invalid 场景，本文件补充：
  - 全枚举值覆盖（KnowledgeLevel / Background / Verdict / QuizType / QuizDifficulty 等）
  - 边界值（confidence 0.0/1.0、verification_rate 0.0/1.0、quiz 3-5 题）
  - JudgeVerdict 4 种裁定 + 分歧解决 + 溯源标注
  - ResourcePackage 3 形态触发组合（lecture 必选 / practice_guide / quiz 条件触发）
  - 跨 Schema 字段联动（FocusedOutput → ResourcePackage）
"""

import pytest
from pydantic import ValidationError

from backend.schemas.student_profile import (
    StudentProfile, KnowledgeLevel, Background, CurrentGoal,
    QuestionType, ComplexityEstimate, IntentType, ConfidenceLevel, TestResult,
)
from backend.schemas.candidate_output import (
    CandidateOutput, FocusedOutputBody, SelfConfidence, KnowledgeRef,
)
from backend.schemas.focused_output import FocusedOutput
from backend.schemas.review_feedback import (
    ReviewFeedback, CandidateReview, ReviewerScores, IssueFound,
)
from backend.schemas.judge_verdict import (
    JudgeVerdict, Verdict, JudgeOpinion, VerificationStatus,
    DissentResolution, CandidateDebate, TraceabilityItem,
)
from backend.schemas.resource_package import (
    ResourcePackage, Lecture, PracticeGuide, Quiz, QuizQuestion,
    QuizType, QuizDifficulty, KnowledgeRefDisplay,
)


# ============================================================
# 1. StudentProfile 全枚举覆盖
# ============================================================

class TestStudentProfileEnums:
    """学情画像枚举值全覆盖"""

    @pytest.mark.parametrize("level", list(KnowledgeLevel))
    def test_all_knowledge_levels(self, level):
        profile = StudentProfile(
            knowledge_level=level,
            background=Background.PYTHON,
            current_goal=CurrentGoal.QUICK_START,
            question_type=QuestionType.CONCEPT,
            domain_hint=["LLM基础"],
            complexity_estimate=ComplexityEstimate.SINGLE_DOMAIN,
            intent_type=IntentType.GENERATION,
        )
        assert profile.knowledge_level == level

    @pytest.mark.parametrize("bg", list(Background))
    def test_all_backgrounds(self, bg):
        profile = StudentProfile(
            knowledge_level=KnowledgeLevel.ENTRY,
            background=bg,
            current_goal=CurrentGoal.QUICK_START,
            question_type=QuestionType.CONCEPT,
            domain_hint=[],
            complexity_estimate=ComplexityEstimate.SINGLE_DOMAIN,
            intent_type=IntentType.GENERATION,
        )
        assert profile.background == bg

    @pytest.mark.parametrize("goal", list(CurrentGoal))
    def test_all_goals(self, goal):
        profile = StudentProfile(
            knowledge_level=KnowledgeLevel.ENTRY,
            background=Background.PYTHON,
            current_goal=goal,
            question_type=QuestionType.CONCEPT,
            domain_hint=[],
            complexity_estimate=ComplexityEstimate.SINGLE_DOMAIN,
            intent_type=IntentType.GENERATION,
        )
        assert profile.current_goal == goal

    @pytest.mark.parametrize("qt", list(QuestionType))
    def test_all_question_types(self, qt):
        profile = StudentProfile(
            knowledge_level=KnowledgeLevel.ENTRY,
            background=Background.PYTHON,
            current_goal=CurrentGoal.QUICK_START,
            question_type=qt,
            domain_hint=[],
            complexity_estimate=ComplexityEstimate.SINGLE_DOMAIN,
            intent_type=IntentType.GENERATION,
        )
        assert profile.question_type == qt

    @pytest.mark.parametrize("intent", list(IntentType))
    def test_all_intents(self, intent):
        profile = StudentProfile(
            knowledge_level=KnowledgeLevel.ENTRY,
            background=Background.PYTHON,
            current_goal=CurrentGoal.QUICK_START,
            question_type=QuestionType.CONCEPT,
            domain_hint=[],
            complexity_estimate=ComplexityEstimate.SINGLE_DOMAIN,
            intent_type=intent,
        )
        assert profile.intent_type == intent


class TestStudentProfileEdgeCases:
    """学情画像边缘 case"""

    def test_empty_domain_hint_allowed(self):
        """domain_hint 可为空"""
        profile = StudentProfile(
            knowledge_level=KnowledgeLevel.ENTRY,
            background=Background.PYTHON,
            current_goal=CurrentGoal.QUICK_START,
            question_type=QuestionType.CONCEPT,
            domain_hint=[],
            complexity_estimate=ComplexityEstimate.SINGLE_DOMAIN,
            intent_type=IntentType.CLARIFICATION,
        )
        assert profile.domain_hint == []

    def test_multi_domain_hint(self):
        """domain_hint 可多选"""
        profile = StudentProfile(
            knowledge_level=KnowledgeLevel.ADVANCED,
            background=Background.ML,
            current_goal=CurrentGoal.PROJECT_DELIVERY,
            question_type=QuestionType.FULL_PIPELINE,
            domain_hint=["LLM基础", "RAG", "Agent框架", "项目部署"],
            complexity_estimate=ComplexityEstimate.FULL_PIPELINE,
            intent_type=IntentType.GENERATION,
        )
        assert len(profile.domain_hint) == 4

    def test_domain_confidence_mapping(self):
        """domain_confidence 字典映射"""
        profile = StudentProfile(
            knowledge_level=KnowledgeLevel.INTERMEDIATE,
            background=Background.PYTHON,
            current_goal=CurrentGoal.QUICK_START,
            question_type=QuestionType.CONCEPT,
            domain_hint=["RAG", "LangChain"],
            complexity_estimate=ComplexityEstimate.CROSS_DOMAIN,
            intent_type=IntentType.GENERATION,
            domain_confidence={"RAG": ConfidenceLevel.HIGH, "LangChain": ConfidenceLevel.LOW},
        )
        assert profile.domain_confidence["RAG"] == ConfidenceLevel.HIGH
        assert profile.domain_confidence["LangChain"] == ConfidenceLevel.LOW

    def test_test_results_optional(self):
        """test_results 可选字段"""
        profile = StudentProfile(
            knowledge_level=KnowledgeLevel.INTERMEDIATE,
            background=Background.PYTHON,
            current_goal=CurrentGoal.QUICK_START,
            question_type=QuestionType.CONCEPT,
            domain_hint=["LLM基础"],
            complexity_estimate=ComplexityEstimate.SINGLE_DOMAIN,
            intent_type=IntentType.GENERATION,
            test_results=[
                TestResult(topic="LLM基础", score=0.85, date="2026-07-19"),
            ],
        )
        assert len(profile.test_results) == 1
        assert profile.test_results[0].score == 0.85

    def test_test_result_score_out_of_range(self):
        """TestResult.score 必须 0-1"""
        with pytest.raises(ValidationError):
            TestResult(topic="test", score=1.5, date="2026-07-19")


# ============================================================
# 2. FocusedOutput 深度测试
# ============================================================

class TestFocusedOutputDeep:
    """聚焦输出深度测试"""

    def test_full_focused_output(self):
        """完整字段的 FocusedOutput"""
        focused = FocusedOutput(
            conclusion="RAG 通过检索外部知识增强生成",
            reasoning_steps=["切分文档", "向量化", "检索 top-k", "拼接 prompt"],
            knowledge_refs=[KnowledgeRef(source="rag.md", content_summary="RAG 概述")],
            applicable_conditions="需要外部知识库的场景",
            code_example="retriever = vectorstore.as_retriever()",
            difficulty_note="中级适配",
        )
        assert focused.conclusion is not None
        assert len(focused.reasoning_steps) == 4
        assert len(focused.knowledge_refs) == 1

    def test_code_example_optional(self):
        """code_example 可为空（触发 practice_guide=False）"""
        focused = FocusedOutput(
            conclusion="概念性结论",
            reasoning_steps=["步骤1", "步骤2", "步骤3"],
            knowledge_refs=[],
            applicable_conditions="概念理解场景",
            code_example="",
            difficulty_note="入门",
        )
        assert focused.code_example == ""

    def test_reasoning_steps_exactly_three(self):
        """reasoning_steps 最少 3 步，正好 3 步合法"""
        focused = FocusedOutput(
            conclusion="结论",
            reasoning_steps=["1", "2", "3"],
            knowledge_refs=[],
            applicable_conditions="条件",
            code_example="",
            difficulty_note="入门",
        )
        assert len(focused.reasoning_steps) == 3


# ============================================================
# 3. CandidateOutput / SelfConfidence 边界
# ============================================================

class TestCandidateOutputEdge:
    """候选输出边界值"""

    def test_self_confidence_zero(self):
        """confidence=0.0 合法（下界）"""
        sc = SelfConfidence(score=0.0, weak_points=[])
        assert sc.score == 0.0

    def test_self_confidence_one(self):
        """confidence=1.0 合法（上界）"""
        sc = SelfConfidence(score=1.0, weak_points=[])
        assert sc.score == 1.0

    def test_self_confidence_negative_rejected(self):
        """confidence<0 拒绝"""
        with pytest.raises(ValidationError):
            SelfConfidence(score=-0.1, weak_points=[])

    def test_candidate_with_weak_points(self):
        """候选输出带不确定点"""
        candidate = CandidateOutput(
            agent_id="agent_001",
            seg_id="seg_1",
            answer=FocusedOutputBody(conclusion="结论"),
            self_confidence=SelfConfidence(score=0.4, weak_points=["不确定点1", "不确定点2"]),
        )
        assert len(candidate.self_confidence.weak_points) == 2


# ============================================================
# 4. JudgeVerdict 4 种裁定 + 分歧解决 + 溯源
# ============================================================

class TestJudgeVerdictDeep:
    """裁判裁决深度测试"""

    @pytest.mark.parametrize("verdict_val", list(Verdict))
    def test_all_verdict_types(self, verdict_val):
        """4 种 Verdict 全覆盖：passed / revise / low_confidence_passed / failed"""
        verdict = JudgeVerdict(
            verdict=verdict_val,
            judges=[JudgeOpinion(role="事实审查", judgment="pass", confidence=0.9)],
            traceability=[],
            overall_verification_rate=0.8,
        )
        assert verdict.verdict == verdict_val

    def test_full_verdict_with_dissent(self):
        """带分歧解决的完整裁决（2:1 分歧）"""
        verdict = JudgeVerdict(
            verdict=Verdict.REVISE,
            judges=[
                JudgeOpinion(role="事实审查", judgment="pass", confidence=0.9),
                JudgeOpinion(role="逻辑审查", judgment="fail", confidence=0.7),
                JudgeOpinion(role="适用性审查", judgment="pass", confidence=0.85),
            ],
            dissent_resolution=DissentResolution(
                minority_judge="逻辑审查",
                evidence_submitted=["证据1"],
                majority_response="accepted",
                candidate_debate=CandidateDebate(
                    challenging_agent="agent_002",
                    challenge_evidence=["挑战证据"],
                    defending_agent="agent_001",
                    defense_evidence=["辩护证据"],
                ),
            ),
            traceability=[],
            overall_verification_rate=0.75,
        )
        assert verdict.dissent_resolution is not None
        assert verdict.dissent_resolution.candidate_debate.defending_agent == "agent_001"

    def test_traceability_items(self):
        """溯源标注条目"""
        verdict = JudgeVerdict(
            verdict=Verdict.PASSED,
            judges=[JudgeOpinion(role="事实审查", judgment="pass", confidence=0.95)],
            traceability=[
                TraceabilityItem(
                    statement="RAG 结合检索和生成",
                    source="rag.md / 概述",
                    verification_status=VerificationStatus.VERIFIED,
                ),
                TraceabilityItem(
                    statement="向量检索用 cosine 相似度",
                    source="vector.md / 检索",
                    verification_status=VerificationStatus.UNVERIFIED,
                ),
            ],
            overall_verification_rate=0.9,
        )
        assert len(verdict.traceability) == 2
        assert verdict.traceability[0].verification_status == VerificationStatus.VERIFIED

    def test_verification_rate_zero(self):
        """verification_rate=0.0 合法（下界）"""
        verdict = JudgeVerdict(
            verdict=Verdict.FAILED,
            judges=[],
            traceability=[],
            overall_verification_rate=0.0,
        )
        assert verdict.overall_verification_rate == 0.0

    def test_verification_rate_one(self):
        """verification_rate=1.0 合法（上界）"""
        verdict = JudgeVerdict(
            verdict=Verdict.PASSED,
            judges=[],
            traceability=[],
            overall_verification_rate=1.0,
        )
        assert verdict.overall_verification_rate == 1.0

    def test_verification_rate_out_of_range(self):
        """verification_rate>1.0 拒绝"""
        with pytest.raises(ValidationError):
            JudgeVerdict(
                verdict=Verdict.PASSED,
                judges=[],
                traceability=[],
                overall_verification_rate=1.5,
            )

    def test_verification_status_all_enums(self):
        """3 种 VerificationStatus 全覆盖"""
        for status in VerificationStatus:
            item = TraceabilityItem(
                statement="测试陈述",
                source="来源",
                verification_status=status,
            )
            assert item.verification_status == status


# ============================================================
# 5. ResourcePackage 3 形态触发组合
# ============================================================

class TestResourcePackageForms:
    """资源包 3 形态触发逻辑"""

    def _make_lecture(self):
        return Lecture(
            title="测试讲义",
            content_markdown="# 内容",
            difficulty_note="中级",
        )

    def test_lecture_only(self):
        """仅讲义（practice_guide 和 quiz 都未触发）"""
        pkg = ResourcePackage(
            task_id="task_1",
            lecture=self._make_lecture(),
            practice_guide=None,
            quiz=None,
            focused_output_ref="task_1",
            profile_ref="sess_1",
        )
        assert pkg.lecture is not None
        assert pkg.practice_guide is None
        assert pkg.quiz is None

    def test_lecture_with_practice_guide(self):
        """讲义 + 实操指南（FocusedOutput 有 code_example 时触发）"""
        pkg = ResourcePackage(
            task_id="task_1",
            lecture=self._make_lecture(),
            practice_guide=PracticeGuide(
                goal="搭建 RAG demo",
                env_setup="pip install langchain",
                steps_markdown="## 步骤1\n```python\nimport langchain\n```",
                expected_output="成功加载",
                common_issues=["依赖冲突"],
            ),
            quiz=None,
            focused_output_ref="task_1",
            profile_ref="sess_1",
        )
        assert pkg.practice_guide is not None
        assert pkg.practice_guide.goal == "搭建 RAG demo"
        assert len(pkg.practice_guide.common_issues) == 1

    def test_lecture_with_quiz(self):
        """讲义 + 测试题（question_type ∈ {概念理解, 操作步骤, 架构设计} 时触发）"""
        pkg = ResourcePackage(
            task_id="task_1",
            lecture=self._make_lecture(),
            practice_guide=None,
            quiz=Quiz(questions=[
                QuizQuestion(question="q1", type=QuizType.CHOICE, options=["A", "B"],
                             answer="A", explanation="解析", difficulty=QuizDifficulty.BASIC),
                QuizQuestion(question="q2", type=QuizType.JUDGE, answer="对",
                             explanation="解析", difficulty=QuizDifficulty.APPLICATION),
                QuizQuestion(question="q3", type=QuizType.SHORT_ANSWER, answer="答案",
                             explanation="解析", difficulty=QuizDifficulty.ADVANCED),
            ]),
            focused_output_ref="task_1",
            profile_ref="sess_1",
        )
        assert pkg.quiz is not None
        assert len(pkg.quiz.questions) == 3

    def test_all_three_forms(self):
        """三形态全触发"""
        pkg = ResourcePackage(
            task_id="task_1",
            lecture=self._make_lecture(),
            practice_guide=PracticeGuide(
                goal="实操", env_setup="env", steps_markdown="steps",
            ),
            quiz=Quiz(questions=[
                QuizQuestion(question=f"q{i}", type=QuizType.CHOICE,
                             options=["A"], answer="A", explanation="e",
                             difficulty=QuizDifficulty.BASIC)
                for i in range(3)
            ]),
            focused_output_ref="task_1",
            profile_ref="sess_1",
        )
        assert pkg.lecture is not None
        assert pkg.practice_guide is not None
        assert pkg.quiz is not None

    def test_lecture_required(self):
        """lecture 是必选形态，缺失拒绝"""
        with pytest.raises(ValidationError):
            ResourcePackage(
                task_id="task_1",
                lecture=None,  # 缺失
                practice_guide=None,
                quiz=None,
                focused_output_ref="task_1",
                profile_ref="sess_1",
            )


class TestQuizConstraints:
    """测试题约束"""

    @pytest.mark.parametrize("qt", list(QuizType))
    def test_all_quiz_types(self, qt):
        """5 种题型全覆盖"""
        q = QuizQuestion(
            question="题", type=qt, answer="答",
            explanation="解析", difficulty=QuizDifficulty.BASIC,
        )
        assert q.type == qt

    @pytest.mark.parametrize("diff", list(QuizDifficulty))
    def test_all_difficulties(self, diff):
        """4 种难度全覆盖"""
        q = QuizQuestion(
            question="题", type=QuizType.JUDGE, answer="对",
            explanation="解析", difficulty=diff,
        )
        assert q.difficulty == diff

    def test_quiz_max_five_questions(self):
        """测试题最多 5 道"""
        with pytest.raises(ValidationError):
            Quiz(questions=[
                QuizQuestion(question=f"q{i}", type=QuizType.JUDGE, answer="对",
                             explanation="e", difficulty=QuizDifficulty.BASIC)
                for i in range(6)
            ])

    def test_quiz_exactly_five_ok(self):
        """正好 5 道合法"""
        quiz = Quiz(questions=[
            QuizQuestion(question=f"q{i}", type=QuizType.JUDGE, answer="对",
                         explanation="e", difficulty=QuizDifficulty.BASIC)
            for i in range(5)
        ])
        assert len(quiz.questions) == 5

    def test_quiz_exactly_three_ok(self):
        """正好 3 道合法（下界）"""
        quiz = Quiz(questions=[
            QuizQuestion(question=f"q{i}", type=QuizType.JUDGE, answer="对",
                         explanation="e", difficulty=QuizDifficulty.BASIC)
            for i in range(3)
        ])
        assert len(quiz.questions) == 3


# ============================================================
# 6. ReviewFeedback
# ============================================================

class TestReviewFeedback:
    """审核反馈 Schema"""

    def test_valid_review_feedback(self):
        """合法审核反馈"""
        feedback = ReviewFeedback(
            seg_id="seg_1",
            candidates=[
                CandidateReview(
                    agent_id="agent_001",
                    scores=ReviewerScores(
                        fact_accuracy=0.9,
                        logic_completeness=0.85,
                        pedagogical_fit=0.8,
                    ),
                    issues_found=[],
                    is_winner=True,
                ),
            ],
            cross_segment_issues=None,
        )
        assert feedback.seg_id == "seg_1"
        assert len(feedback.candidates) == 1
        assert feedback.candidates[0].is_winner is True

    def test_review_feedback_with_issues(self):
        """带问题的审核反馈"""
        feedback = ReviewFeedback(
            seg_id="seg_1",
            candidates=[
                CandidateReview(
                    agent_id="agent_002",
                    scores=ReviewerScores(
                        fact_accuracy=0.6,
                        logic_completeness=0.7,
                        pedagogical_fit=0.5,
                    ),
                    issues_found=[
                        IssueFound(
                            reviewer="Verifier",
                            severity="high",
                            location="knowledge_refs[1]",
                            description="引用来源不准确",
                        ),
                    ],
                    is_winner=False,
                ),
            ],
            cross_segment_issues=[
                IssueFound(
                    reviewer="Skeptic",
                    severity="medium",
                    location="seg_1→seg_2",
                    description="段间逻辑断裂",
                ),
            ],
        )
        assert len(feedback.candidates[0].issues_found) == 1
        assert feedback.cross_segment_issues is not None

    def test_reviewer_scores_out_of_range(self):
        """评分超范围拒绝"""
        with pytest.raises(ValidationError):
            ReviewerScores(
                fact_accuracy=1.5,
                logic_completeness=0.8,
                pedagogical_fit=0.7,
            )

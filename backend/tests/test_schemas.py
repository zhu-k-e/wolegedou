"""SOP Schema校验测试

对应方案书 7.5 节单元测试策略 - 测试用例4：
  输出Schema校验
"""

import pytest
from pydantic import ValidationError

from backend.schemas.student_profile import StudentProfile, KnowledgeLevel, IntentType
from backend.schemas.candidate_output import CandidateOutput, SelfConfidence, FocusedOutputBody
from backend.schemas.review_feedback import ReviewFeedback, CandidateReview, ReviewerScores
from backend.schemas.focused_output import FocusedOutput
from backend.schemas.judge_verdict import JudgeVerdict, Verdict, JudgeOpinion
from backend.schemas.resource_package import ResourcePackage, Lecture, Quiz, QuizQuestion


class TestStudentProfile:
    """学情画像Schema测试"""

    def test_valid_profile(self, sample_profile_data):
        profile = StudentProfile(**sample_profile_data)
        assert profile.knowledge_level == KnowledgeLevel.INTERMEDIATE
        assert profile.intent_type == IntentType.GENERATION
        assert len(profile.domain_hint) == 2

    def test_missing_required_field(self, sample_profile_data):
        del sample_profile_data["knowledge_level"]
        with pytest.raises(ValidationError):
            StudentProfile(**sample_profile_data)

    def test_invalid_enum_value(self, sample_profile_data):
        sample_profile_data["knowledge_level"] = "专家"
        with pytest.raises(ValidationError):
            StudentProfile(**sample_profile_data)


class TestCandidateOutput:
    """候选输出Schema测试"""

    def test_valid_candidate(self):
        candidate = CandidateOutput(
            agent_id="agent_001",
            seg_id="seg_1",
            answer=FocusedOutputBody(conclusion="测试结论"),
            self_confidence=SelfConfidence(score=0.85, weak_points=["不确定点1"]),
        )
        assert candidate.agent_id == "agent_001"
        assert candidate.self_confidence.score == 0.85

    def test_confidence_score_range(self):
        with pytest.raises(ValidationError):
            SelfConfidence(score=1.5, weak_points=[])


class TestFocusedOutput:
    """聚焦输出Schema测试"""

    def test_valid_focused_output(self, sample_focused_output_data):
        focused = FocusedOutput(**sample_focused_output_data)
        assert focused.conclusion is not None
        assert len(focused.reasoning_steps) >= 3

    def test_min_reasoning_steps(self, sample_focused_output_data):
        sample_focused_output_data["reasoning_steps"] = ["步骤1", "步骤2"]
        with pytest.raises(ValidationError):
            FocusedOutput(**sample_focused_output_data)


class TestJudgeVerdict:
    """裁判裁决Schema测试"""

    def test_valid_verdict_passed(self):
        verdict = JudgeVerdict(
            verdict=Verdict.PASSED,
            judges=[
                JudgeOpinion(role="事实审查", judgment="pass", evidence=[], confidence=0.9),
                JudgeOpinion(role="逻辑审查", judgment="pass", evidence=[], confidence=0.85),
                JudgeOpinion(role="适用性审查", judgment="pass", evidence=[], confidence=0.88),
            ],
            traceability=[],
            overall_verification_rate=0.94,
        )
        assert verdict.verdict == Verdict.PASSED
        assert len(verdict.judges) == 3

    def test_invalid_verdict_enum(self):
        with pytest.raises(ValidationError):
            JudgeVerdict(
                verdict="unknown",
                judges=[],
                traceability=[],
                overall_verification_rate=0.5,
            )


class TestResourcePackage:
    """资源包Schema测试"""

    def test_valid_package_with_all_forms(self):
        pkg = ResourcePackage(
            task_id="task_001",
            lecture=Lecture(
                title="测试讲义",
                content_markdown="# 测试内容",
                difficulty_note="中级适配",
            ),
            practice_guide=None,
            quiz=Quiz(questions=[
                QuizQuestion(
                    question="测试题1", type="选择", options=["A", "B"],
                    answer="A", explanation="解析", difficulty="基础",
                ),
                QuizQuestion(
                    question="测试题2", type="选择", options=["A", "B"],
                    answer="B", explanation="解析", difficulty="应用",
                ),
                QuizQuestion(
                    question="测试题3", type="选择", options=["A", "B"],
                    answer="A", explanation="解析", difficulty="进阶",
                ),
            ]),
            focused_output_ref="task_001",
            profile_ref="sess_001",
        )
        assert pkg.lecture.title == "测试讲义"
        assert pkg.quiz is not None
        assert len(pkg.quiz.questions) == 3
        assert pkg.practice_guide is None  # 未触发

    def test_quiz_min_questions(self):
        """测试题至少3道"""
        with pytest.raises(ValidationError):
            Quiz(questions=[
                QuizQuestion(
                    question="题1", type="判断", answer="对",
                    explanation="解析", difficulty="基础",
                ),
                QuizQuestion(
                    question="题2", type="判断", answer="错",
                    explanation="解析", difficulty="应用",
                ),
            ])

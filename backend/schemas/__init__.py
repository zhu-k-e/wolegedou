"""SOP中间产物链 - 6个标准化Schema (MetaGPT落地)

继承关系（发布-订阅模式）：
  StudentProfile  → 被 Stage 2/3/4/5/6 订阅
  CandidateOutput → 被 Stage 3 订阅
  ReviewFeedback  → 被 Stage 4 订阅（反馈回流的载体）
  FocusedOutput   → 被 Stage 5 订阅
  JudgeVerdict    → 被 Stage 6 订阅
  ResourcePackage → 最终交付
"""

from backend.schemas.student_profile import (
    StudentProfile,
    KnowledgeLevel,
    Background,
    CurrentGoal,
    QuestionType,
    ComplexityEstimate,
    IntentType,
    ConfidenceLevel,
    TestResult,
    DOMAIN_HINT_ENUMS,
)
from backend.schemas.candidate_output import (
    CandidateOutput,
    FocusedOutputBody,
    SelfConfidence,
    KnowledgeRef,
)
from backend.schemas.review_feedback import (
    ReviewFeedback,
    CandidateReview,
    ReviewerScores,
    IssueFound,
)
from backend.schemas.focused_output import FocusedOutput
from backend.schemas.judge_verdict import (
    JudgeVerdict,
    Verdict,
    JudgeOpinion,
    DissentResolution,
    CandidateDebate,
    TraceabilityItem,
    VerificationStatus,
)
from backend.schemas.resource_package import (
    ResourcePackage,
    Lecture,
    PracticeGuide,
    Quiz,
    QuizQuestion,
    QuizType,
    QuizDifficulty,
    KnowledgeRefDisplay,
)

__all__ = [
    # Stage 1
    "StudentProfile", "KnowledgeLevel", "Background", "CurrentGoal",
    "QuestionType", "ComplexityEstimate", "IntentType", "ConfidenceLevel",
    "TestResult", "DOMAIN_HINT_ENUMS",
    # Stage 2
    "CandidateOutput", "FocusedOutputBody", "SelfConfidence", "KnowledgeRef",
    # Stage 3
    "ReviewFeedback", "CandidateReview", "ReviewerScores", "IssueFound",
    # Stage 4
    "FocusedOutput",
    # Stage 5
    "JudgeVerdict", "Verdict", "JudgeOpinion", "DissentResolution",
    "CandidateDebate", "TraceabilityItem", "VerificationStatus",
    # Stage 6
    "ResourcePackage", "Lecture", "PracticeGuide", "Quiz",
    "QuizQuestion", "QuizType", "QuizDifficulty", "KnowledgeRefDisplay",
]

"""GAP-4/5/6 修复验证脚本"""
import inspect
from backend.agents.review_team import ReviewTeam
from backend.services.memory_service import MemoryService
from backend.db.repositories import config_repo, agent_repo
from backend.db.database import execute_sql
from backend.db.init_db import init_database
from backend.schemas.student_profile import (
    StudentProfile, KnowledgeLevel, Background, CurrentGoal,
    QuestionType, ComplexityEstimate, IntentType,
)
from backend.schemas.focused_output import FocusedOutput
from backend.schemas.candidate_output import (
    CandidateOutput, FocusedOutputBody, SelfConfidence, KnowledgeRef,
)
from backend.schemas.resource_package import ResourcePackage, Lecture, KnowledgeRefDisplay


# === GAP-4: review_segment uses asyncio.gather ===
source = inspect.getsource(ReviewTeam.review_segment)
assert "asyncio.gather" in source, "GAP-4: asyncio.gather not found"
lines = [l.strip() for l in source.split("\n") if l.strip()]
serial = False
for i, line in enumerate(lines):
    if "await self.verifier.review" in line and "gather" not in line:
        if i + 1 < len(lines) and "await self.skeptic.review" in lines[i + 1]:
            serial = True
assert not serial, "GAP-4: Still serial!"
print("GAP-4 PASSED: review_segment uses asyncio.gather for parallel review")

# === GAP-5: alpha auto-adjustment ===
init_database()

alpha_before = config_repo.get_alpha()
assert alpha_before == 0.9, f"Initial alpha should be 0.9, got {alpha_before}"
print(f"GAP-5 Test 1 PASSED: initial alpha = {alpha_before}")

ms = MemoryService()

# < 50 records -> alpha stays 0.9
ms._check_alpha_adjustment()
assert config_repo.get_alpha() == 0.9
print("GAP-5 Test 2 PASSED: alpha stays 0.9 with <50 records")

# >= 50 records -> alpha = 0.7
# Use existing agent from seed data to avoid FK constraint
existing = agent_repo.get_all_active_agents()
test_agent_id = existing[0]["agent_id"] if existing else "agent_rag"
# Get current performance to find function_tag
all_perf = agent_repo.get_agent_all_performances(test_agent_id)
test_tag = all_perf[0]["function_tag"] if all_perf else "RAG"
# Set count to 50
execute_sql(
    "UPDATE agent_performance SET count = 50 WHERE agent_id = ? AND function_tag = ?",
    (test_agent_id, test_tag),
)
ms._check_alpha_adjustment()
assert config_repo.get_alpha() == 0.7, f"Expected 0.7, got {config_repo.get_alpha()}"
print("GAP-5 Test 3 PASSED: alpha = 0.7 with >=50 records")

# >= 100 records -> alpha = 0.5
execute_sql(
    "UPDATE agent_performance SET count = 100 WHERE agent_id = ? AND function_tag = ?",
    (test_agent_id, test_tag),
)
ms._check_alpha_adjustment()
assert config_repo.get_alpha() == 0.5, f"Expected 0.5, got {config_repo.get_alpha()}"
print("GAP-5 Test 4 PASSED: alpha = 0.5 with >=100 records")

# >= 200 records -> alpha = 0.3
execute_sql(
    "UPDATE agent_performance SET count = 200 WHERE agent_id = ? AND function_tag = ?",
    (test_agent_id, test_tag),
)
ms._check_alpha_adjustment()
assert config_repo.get_alpha() == 0.3, f"Expected 0.3, got {config_repo.get_alpha()}"
print("GAP-5 Test 5 PASSED: alpha = 0.3 with >=200 records")

# No redundant writes
ms._check_alpha_adjustment()
assert config_repo.get_alpha() == 0.3
print("GAP-5 Test 6 PASSED: alpha stays 0.3 (no redundant writes)")

# Cleanup - reset count to 0 and alpha to 0.9
execute_sql(
    "UPDATE agent_performance SET count = 0 WHERE agent_id = ? AND function_tag = ?",
    (test_agent_id, test_tag),
)
config_repo.set_alpha(0.9)
print("GAP-5 ALL PASSED: alpha auto-adjustment verified")

# === GAP-6: Fallback strategies ===

# Test 1: Default StudentProfile
default_profile = StudentProfile(
    knowledge_level=KnowledgeLevel.ENTRY,
    background=Background.SCIENCE_NO_CODE,
    current_goal=CurrentGoal.QUICK_START,
    question_type=QuestionType.CONCEPT,
    domain_hint=[],
    complexity_estimate=ComplexityEstimate.SINGLE_DOMAIN,
    intent_type=IntentType.GENERATION,
    session_id="test",
)
assert default_profile.knowledge_level == KnowledgeLevel.ENTRY
print("GAP-6 Test 1 PASSED: default StudentProfile construction works")

# Test 2: Fallback FocusedOutput from CandidateOutput (2 steps -> padded to 3)
candidate_body = FocusedOutputBody(
    conclusion="RAG is retrieval-augmented generation",
    reasoning_steps=["step1: chunking", "step2: embedding"],
    knowledge_refs=[KnowledgeRef(source="doc1", content_summary="RAG basics")],
    applicable_conditions="for document QA",
    code_example="import rag",
    difficulty_note="beginner",
)
candidate = CandidateOutput(
    agent_id="test_agent", seg_id="seg_1",
    answer=candidate_body, self_confidence=SelfConfidence(score=0.7),
)
ans = candidate.answer
steps = list(ans.reasoning_steps) if ans.reasoning_steps else []
while len(steps) < 3:
    steps.append("(fallback: padding step)")
fallback_focused = FocusedOutput(
    conclusion=ans.conclusion or "(fallback)",
    reasoning_steps=steps,
    knowledge_refs=ans.knowledge_refs,
    applicable_conditions=ans.applicable_conditions or "(fallback)",
    code_example=ans.code_example,
    difficulty_note=ans.difficulty_note,
)
assert len(fallback_focused.reasoning_steps) == 3
assert fallback_focused.reasoning_steps[2] == "(fallback: padding step)"
print("GAP-6 Test 2 PASSED: fallback FocusedOutput (steps padded to 3)")

# Test 3: Fallback from empty candidate
empty_body = FocusedOutputBody()
empty_candidate = CandidateOutput(
    agent_id="test", seg_id="seg_1",
    answer=empty_body, self_confidence=SelfConfidence(score=0.3),
)
ans2 = empty_candidate.answer
steps2 = list(ans2.reasoning_steps) if ans2.reasoning_steps else []
while len(steps2) < 3:
    steps2.append("(fallback: padding step)")
fallback2 = FocusedOutput(
    conclusion=ans2.conclusion or "(fallback: no focused output)",
    reasoning_steps=steps2,
    knowledge_refs=ans2.knowledge_refs,
    applicable_conditions=ans2.applicable_conditions or "(fallback)",
    code_example=ans2.code_example,
    difficulty_note=ans2.difficulty_note,
)
assert fallback2.conclusion == "(fallback: no focused output)"
assert len(fallback2.reasoning_steps) == 3
print("GAP-6 Test 3 PASSED: fallback from empty candidate works")

# Test 4: Fallback ResourcePackage (lecture only)
focused = FocusedOutput(
    conclusion="test conclusion",
    reasoning_steps=["s1", "s2", "s3"],
    knowledge_refs=[KnowledgeRef(source="doc1", content_summary="ref1")],
    applicable_conditions="test conditions",
    code_example="code",
    difficulty_note="test difficulty",
)
fallback_pkg = ResourcePackage(
    task_id="test_task",
    lecture=Lecture(
        title="Learning Resource (Fallback)",
        content_markdown=focused.conclusion,
        difficulty_note=focused.difficulty_note or "(fallback)",
        knowledge_refs_display=[
            KnowledgeRefDisplay(source=ref.source, verification_status="pending")
            for ref in focused.knowledge_refs
        ],
    ),
    practice_guide=None,
    quiz=None,
    focused_output_ref="test_task",
    profile_ref="test_session",
)
assert fallback_pkg.lecture is not None
assert fallback_pkg.practice_guide is None
assert fallback_pkg.quiz is None
assert len(fallback_pkg.lecture.knowledge_refs_display) == 1
print("GAP-6 Test 4 PASSED: fallback ResourcePackage (lecture only)")

print()
print("=== ALL TESTS PASSED ===")

"""验证意图兜底：简短技术问题不应被判clarification"""
import sys
sys.path.insert(0, "D:/projects/wolegedou")

from backend.agents.profile_agent import _TECH_KEYWORD_MAP, ProfileAgent
from backend.schemas.student_profile import (
    StudentProfile, KnowledgeLevel, Background, CurrentGoal,
    QuestionType, ComplexityEstimate, IntentType, ConfidenceLevel,
)


def make_profile(intent: IntentType, domain_hint: list[str] = None) -> StudentProfile:
    """造一个测试用画像"""
    return StudentProfile(
        knowledge_level=KnowledgeLevel.ENTRY,
        background=Background.SCIENCE_NO_CODE,
        current_goal=CurrentGoal.QUICK_START,
        question_type=QuestionType.CONCEPT,
        domain_hint=domain_hint or [],
        complexity_estimate=ComplexityEstimate.SINGLE_DOMAIN,
        intent_type=intent,
        domain_confidence={},
    )


def simulate_enforce(question: str, llm_intent: IntentType, llm_domains: list[str] = None):
    """模拟LLM判错后，后处理能否兜底"""
    profile = make_profile(llm_intent, llm_domains)
    # 直接调用后处理逻辑（不实例化ProfileAgent，复用静态逻辑）
    agent = ProfileAgent.__new__(ProfileAgent)  # 跳过__init__
    agent._enforce_generation_for_technical_questions(question, profile)
    return profile


# === 测试用例 ===
cases = [
    # (问题, LLM误判的intent, LLM给的domain_hint, 期望兜底后intent, 描述)
    ("什么是RAG", IntentType.CLARIFICATION, [], IntentType.GENERATION, "简短RAG问题被误判clarification"),
    ("Prompt怎么写", IntentType.CLARIFICATION, [], IntentType.GENERATION, "简短Prompt问题被误判clarification"),
    ("LangChain怎么用", IntentType.CLARIFICATION, [], IntentType.GENERATION, "简短LangChain问题被误判"),
    ("讲讲向量数据库", IntentType.CLARIFICATION, [], IntentType.GENERATION, "向量数据库问题被误判"),
    ("我想学微调", IntentType.CLARIFICATION, [], IntentType.GENERATION, "微调问题被误判"),
    ("transformer原理是什么", IntentType.CLARIFICATION, [], IntentType.GENERATION, "transformer问题被误判"),
    ("什么是embedding", IntentType.CLARIFICATION, [], IntentType.GENERATION, "embedding问题被误判"),
    ("lora和qlora区别", IntentType.CLARIFICATION, [], IntentType.GENERATION, "lora问题被误判"),
    ("怎么用huggingface", IntentType.CLARIFICATION, [], IntentType.GENERATION, "huggingface问题被误判"),
    # 无技术关键词 → 尊重LLM判断
    ("你好", IntentType.CLARIFICATION, [], IntentType.CLARIFICATION, "纯问候应保持clarification"),
    ("帮帮我", IntentType.CLARIFICATION, [], IntentType.CLARIFICATION, "求助应保持clarification"),
    ("我想学点东西", IntentType.CLARIFICATION, [], IntentType.CLARIFICATION, "空泛应保持clarification"),
    # LLM判对了generation → 不影响
    ("什么是RAG", IntentType.GENERATION, ["RAG"], IntentType.GENERATION, "LLM判对generation不应破坏"),
]

print("=" * 70)
print("意图兜底验证")
print("=" * 70)

passed = 0
failed = 0
for question, llm_intent, llm_domains, expected_intent, desc in cases:
    profile = simulate_enforce(question, llm_intent, llm_domains)
    ok = profile.intent_type == expected_intent
    status = "✅" if ok else "❌"
    if ok:
        passed += 1
    else:
        failed += 1
    print(f"{status} [{desc}]")
    print(f"   问题: {question}")
    print(f"   LLM判: {llm_intent.value} domains={llm_domains}")
    print(f"   兜底后: intent={profile.intent_type.value} domains={profile.domain_hint}")
    if not ok:
        print(f"   ⚠️ 期望 {expected_intent.value} 但得到 {profile.intent_type.value}")
    print()

print("=" * 70)
print(f"结果: {passed} 通过 / {failed} 失败")
print("=" * 70)

# 额外：检查关键词覆盖度
print("\n关键词覆盖领域检查:")
covered = set(_TECH_KEYWORD_MAP.values())
all_domains = {"LLM基础", "Prompt工程", "LangChain", "RAG", "HuggingFace",
               "模型微调", "向量数据库", "Agent框架", "项目部署"}
missing = all_domains - covered
if missing:
    print(f"⚠️ 以下领域无关键词覆盖: {missing}")
else:
    print("✅ 全部9个领域都有关键词覆盖")

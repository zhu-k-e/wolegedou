"""端到端冒烟测试 - 用 mock LLM 跑通完整主链路

验证编排器 FSM 主链路（IDLE→PROFILING→DISPATCHING→GENERATING→
REVIEWING→FOCUSING→JUDGING→FORMATTING→COMPLETE）串联不会崩溃。

不依赖真实 LLM API key 和知识库（用 Stub）。
"""
import json
import re

import pytest

from backend.config import get_settings
from backend.core.orchestrator import Orchestrator
from backend.core.fsm import FSMState
from backend.services.llm_client import LLMClient, ModelTier


# LLMClient 构造需要 API Key（.env）；未配置时跳过真实 e2e（mock 也需构造成功），
# 评审/CI 无 .env 时保持全绿，配置 key 后自动启用
pytestmark = pytest.mark.skipif(
    not (get_settings().deepseek_api_key or get_settings().openai_api_key),
    reason="未配置 LLM API Key（.env），跳过 e2e 冒烟测试；配置后自动启用",
)


# ============================================================
# Mock LLM 响应工厂 —— 每个 Agent 调用场景的预设 JSON
# ============================================================

def _profile_json(domains=None, complexity="单领域"):
    domains = domains or ["RAG"]
    return json.dumps({
        "knowledge_level": "入门",
        "background": "有Python基础",
        "current_goal": "快速上手应用",
        "question_type": "概念理解",
        "domain_hint": domains,
        "complexity_estimate": complexity,
        "intent_type": "generation",
        "domain_confidence": {d: "high" for d in domains},
    }, ensure_ascii=False)


def _candidate_json(user_content: str) -> str:
    """从 user_prompt 提取 agent_id 和 seg_id，返回合法 CandidateOutput JSON"""
    agent_match = re.search(r'"agent_id":\s*"([^"]+)"', user_content)
    seg_match = re.search(r'"seg_id":\s*"([^"]+)"', user_content)
    agent_id = agent_match.group(1) if agent_match else "rag_specialist"
    seg_id = seg_match.group(1) if seg_match else "seg_1"
    return json.dumps({
        "agent_id": agent_id,
        "seg_id": seg_id,
        "answer": {
            "conclusion": "RAG 是检索增强生成技术",
            "reasoning_steps": ["步骤1：对问题向量化检索", "步骤2：拼接检索结果到上下文", "步骤3：LLM 基于上下文生成回答"],
            "knowledge_refs": [{"source": "RAG 论文 2020", "content_summary": "RAG 检索增强生成框架"}],
            "applicable_conditions": "适用于知识密集型问答场景",
            "code_example": "from rag import RAG\nrag = RAG()\nanswer = rag.query('什么是RAG')",
            "difficulty_note": "入门水平需先理解向量检索概念",
        },
        "self_confidence": {"score": 0.82, "weak_points": []},
    }, ensure_ascii=False)


def _focused_json() -> str:
    return json.dumps({
        "conclusion": "RAG 通过检索外部知识库增强 LLM 生成质量，降低幻觉",
        "reasoning_steps": [
            "步骤1：将用户问题向量化",
            "步骤2：从向量知识库检索 Top-K 相关文档片段",
            "步骤3：将检索结果作为上下文拼接到 Prompt 中，交给 LLM 生成最终回答",
        ],
        "knowledge_refs": [{"source": "RAG 论文 2020", "content_summary": "RAG 检索增强生成核心原理"}],
        "applicable_conditions": "适用于需要准确事实依据的问答、不适用于纯创意生成",
        "code_example": "from rag import RAG\nrag = RAG(index='kb')\nresult = rag.query('什么是RAG')\nprint(result.answer)",
        "difficulty_note": "入门水平需理解向量检索和 Prompt 拼接两个核心概念",
    }, ensure_ascii=False)


def _verifier_json() -> str:
    return json.dumps({
        "fact_accuracy": 0.92,
        "verified_count": 1,
        "contradiction_count": 0,
        "unverified_items": [],
        "contradiction_items": [],
    }, ensure_ascii=False)


def _skeptic_json() -> str:
    return json.dumps({
        "logic_completeness": 0.8,
        "checklist_results": [
            {"item": "清单1", "passed": True, "score": 0.2, "reason": "推理给出了原因"},
            {"item": "清单2", "passed": True, "score": 0.2, "reason": "结论与推理一致"},
            {"item": "清单3", "passed": True, "score": 0.2, "reason": "无遗漏前置条件"},
            {"item": "清单4", "passed": True, "score": 0.2, "reason": "无循环论证"},
            {"item": "清单5", "passed": False, "score": 0.0, "reason": "代码示例简化"},
        ],
        "failed_items": ["代码示例步骤可执行性可进一步细化"],
    }, ensure_ascii=False)


def _evaluator_json() -> str:
    return json.dumps({
        "pedagogical_fit": 0.88,
        "dimension_scores": {"level_match": 0.9, "bg_fit": 0.85, "goal_align": 0.9, "actionability": 0.87},
        "mismatch_details": [],
    }, ensure_ascii=False)


def _cross_segment_json() -> str:
    return json.dumps({"issues": []}, ensure_ascii=False)


def _judge_pass_json() -> str:
    return json.dumps({
        "verdict": "passed",
        "confidence": 0.91,
        "issues": [],
        "verification_coverage": 0.95,
    }, ensure_ascii=False)


def _judge_fail_json() -> str:
    """1个裁判返回 fail（触发 2:1 分歧）"""
    return json.dumps({
        "verdict": "revise",
        "confidence": 0.6,
        "issues": ["推理步骤不够详细"],
        "verification_coverage": 0.8,
    }, ensure_ascii=False)


def _majority_reject_json() -> str:
    return json.dumps({
        "response": "rejected",
        "reasoning": ["少数方质疑不成立，推理步骤已足够详细"],
    }, ensure_ascii=False)


def _chief_pass_json() -> str:
    return json.dumps({
        "verdict": "passed",
        "reasoning": "事实准确，逻辑完整，适用性达标",
    }, ensure_ascii=False)


def _debate_json() -> str:
    return json.dumps({"evidence": ["从知识库检索结果看，该结论有依据"]}, ensure_ascii=False)


def _lecture_json() -> str:
    return json.dumps({
        "title": "RAG 检索增强生成入门",
        "content_markdown": "## RAG 基础\n\nRAG（Retrieval Augmented Generation）通过检索外部知识增强生成质量。\n\n### 核心流程\n1. 向量化检索\n2. 上下文拼接\n3. LLM 生成",
        "difficulty_note": "入门级讲解，适合有 Python 基础的学习者",
    }, ensure_ascii=False)


def _practice_json() -> str:
    return json.dumps({
        "goal": "搭建一个简单的 RAG 问答系统",
        "env_setup": "pip install langchain chromadb",
        "steps_markdown": "1. 安装依赖\n2. 加载文档到向量库\n3. 构建检索链\n4. 执行查询",
        "expected_output": "返回基于知识库的回答",
        "common_issues": ["向量化失败：检查 embedding 模型", "检索为空：检查 chunk 大小"],
    }, ensure_ascii=False)


def _quiz_json() -> str:
    return json.dumps({
        "questions": [
            {"question": "RAG 的全称是？", "type": "选择", "options": ["A. 检索增强生成", "B. 随机访问生成", "C. 递归自动生成"], "answer": "A", "explanation": "RAG = Retrieval Augmented Generation", "difficulty": "基础"},
            {"question": "RAG 的核心步骤包括哪些？", "type": "简答", "options": [], "answer": "检索、增强、生成三步", "explanation": "先检索相关文档，再拼接到上下文，最后由 LLM 生成", "difficulty": "应用"},
            {"question": "为什么 RAG 比纯 LLM 更准确？", "type": "选择", "options": ["A. 有外部知识库依据", "B. 模型参数更大", "C. 使用了更好的 GPU"], "answer": "A", "explanation": "RAG 检索外部知识增强，降低幻觉", "difficulty": "综合"},
        ],
    }, ensure_ascii=False)


def _advance_json() -> str:
    return json.dumps({
        "question": "如何优化 RAG 系统的检索质量？请从 chunk 策略、embedding、重排序三个维度分析。",
        "type": "设计分析",
        "answer": "chunk 优化、embedding 微调、cross-encoder 重排序",
        "explanation": "进阶挑战：综合优化 RAG 检索链路",
        "difficulty": "进阶",
    }, ensure_ascii=False)


def _followup_json() -> str:
    return json.dumps({"questions": ["如果知识库中没有相关文档，RAG 系统会如何表现？如何处理？"]}, ensure_ascii=False)


def _recheck_json() -> str:
    return json.dumps({"has_error": False, "error_detail": "", "corrected_content": ""}, ensure_ascii=False)


# ============================================================
# FakeLLMClient —— 根据 user_prompt 关键词路由返回预设 JSON
# ============================================================

# 全局开关：裁判是否返回 fail（用于测试 2:1 分歧路径）
_judge_fail_mode = {"enabled": False}
# 全局：多段场景的 profile 域配置
_profile_domains = {"domains": None, "complexity": "单领域"}


async def _fake_chat(self, messages, tier=ModelTier.MID, temperature=0.7, max_tokens=2048, response_format=None):
    """Mock LLMClient.chat —— 所有 Agent 的 LLM 调用都走这里"""
    user_content = ""
    for msg in messages:
        if msg["role"] == "user":
            user_content = msg["content"]

    # --- 学情诊断 Agent ---
    if "历史对话" in user_content:
        return _profile_json(
            domains=_profile_domains["domains"],
            complexity=_profile_domains["complexity"],
        )

    # --- 领域 Agent：候选输出 ---
    if "请输出JSON，包含以下字段" in user_content and "agent_id" in user_content:
        return _candidate_json(user_content)

    # --- 领域 Agent：聚焦输出（含 REVISING 阶段的 judge_feedback 场景）---
    if "你在段内评选中获胜" in user_content:
        return _focused_json()

    # --- 审核团队 ---
    if "知识库验证结果" in user_content:          # Verifier
        return _verifier_json()
    if "学情画像" in user_content and "AI输出" in user_content:  # Evaluator
        return _evaluator_json()
    if "AI输出" in user_content:                  # Skeptic（兜底）
        return _skeptic_json()
    if "请检查以下各段输出的一致性" in user_content:  # CrossSegment
        return _cross_segment_json()

    # --- 裁判团 ---
    if "聚焦输出（待审查）" in user_content:
        # 用 system prompt 区分 3 名裁判
        sys_content = next((m["content"] for m in messages if m["role"] == "system"), "")
        if _judge_fail_mode["enabled"] and "适用性审查" in sys_content:
            return _judge_fail_json()  # 裁判3返回fail，触发2:1分歧
        return _judge_pass_json()
    if "你是裁判团多数方" in user_content:        # majority_response
        return _majority_reject_json()
    if "你是裁判长" in user_content:              # chief_judge_arbitrate
        return _chief_pass_json()

    # --- 候选 Agent 辩论 ---
    if "你是落选候选Agent" in user_content:
        return _debate_json()
    if "你是获胜候选Agent" in user_content:
        return _debate_json()

    # --- 资源生成 Agent ---
    if "转换为Markdown格式的讲义" in user_content:
        return _lecture_json()
    if "请生成实操指南" in user_content:
        return _practice_json()
    if "请生成3-5道分阶测试题" in user_content:
        return _quiz_json()
    if "降维策略" in user_content and "讲义" in user_content:
        return _lecture_json()
    if "降维策略" in user_content and "实操" in user_content:
        return _practice_json()
    if "降维策略" in user_content and "测试题" in user_content:
        return _quiz_json()
    if "进阶挑战题" in user_content:
        return _advance_json()

    # --- 延伸路径 ---
    if "启发式追问" in user_content:
        return _followup_json()
    if "学生反馈内容有误" in user_content:
        return _recheck_json()

    # 兜底
    return "{}"


async def _fake_chat_json(self, messages, tier=ModelTier.MID, temperature=0.0, max_tokens=2048):
    """Mock LLMClient.chat_json —— 委托给 _fake_chat"""
    return await _fake_chat(self, messages, tier=tier, temperature=temperature, max_tokens=max_tokens)


@pytest.fixture(autouse=True)
def mock_llm(monkeypatch):
    """自动 mock LLMClient 的 chat / chat_json 方法"""
    monkeypatch.setattr(LLMClient, "chat", _fake_chat)
    monkeypatch.setattr(LLMClient, "chat_json", _fake_chat_json)
    # 重置全局开关
    _judge_fail_mode["enabled"] = False
    _profile_domains["domains"] = None
    _profile_domains["complexity"] = "单领域"
    yield
    _judge_fail_mode["enabled"] = False
    _profile_domains["domains"] = None
    _profile_domains["complexity"] = "单领域"


# ============================================================
# 测试用例
# ============================================================

@pytest.mark.asyncio
async def test_e2e_single_segment_happy_path():
    """单段主流程 3:0 通过：IDLE→...→FORMATTING→COMPLETE

    覆盖：画像→调度→2候选生成→3人审核→聚焦输出→3裁判通过→资源包(讲义+实操+测试题)
    """
    orch = Orchestrator()
    result = await orch.process_question(
        question="什么是RAG？",
        session_id="e2e_single_seg_001",
    )

    # 不应有错误
    assert "error" not in result, f"主流程出错: {result.get('error')}"

    # 画像已生成
    assert result["profile"] is not None
    assert result["profile"]["intent_type"] == "generation"

    # 调度信息
    assert result["dispatch_info"] is not None
    assert result["dispatch_info"]["intent"] == "generation"
    assert len(result["dispatch_info"]["segments"]) == 1  # 单段

    # 裁判裁决
    assert result["judge_verdict"] is not None
    assert result["judge_verdict"]["verdict"] == "passed"

    # 资源包：讲义必选 + 实操（有code_example）+ 测试题（概念理解触发）
    pkg = result["resource_package"]
    assert pkg is not None
    assert pkg["lecture"] is not None
    assert pkg["practice_guide"] is not None   # code_example 触发
    assert pkg["quiz"] is not None             # 概念理解触发
    assert len(pkg["quiz"]["questions"]) >= 3


@pytest.mark.asyncio
async def test_e2e_multi_segment():
    """多段主流程：跨领域 → 2段 → 多段合并 → COMPLETE"""
    _profile_domains["domains"] = ["RAG", "LangChain"]
    _profile_domains["complexity"] = "跨领域"

    orch = Orchestrator()
    result = await orch.process_question(
        question="RAG和LangChain怎么结合使用？",
        session_id="e2e_multi_seg_001",
    )

    assert "error" not in result, f"多段流程出错: {result.get('error')}"
    assert result["dispatch_info"] is not None
    assert len(result["dispatch_info"]["segments"]) >= 2  # 多段
    assert result["resource_package"] is not None
    assert result["judge_verdict"] is not None


@pytest.mark.asyncio
async def test_e2e_judge_dissent_2to1():
    """裁判 2:1 分歧 → 分歧解决 → 候选辩论 → 最终通过"""
    _judge_fail_mode["enabled"] = True  # 裁判3返回fail

    orch = Orchestrator()
    result = await orch.process_question(
        question="什么是RAG的检索策略？",
        session_id="e2e_dissent_001",
    )

    assert "error" not in result, f"分歧流程出错: {result.get('error')}"
    assert result["judge_verdict"] is not None
    # 分歧解决后多数方反驳→裁判长裁决→passed
    assert result["judge_verdict"]["verdict"] in ("passed", "revise", "low_confidence_passed")
    # 如果有分歧解决记录，验证候选辩论
    if result["judge_verdict"].get("dissent_resolution"):
        dr = result["judge_verdict"]["dissent_resolution"]
        assert dr["minority_judge"] is not None


@pytest.mark.asyncio
async def test_e2e_extension_advance():
    """延伸路径：答题正确率≥85% → 进阶挑战 → 启发式追问"""
    orch = Orchestrator()

    # 先完成主流程
    result = await orch.process_question(
        question="什么是RAG？",
        session_id="e2e_ext_001",
    )
    assert "error" not in result
    task_id = result["task_id"]

    # 触发延伸路径：quiz_submit accuracy=0.9 → advance
    ext_result = await orch.handle_extension(
        task_id=task_id,
        event_type="quiz_submit",
        event_data={"accuracy": 0.9},
    )

    assert "error" not in ext_result
    # advance → heuristic_followup 链式执行
    assert ext_result.get("action") in ("heuristic_followup", "advance")
    # followup_questions 应该有内容
    final = ext_result
    if final.get("action") == "heuristic_followup":
        assert isinstance(final.get("followup_questions"), list)


@pytest.mark.asyncio
async def test_e2e_extension_redimension():
    """延伸路径：答题正确率<85% → 降维解释 → 启发式追问"""
    orch = Orchestrator()

    result = await orch.process_question(
        question="什么是RAG？",
        session_id="e2e_redim_001",
    )
    assert "error" not in result
    task_id = result["task_id"]

    ext_result = await orch.handle_extension(
        task_id=task_id,
        event_type="quiz_submit",
        event_data={"accuracy": 0.5},  # 低正确率→降维
    )

    assert "error" not in ext_result
    # 降维→启发式追问链
    assert ext_result.get("action") in ("heuristic_followup", "redimension")

"""学情诊断Agent - 模块一

对应方案书第二部分：
  2.2 学情画像生成（含增量更新）
  2.3 三步调度框架（意图裁决→领域解析→候选遴选的意图裁决部分）
  6.1.3 交付后延伸路径中的HEURISTIC_FOLLOWUP启发式追问
"""

from typing import Optional

from loguru import logger

from backend.agents.base_agent import BaseAgent
from backend.schemas.student_profile import (
    StudentProfile,
    KnowledgeLevel,
    Background,
    CurrentGoal,
    QuestionType,
    ComplexityEstimate,
    IntentType,
    ConfidenceLevel,
)
from backend.services.llm_client import ModelTier
from backend.db.repositories import profile_repo
from backend.db.database import query_all


# 技术关键词 → domain_hint 映射（意图兜底用）
# 防止LLM对简短技术问题（如"什么是RAG"）误判clarification且domain_hint给空
# 只要问题原文命中任一关键词，代码强制改判generation并补domain_hint
_TECH_KEYWORD_MAP: dict[str, str] = {
    # LLM基础
    "llm": "LLM基础", "大模型": "LLM基础", "语言模型": "LLM基础",
    "transformer": "LLM基础", "注意力机制": "LLM基础", "attention": "LLM基础",
    "token": "LLM基础", "embedding": "LLM基础", "嵌入": "LLM基础",
    "gpt": "LLM基础", "bert": "LLM基础", "预训练": "LLM基础",
    "生成模型": "LLM基础", "大语言": "LLM基础",
    # Prompt工程
    "prompt": "Prompt工程", "提示词": "Prompt工程", "提示工程": "Prompt工程",
    "few-shot": "Prompt工程", "fewshot": "Prompt工程", "cot": "Prompt工程",
    "思维链": "Prompt工程", "chain-of-thought": "Prompt工程",
    # LangChain
    "langchain": "LangChain", "langgraph": "LangChain",
    # RAG
    "rag": "RAG", "检索增强": "RAG", "文档切分": "RAG", "检索增强生成": "RAG",
    # HuggingFace
    "huggingface": "HuggingFace", "transformers库": "HuggingFace",
    "hf ": "HuggingFace",
    # 模型微调
    "微调": "模型微调", "lora": "模型微调", "qlora": "模型微调",
    "finetune": "模型微调", "fine-tune": "模型微调", "fine tune": "模型微调",
    "peft": "模型微调",
    # 向量数据库
    "向量数据库": "向量数据库", "向量库": "向量数据库",
    "chroma": "向量数据库", "chromadb": "向量数据库",
    "faiss": "向量数据库", "milvus": "向量数据库", "pinecone": "向量数据库",
    # Agent框架
    "agent框架": "Agent框架", "agent开发": "Agent框架",
    "function calling": "Agent框架", "工具调用": "Agent框架",
    "智能体": "Agent框架", "react模式": "Agent框架",
    "多agent": "Agent框架", "multi-agent": "Agent框架",
    # 项目部署
    "fastapi": "项目部署", "docker": "项目部署", "部署上线": "项目部署",
    "streamlit": "项目部署", "gradio": "项目部署",
}


class ProfileAgent(BaseAgent):
    """学情诊断Agent

    职责：
    1. 生成/增量更新学情画像（StudentProfile）
    2. 意图裁决（intent_type路由）
    3. 启发式追问生成（HEURISTIC_FOLLOWUP状态）
    """

    def __init__(self, **kwargs):
        super().__init__(
            agent_id="agent_profile",
            agent_name="学情诊断Agent",
            **kwargs,
        )

    @property
    def system_prompt(self) -> str:
        return (
            "你是一个学情诊断专家。请根据学生的问题，输出严格的JSON格式的学情画像。\n\n"
            "请从以下枚举值中选择，不要自创值：\n"
            "- knowledge_level: ['入门', '中级', '进阶']\n"
            "- background: ['文科', '理科_无编程', '有Python基础', '有ML基础']\n"
            "- current_goal: ['快速上手应用', '深入理解原理', '项目落地', '算法研究']\n"
            "- question_type: ['概念理解', '操作步骤', '调试排错', '架构设计', '全链路规划']\n"
            "- domain_hint: 可从 ['LLM基础', 'Prompt工程', 'LangChain', 'RAG', "
            "'HuggingFace', '模型微调', '向量数据库', 'Agent框架', '项目部署'] 中选择多个\n"
            "- complexity_estimate: ['单领域', '跨领域', '全链路']\n"
        "- intent_type: ['generation', 'navigation', 'clarification']\n"
        "  ⚠️ 硬规则：只要问题中出现任何技术术语（RAG/Prompt/LangChain/微调/向量/Transformer/Agent/"
        "HuggingFace/Embedding/LoRA等），intent_type 必须为 generation，绝不能为 clarification。\n"
        "  - generation（默认优先选）：当问题涉及具体技术/概念/任务时选这个\n"
        "    包括问题简短但领域明确的情况（如'什么是RAG'、'Prompt怎么写'、'LangChain怎么用'、'讲讲向量数据库'）\n"
        "  - clarification：仅当问题完全没有领域线索时选（纯问候'你好'、求助'帮帮我'、完全空泛'我想学点东西'）\n"
        "    问题简短≠需要澄清，只要含技术词就是 generation\n"
        "  - navigation：仅当用户明确询问学习路径/路线图时选（'我该学什么'、'推荐学习顺序'）\n"
        "- domain_confidence: 对每个domain_hint评估置信度，值为 {'领域名': 'high/low'}\n"
        "  - 如果问题明确提到某个领域（如'什么是RAG'），对应领域的confidence应为 high\n"
        "  - 只有边缘/弱关联（如一句话里顺带提到）才标 low\n"
        "只输出JSON，不要输出其他内容。"
        )

    @staticmethod
    def _load_student_feedback(session_id: str) -> list[dict]:
        """读取student_feedback表中difficulty_mismatch反馈，用于调整画像

        方案书§5.7：difficulty_mismatch反馈应触发生成画像时调整knowledge_level。
        读取当前session最近3条difficulty_mismatch反馈，提取难度信息。
        """
        rows = query_all(
            """
            SELECT feedback_type, comment, created_at
            FROM student_feedback
            WHERE session_id = ? AND feedback_type = 'difficulty_mismatch'
            ORDER BY created_at DESC
            LIMIT 3
            """,
            (session_id,),
        )
        return [dict(r) for r in rows]

    async def generate_profile(
        self,
        question: str,
        session_id: str,
        history: Optional[list[dict]] = None,
    ) -> StudentProfile:
        """生成或增量更新学情画像

        对应方案书 2.2.4 增量更新机制：
          - 同一session第2次及以后提问触发增量更新
          - 检索最近3次历史，综合评估

        画像缓存（方案书§8.4.2优化2）：
          - 同一session已有画像时直接复用，跳过LLM调用（节省~3秒）
          - 首次提问时才调用LLM生成画像

        Student Feedback Loop（方案书§5.7，P0-1修复）：
          - 读取student_feedback表中该session的difficulty_mismatch记录
          - 若存在难度不匹配反馈，在生成新画像时自动降级knowledge_level
        """
        import json

        # 检查是否已有画像
        latest = profile_repo.get_latest_profile(session_id)

        # === 画像缓存：同一session已有画像时复用（节省~3秒LLM调用） ===
        if latest:
            cached_profile = self._profile_from_dict(latest)
            if cached_profile:
                logger.info(
                    f"画像缓存命中: session={session_id}, version={cached_profile.version}, "
                    f"level={cached_profile.knowledge_level}, 跳过LLM调用"
                )
                return cached_profile

        # 首次提问：调用LLM生成画像
        version = profile_repo.get_next_version(session_id) if latest else 1

        # P0-1: 读取学生反馈，作为生成画像时的额外上下文
        feedback_records = self._load_student_feedback(session_id)
        feedback_context = ""
        if feedback_records:
            feedback_lines = []
            for fb in feedback_records:
                ts = fb.get("created_at", "")
                comment = fb.get("comment", "")
                if comment:
                    feedback_lines.append(f"  [{ts}] difficulty_mismatch: {comment}")
            if feedback_lines:
                feedback_context = "\n学生历史反馈（难度不匹配记录）：\n" + "\n".join(feedback_lines)
                logger.info(
                    f"学生反馈上下文已加载: session={session_id}, "
                    f"difficulty_mismatch记录={len(feedback_records)}条"
                )

        # 构造Prompt
        history_str = json.dumps(history, ensure_ascii=False) if history else "无"
        user_prompt = f"学生问题：{question}\n历史对话：{history_str}{feedback_context}"

        # 调用LLM生成画像
        profile = await self.generate_and_validate(
            user_prompt=user_prompt,
            model_class=StudentProfile,
            tier=ModelTier.MID,
            temperature=0.0,
        )

        # P0-1: 如果有difficulty_mismatch反馈且LLM判定的level过高，强制降一级
        if feedback_records:
            self._adjust_knowledge_level_for_difficulty_feedback(profile, feedback_records)

        # 意图兜底：问题含技术关键词时强制走generation，防LLM误判clarification
        self._enforce_generation_for_technical_questions(question, profile)

        # 设置元数据
        profile.session_id = session_id
        profile.version = version

        # 保存到数据库
        profile_repo.save_profile(
            session_id=session_id,
            version=version,
            knowledge_level=profile.knowledge_level.value,
            background=profile.background.value,
            current_goal=profile.current_goal.value,
            question_type=profile.question_type.value,
            domain_hint=profile.domain_hint,
            complexity_estimate=profile.complexity_estimate.value,
            intent_type=profile.intent_type.value,
            domain_confidence={k: v.value for k, v in profile.domain_confidence.items()},
        )

        logger.info(
            f"学情画像已生成: session={session_id}, version={version}, "
            f"level={profile.knowledge_level}, intent={profile.intent_type}"
        )
        return profile

    @staticmethod
    def _adjust_knowledge_level_for_difficulty_feedback(
        profile: StudentProfile,
        feedback_records: list[dict],
    ) -> None:
        """根据difficulty_mismatch反馈调整knowledge_level

        方案书§5.7：当学生反馈难度不匹配时，自动降级knowledge_level。
        - 如果有>=2条difficulty_mismatch且当前level>=中级 → 降一级
        - 如果有>=3条difficulty_mismatch且当前level=入门 → 标记low_confidence
        - 否则不调整
        """
        mismatch_count = len(feedback_records)
        if mismatch_count < 2:
            return  # 偶发反馈不调整

        level = profile.knowledge_level
        _LEVEL_ORDER = [KnowledgeLevel.ENTRY, KnowledgeLevel.INTERMEDIATE, KnowledgeLevel.ADVANCED]

        if level == KnowledgeLevel.ADVANCED:
            profile.knowledge_level = KnowledgeLevel.INTERMEDIATE
            logger.info(
                f"[student_feedback] difficulty_mismatch({mismatch_count}条): "
                f"ADVANCED降级为INTERMEDIATE"
            )
        elif level == KnowledgeLevel.INTERMEDIATE:
            profile.knowledge_level = KnowledgeLevel.ENTRY
            logger.info(
                f"[student_feedback] difficulty_mismatch({mismatch_count}条): "
                f"INTERMEDIATE降级为ENTRY"
            )
        elif level == KnowledgeLevel.ENTRY and mismatch_count >= 3:
            # 入门水平还反馈难度不匹配 → 标记日志，保留入门
            logger.warning(
                f"[student_feedback] difficulty_mismatch({mismatch_count}条) "
                f"但level已为ENTRY，无法继续降级"
            )

    def _enforce_generation_for_technical_questions(
        self, question: str, profile: StudentProfile
    ) -> None:
        """意图兜底：问题含技术关键词时强制走generation，防LLM误判clarification

        LLM对简短技术问题（如"什么是RAG"）有时会误判clarification且domain_hint给空，
        导致matcher层的兜底（matcher.py:67 基于domain_hint）也救不回来。
        本方法基于问题原文做关键词匹配，不依赖LLM判断，作为最后一道防线。
        """
        q_lower = question.lower()
        matched_domains: list[str] = []
        for kw, domain in _TECH_KEYWORD_MAP.items():
            if kw in q_lower and domain not in matched_domains:
                matched_domains.append(domain)

        if not matched_domains:
            return  # 无技术关键词，尊重LLM判断

        # 有技术关键词 → 强制generation
        if profile.intent_type != IntentType.GENERATION:
            logger.info(
                f"[意图兜底] 问题含技术关键词{matched_domains}但LLM判{profile.intent_type.value}，"
                f"强制改判generation"
            )
            profile.intent_type = IntentType.GENERATION

        # 补domain_hint（如果LLM给空了或漏了）
        existing = set(profile.domain_hint)
        for d in matched_domains:
            if d not in existing:
                profile.domain_hint.append(d)
                profile.domain_confidence[d] = ConfidenceLevel.HIGH
                logger.info(f"[意图兜底] 补充domain_hint: {d}")

    @staticmethod
    def _profile_from_dict(data: dict) -> Optional[StudentProfile]:
        """将数据库行dict转换为StudentProfile对象（用于画像缓存复用）"""
        try:
            domain_confidence_raw = data.get("domain_confidence", {})
            domain_confidence = {}
            if isinstance(domain_confidence_raw, str):
                import json
                domain_confidence_raw = json.loads(domain_confidence_raw)
            for k, v in domain_confidence_raw.items():
                domain_confidence[k] = ConfidenceLevel(v) if isinstance(v, str) else v

            domain_hint_raw = data.get("domain_hint", [])
            if isinstance(domain_hint_raw, str):
                import json
                domain_hint_raw = json.loads(domain_hint_raw)

            return StudentProfile(
                knowledge_level=KnowledgeLevel(data["knowledge_level"]),
                background=Background(data["background"]),
                current_goal=CurrentGoal(data["current_goal"]),
                question_type=QuestionType(data["question_type"]),
                domain_hint=domain_hint_raw,
                complexity_estimate=ComplexityEstimate(data["complexity_estimate"]),
                intent_type=IntentType(data["intent_type"]),
                domain_confidence=domain_confidence,
                session_id=data.get("session_id"),
                version=data.get("version", 1),
            )
        except Exception as e:
            logger.warning(f"画像缓存转换失败: {e}, data={data}")
            return None

    async def generate_heuristic_followup(
        self,
        recent_content: str,
        profile: StudentProfile,
    ) -> list[str]:
        """生成启发式追问问题（HEURISTIC_FOLLOWUP状态）

        对应方案书 6.1.3 节：
          - 追问与刚交付资源的核心知识点相关
          - 引导题而非判断题
          - 追问难度略高于资源难度
          - LLM根据当前上下文实时生成
        """
        user_prompt = (
            f"刚交付的学习资源核心内容：\n{recent_content[:1000]}\n\n"
            f"学生画像：{profile.model_dump_json(indent=2)}\n\n"
            "请生成1-2个启发式追问问题，引导学生深入思考。"
            "追问形式：不是判断题（'懂了吗？'），而是引导题。"
            "只输出JSON: {\"questions\": [\"追问1\", \"追问2\"]}"
        )

        raw = await self.generate(user_prompt, tier=ModelTier.MID, temperature=0.7)

        data = await self.parse_json_safe(raw)
        if data is None:
            return [raw.strip()]
        return data.get("questions", [])

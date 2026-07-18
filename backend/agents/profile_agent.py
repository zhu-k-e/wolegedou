"""学情诊断Agent - 模块一

对应方案书第二部分：
  2.2 学情画像生成（含增量更新）
  2.3 三步调度框架（意图裁决→领域解析→候选遴选的意图裁决部分）
  6.1.3 交付后延伸路径中的HEURISTIC_FOLLOWUP启发式追问
"""

from typing import Optional

from loguru import logger

from backend.agents.base_agent import BaseAgent
from backend.schemas.student_profile import StudentProfile
from backend.services.llm_client import ModelTier
from backend.db.repositories import profile_repo


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
            "- domain_confidence: 对每个domain_hint评估置信度，值为 {'领域名': 'high/low'}\n"
            "只输出JSON，不要输出其他内容。"
        )

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
        """
        import json

        # 检查是否需要增量更新
        latest = profile_repo.get_latest_profile(session_id)
        version = profile_repo.get_next_version(session_id) if latest else 1

        # 构造Prompt
        history_str = json.dumps(history, ensure_ascii=False) if history else "无"
        user_prompt = f"学生问题：{question}\n历史对话：{history_str}"

        # 调用LLM生成画像
        profile = await self.generate_and_validate(
            user_prompt=user_prompt,
            model_class=StudentProfile,
            tier=ModelTier.MID,
            temperature=0.0,
        )

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

        # 简单解析
        import json
        try:
            data = json.loads(raw)
            return data.get("questions", [])
        except json.JSONDecodeError:
            return [raw.strip()]

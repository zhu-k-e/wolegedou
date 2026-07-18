"""Agent基类 - 统一LLM调用接口

所有Agent（学情诊断、领域Agent、审核团队、裁判团、资源生成）继承此类。
"""

from typing import Optional

from loguru import logger

from backend.services.llm_client import LLMClient, ModelTier, get_llm_client
from backend.services.json_validator import JSONValidator, get_json_validator
from backend.services.knowledge_base import KnowledgeBaseInterface, get_knowledge_base
from backend.core.exceptions import LLMCallError, SchemaValidationError


class BaseAgent:
    """Agent基类

    提供统一的LLM调用、JSON校验、知识库访问能力。
    子类通过实现 system_prompt 和调用 generate 来完成具体任务。
    """

    def __init__(
        self,
        agent_id: str,
        agent_name: str,
        llm_client: Optional[LLMClient] = None,
        json_validator: Optional[JSONValidator] = None,
        knowledge_base: Optional[KnowledgeBaseInterface] = None,
    ):
        self.agent_id = agent_id
        self.agent_name = agent_name
        self._llm = llm_client or get_llm_client()
        self._validator = json_validator or get_json_validator()
        self._kb = knowledge_base or get_knowledge_base()

    @property
    def system_prompt(self) -> str:
        """子类覆盖：返回此Agent的System Prompt"""
        raise NotImplementedError("子类必须实现 system_prompt 属性")

    async def generate(
        self,
        user_prompt: str,
        tier: ModelTier = ModelTier.MID,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        use_json_mode: bool = True,
        history: Optional[list[dict]] = None,
    ) -> str:
        """调用LLM生成内容

        Args:
            user_prompt: 用户Prompt（含具体任务描述）
            tier: 模型等级
            temperature: 温度（评分场景用0，生成场景用0.7）
            max_tokens: 最大输出token数
            use_json_mode: 是否使用JSON模式（第一层原生约束）
            history: 之前的对话历史（同一会话上下文），格式为[{"role":"user","content":"..."},{"role":"assistant","content":"..."}]

        Returns:
            LLM输出的原始文本
        """
        messages = [
            {"role": "system", "content": self.system_prompt},
        ]
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": user_prompt})

        try:
            if use_json_mode:
                return await self._llm.chat_json(
                    messages, tier=tier, temperature=temperature, max_tokens=max_tokens
                )
            else:
                return await self._llm.chat(
                    messages, tier=tier, temperature=temperature, max_tokens=max_tokens
                )
        except Exception as e:
            logger.error(f"Agent {self.agent_id} LLM调用失败: {e}")
            raise LLMCallError(f"Agent {self.agent_name} 生成失败: {e}") from e

    async def generate_and_validate(
        self,
        user_prompt: str,
        model_class,
        tier: ModelTier = ModelTier.MID,
        temperature: float = 0.0,
        max_tokens: int = 2048,
        schema_hint: Optional[str] = None,
        history: Optional[list[dict]] = None,
    ):
        """调用LLM生成内容并通过三层兜底校验

        Args:
            user_prompt: 用户Prompt
            model_class: 目标Pydantic模型类
            tier: 模型等级
            temperature: 温度
            max_tokens: 最大输出token数
            schema_hint: Schema描述（第三层LLM修复时使用）
            history: 之前的对话历史（同一会话上下文）

        Returns:
            校验通过的Pydantic模型实例

        Raises:
            SchemaValidationError: 三层兜底均失败时抛出
        """
        raw_output = await self.generate(
            user_prompt, tier=tier, temperature=temperature, max_tokens=max_tokens,
            history=history,
        )

        result = await self._validator.validate(raw_output, model_class, schema_hint)

        if result is None:
            raise SchemaValidationError(
                model_class.__name__,
                f"三层兜底校验均失败, raw_output前100字符: {raw_output[:100]}"
            )

        return result

    async def search_knowledge(self, query: str, top_k: int = 3) -> list:
        """搜索知识库（便捷方法）"""
        return await self._kb.search(query, top_k=top_k)

    def __repr__(self):
        return f"<{self.__class__.__name__} id={self.agent_id} name={self.agent_name}>"

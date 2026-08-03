"""LLM客户端 - OpenAI兼容接口，支持分层模型策略

对应方案书 8.5 节分层模型配置：
  - 中档(DeepSeek-V3)：候选生成/审核/资源生成
  - 高档(GPT-4o)：聚焦输出/裁判团裁决
  - 低档(GPT-4o-mini)：轻量判断
"""

from enum import Enum
from typing import Optional

from loguru import logger
from openai import AsyncOpenAI

from backend.config import get_settings


class ModelTier(str, Enum):
    """模型等级"""
    MID = "mid"      # 中档：DeepSeek-V3
    HIGH = "high"    # 高档：GPT-4o
    LOW = "low"      # 低档：GPT-4o-mini


class LLMClient:
    """LLM调用客户端，支持分层模型选择"""

    def __init__(self):
        settings = get_settings()
        # 中档模型客户端（DeepSeek）
        self._mid_client = AsyncOpenAI(
            api_key=settings.deepseek_api_key,
            base_url=settings.deepseek_base_url,
            max_retries=1,  # 关掉 SDK 默认重试叠加，避免单次卡慢时 60×3=180s
        )
        self._mid_model = settings.deepseek_model

        # 高档模型客户端（OpenAI GPT-4o）
        self._high_client = AsyncOpenAI(
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
            max_retries=1,  # 同上
        )
        self._high_model = settings.openai_model

        # 低档模型复用OpenAI客户端
        self._low_model = settings.openai_mini_model

    async def chat(
        self,
        messages: list[dict],
        tier: ModelTier = ModelTier.MID,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        response_format: Optional[dict] = None,
    ) -> str:
        """调用LLM对话接口

        Args:
            messages: OpenAI格式的消息列表
            tier: 模型等级
            temperature: 温度参数（评分场景用0，生成场景用0.7）
            max_tokens: 最大输出token数
            response_format: 响应格式约束（JSON模式）

        Returns:
            LLM输出的文本内容
        """
        client, model = self._get_client_and_model(tier)
        settings = get_settings()

        try:
            kwargs = {
                "model": model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "timeout": settings.llm_timeout,
            }
            if response_format:
                kwargs["response_format"] = response_format

            response = await client.chat.completions.create(**kwargs)
            choice = response.choices[0]
            content = choice.message.content

            # 输出截断检测：finish_reason == "length" 表示达到 max_tokens 上限被硬截断。
            # 截断的 JSON 必然残缺（缺右括号/引号），会导致三层兜底校验全部失败并抛
            # SchemaValidationError。此前该情况完全静默，只能看到"三层兜底均失败"的
            # 表象而无法定位根因，故显式告警。
            finish_reason = getattr(choice, "finish_reason", None)
            if finish_reason == "length":
                logger.warning(
                    f"LLM输出被截断(达到max_tokens上限) [tier={tier.value}, "
                    f"model={model}, max_tokens={max_tokens}, 实际输出长度={len(content or '')}]"
                    f" —— JSON 极可能残缺，请上调 max_tokens"
                )

            logger.debug(
                f"LLM调用成功 [tier={tier.value}, model={model}], "
                f"输出长度={len(content or '')}, finish_reason={finish_reason}"
            )
            return content

        except Exception as e:
            logger.error(f"LLM调用失败 [tier={tier.value}, model={model}]: {e}")
            raise

    async def chat_json(
        self,
        messages: list[dict],
        tier: ModelTier = ModelTier.MID,
        temperature: float = 0.0,
        max_tokens: int = 2048,
    ) -> str:
        """调用LLM并请求JSON格式输出（第一层原生约束）

        对应方案书 3.5.2 节第一层兜底：使用response_format模式
        """
        return await self.chat(
            messages=messages,
            tier=tier,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
        )

    def _get_client_and_model(self, tier: ModelTier) -> tuple[AsyncOpenAI, str]:
        """根据等级获取对应的客户端和模型名"""
        if tier == ModelTier.MID:
            return self._mid_client, self._mid_model
        elif tier == ModelTier.HIGH:
            return self._high_client, self._high_model
        else:
            return self._high_client, self._low_model


# 全局单例
_llm_client: Optional[LLMClient] = None


def get_llm_client() -> LLMClient:
    """获取LLM客户端单例"""
    global _llm_client
    if _llm_client is None:
        _llm_client = LLMClient()
    return _llm_client

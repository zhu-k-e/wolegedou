"""LLM客户端 - OpenAI兼容接口，支持分层模型策略

对应方案书 8.5 节分层模型配置：
  - 中档(DeepSeek-V3)：候选生成/审核/资源生成
  - 高档(GPT-4o)：聚焦输出/裁判团裁决
  - 低档(GPT-4o-mini)：轻量判断
"""

import asyncio
from enum import Enum
from typing import Optional

from loguru import logger
from openai import AsyncOpenAI

from backend.config import get_settings

# 截断重试时 max_tokens 翻倍的封顶值，避免无限膨胀成本
# 模型输出 token 上限（按模型名识别；用于截断重试时避免越界触发 400）
# 注意：此处是输出长度上限，不是上下文长度。
_MODEL_TOKEN_LIMITS = {
    "qwen-max": 8192,
    "qwen-plus": 8192,
    "qwen-turbo": 8192,
    "qwen": 8192,
    "deepseek-v4-flash": 8192,
    "deepseek-v3": 8192,
    "deepseek-reasoner": 8192,
    "gpt-4o": 16384,
    "gpt-4o-mini": 16384,
    "gpt-4": 8192,
}
_DEFAULT_OUTPUT_CAP = 8192


class ModelTier(str, Enum):
    """模型等级"""
    MID = "mid"      # 中档：DeepSeek-V3
    HIGH = "high"    # 高档：GPT-4o
    LOW = "low"      # 低档：GPT-4o-mini


class LLMClient:
    """LLM调用客户端，支持分层模型选择"""

    def __init__(self):
        settings = get_settings()
        # 中档模型客户端（DeepSeek）——
        # 用 deepseek-chat 而非 v4-flash：实测 v4-flash 偶发空输出（降级根因），chat 稳定有内容
        self._mid_client = AsyncOpenAI(
            api_key=settings.deepseek_api_key,
            base_url=settings.deepseek_base_url,
            max_retries=1,  # 关掉 SDK 默认重试叠加，避免单次卡慢时 60×3=180s
        )
        self._mid_model = "deepseek-chat"

        # 高档模型客户端（Qwen / DashScope）—— 用户充值后于 2026-08-06 恢复
        # 方案书 A 混合档：HIGH=聚焦输出/裁判团裁决(qwen-max)，LOW=轻量判断(qwen-turbo)
        self._high_client = AsyncOpenAI(
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
            max_retries=1,
        )
        self._high_model = settings.openai_model  # qwen-max
        self._low_model = settings.openai_mini_model  # qwen-turbo

    @staticmethod
    def _get_model_token_cap(model: str) -> int:
        """根据模型名返回输出 token 上限，避免截断重试时越界触发 400。"""
        model_lower = model.lower()
        for prefix, cap in _MODEL_TOKEN_LIMITS.items():
            if prefix in model_lower:
                return cap
        return _DEFAULT_OUTPUT_CAP

    @staticmethod
    def _backoff(attempt: int) -> float:
        """指数退避（秒），封顶 8s，避免长尾等待"""
        return min(2 ** attempt, 8)

    async def chat(
        self,
        messages: list[dict],
        tier: ModelTier = ModelTier.MID,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        response_format: Optional[dict] = None,
        max_retries: int = 2,
    ) -> str:
        """调用LLM对话接口（健壮版：自动处理截断/空输出/瞬时故障）

        Args:
            messages: OpenAI格式的消息列表
            tier: 模型等级
            temperature: 温度参数（评分场景用0，生成场景用0.7）
            max_tokens: 最大输出token数
            response_format: 响应格式约束（JSON模式）
            max_retries: 额外重试次数（不含首次），用于截断/空输出/瞬时异常

        根因修复（对照旧版"只告警不重试"）：
          - 输出被截断(finish_reason=="length")：把 max_tokens 翻倍重试（按模型
            上限封顶，如 qwen-max=8192/gpt-4o=16384），拿回完整答案而非残缺 JSON
            ——这是"答不出来/报错"最常见根因，也是质量杀手（答案被腰斩）。
          - 空输出：瞬时故障（限流/抖动/模型偶发），退避后重试。
          - 瞬时异常(网络/超时/5xx)：退避后重试，耗尽才上抛。
          - 鉴权/配额错误(401/402/403/404)：不可重试，快速失败（不刷三遍红字）。
        正常路径不受影响；仅在确有问题时多花 1~2 次调用，把"报错/降级"
        转回"完整高质量答案"。
        """
        client, model = self._get_client_and_model(tier)
        settings = get_settings()
        last_exc: Optional[Exception] = None

        # 按模型上限裁剪初始 max_tokens，避免传入值越界触发 400
        model_cap = self._get_model_token_cap(model)
        if max_tokens > model_cap:
            logger.warning(
                f"传入 max_tokens={max_tokens} 超过模型 {model} 上限 {model_cap}，"
                f"已自动裁剪"
            )
            max_tokens = model_cap

        for attempt in range(max_retries + 1):
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
                content = choice.message.content or ""
                finish_reason = getattr(choice, "finish_reason", None)

                # —— 空输出：瞬时故障，重试 ——
                if not content.strip():
                    logger.warning(
                        f"LLM返回空输出 [tier={tier.value}, model={model}, "
                        f"attempt={attempt}/{max_retries}]，"
                        f"{self._backoff(attempt)}s 后重试"
                    )
                    if attempt < max_retries:
                        await asyncio.sleep(self._backoff(attempt))
                        continue
                    logger.error(
                        f"LLM连续返回空输出已放弃 [tier={tier.value}, model={model}]"
                    )
                    return content

                # —— 截断：上调 max_tokens 重试，拿完整答案 ——
                if finish_reason == "length":
                    model_cap = self._get_model_token_cap(model)
                    logger.warning(
                        f"LLM输出被截断(达到max_tokens上限) [tier={tier.value}, "
                        f"model={model}, max_tokens={max_tokens}, 实际长度={len(content)}, "
                        f"model_cap={model_cap}]; "
                        f"attempt={attempt}/{max_retries}"
                    )
                    if attempt < max_retries and max_tokens < model_cap:
                        max_tokens = min(max_tokens * 2, model_cap)
                        logger.warning(f"上调 max_tokens 至 {max_tokens} 重试")
                        continue
                    logger.error(
                        f"LLM输出在{max_retries + 1}次尝试后仍被截断(已封顶"
                        f"{max_tokens}) [tier={tier.value}] —— 返回残缺内容交由上层校验"
                    )
                    return content

                logger.debug(
                    f"LLM调用成功 [tier={tier.value}, model={model}], "
                    f"输出长度={len(content)}, finish_reason={finish_reason}"
                )
                return content

            except Exception as e:
                last_exc = e
                # —— 不可重试错误：鉴权/配额/资源不存在(401/402/403/404)。
                # 重试无意义（余额不会几秒内恢复、key 不会自动变有效），快速失败
                # 避免刷三遍红字又白等退避。瞬时故障(网络/超时/5xx)才走下面重试 ——
                status_code = getattr(e, "status_code", None)
                if status_code in (401, 402, 403, 404):
                    logger.error(
                        f"LLM调用不可重试错误 [tier={tier.value}, model={model}, "
                        f"status={status_code}]: {e}"
                    )
                    raise
                logger.error(
                    f"LLM调用失败 [tier={tier.value}, model={model}, "
                    f"attempt={attempt}/{max_retries}]: {e}"
                )
                if attempt < max_retries:
                    await asyncio.sleep(self._backoff(attempt))
                    continue
                logger.error(
                    f"LLM调用在{max_retries + 1}次尝试后放弃 [tier={tier.value}]"
                )
                raise

        # 理论上不可达；兜底抛出最后一次异常
        if last_exc:
            raise last_exc
        return ""

    async def chat_json(
        self,
        messages: list[dict],
        tier: ModelTier = ModelTier.MID,
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> str:
        """调用LLM并请求JSON格式输出（第一层原生约束）

        对应方案书 3.5.2 节第一层兜底：使用response_format模式。
        复用 chat 的健壮重试（截断/空输出自动重试）。
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

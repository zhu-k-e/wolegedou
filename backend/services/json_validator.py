"""JSON输出质量控制 - 三层兜底机制

对应方案书 3.5.2 节：
  第一层：原生约束（response_format，成本0，延迟0，覆盖率~85%）
  第二层：正则修复（成本0，延迟<1ms，覆盖率追加~10%）
  第三层：LLM修复（成本1次调用，延迟+2-3s，覆盖率追加~3-5%）
最终预期合格率：≥97%
"""

import json
import re
from typing import Optional, Type, TypeVar

from loguru import logger
from pydantic import BaseModel, ValidationError

from backend.services.llm_client import LLMClient, ModelTier


T = TypeVar("T", bound=BaseModel)


class JSONValidator:
    """三层JSON兜底校验服务"""

    def __init__(self, llm_client: Optional[LLMClient] = None):
        self._llm = llm_client

    async def validate(
        self,
        raw_output: str,
        model_class: Type[T],
        schema_hint: Optional[str] = None,
    ) -> Optional[T]:
        """三层兜底校验LLM输出

        Args:
            raw_output: LLM原始输出文本
            model_class: 目标Pydantic模型类
            schema_hint: Schema描述（第三层LLM修复时使用）

        Returns:
            校验通过的Pydantic模型实例，失败返回None
        """
        # 第一层：直接解析 + Pydantic校验
        result = self._layer1_direct_parse(raw_output, model_class)
        if result is not None:
            return result

        # 第二层：正则修复 + 重新校验
        result = self._layer2_regex_repair(raw_output, model_class)
        if result is not None:
            return result

        # 第三层：LLM修复（需要LLM客户端）
        if self._llm is not None:
            result = await self._layer3_llm_repair(raw_output, model_class, schema_hint)
            if result is not None:
                return result

        logger.warning(f"三层兜底均失败，raw_output前100字符: {raw_output[:100]}")
        return None

    async def parse_json_safe(
        self,
        raw_output: str,
        schema_hint: Optional[str] = None,
    ) -> Optional[dict]:
        """三层兜底解析JSON（返回dict，不绑定Pydantic模型）

        用于输出结构简单、不值得定义Pydantic模型的场景
        （如辩论证据、裁判意见、启发式追问等）。
        复用三层兜底机制：直接解析 → 正则提取 → LLM修复。
        """
        # 第一层：直接解析
        try:
            return json.loads(raw_output)
        except json.JSONDecodeError:
            pass

        # 第二层：正则提取
        json_str = self._extract_json_block(raw_output)
        if json_str is not None:
            try:
                return json.loads(json_str)
            except json.JSONDecodeError:
                pass

        # 第三层：LLM修复
        if self._llm is not None:
            try:
                messages = [
                    {
                        "role": "system",
                        "content": (
                            "你是一个JSON修复助手。以下文本应该是JSON但格式有误，"
                            "请修复并输出有效JSON。只输出JSON，不要输出其他内容。"
                        ),
                    },
                    {"role": "user", "content": f"原始输出:\n{raw_output}"},
                ]
                repaired = await self._llm.chat_json(messages, tier=ModelTier.MID)
                return json.loads(repaired)
            except Exception as e:
                logger.debug(f"parse_json_safe 第三层修复失败: {e}")

        logger.warning(f"parse_json_safe 三层均失败, raw前100字符: {raw_output[:100]}")
        return None

    # ============================================================
    # 第一层：直接解析
    # ============================================================

    def _layer1_direct_parse(self, raw: str, model_class: Type[T]) -> Optional[T]:
        """直接JSON解析 + Pydantic校验"""
        try:
            # 尝试直接解析
            data = json.loads(raw)
            return model_class.model_validate(data)
        except (json.JSONDecodeError, ValidationError) as e:
            logger.debug(f"第一层解析失败: {type(e).__name__}")
            return None

    # ============================================================
    # 第二层：正则修复
    # ============================================================

    def _layer2_regex_repair(self, raw: str, model_class: Type[T]) -> Optional[T]:
        """正则提取 + 截断补齐 + 字段级修复"""
        try:
            json_str = self._extract_json_block(raw)
            if json_str is None:
                # 首次提取失败（多半是截断导致括号不平衡），尝试补齐
                json_str = self._repair_truncated_json(raw)
            if json_str is None:
                return None

            try:
                data = json.loads(json_str)
            except json.JSONDecodeError:
                # 二次尝试截断补齐（覆盖首轮漏网的残缺形态）
                repaired = self._repair_truncated_json(raw)
                if repaired is None:
                    return None
                try:
                    data = json.loads(repaired)
                except json.JSONDecodeError:
                    return None

            # 字段级修复
            data = self._repair_fields(data, model_class)

            return model_class.model_validate(data)

        except (json.JSONDecodeError, ValidationError, Exception) as e:
            logger.debug(f"第二层修复失败: {type(e).__name__}: {e}")
            return None

    def _extract_json_block(self, raw: str) -> Optional[str]:
        """提取最外层 {...} JSON块（仅当括号平衡时返回）"""
        # 去除可能的 ```json 标记
        cleaned = re.sub(r"```(?:json)?\s*", "", raw).strip()

        # 找最外层花括号
        start = cleaned.find("{")
        if start == -1:
            return None

        depth = 0
        for i in range(start, len(cleaned)):
            if cleaned[i] == "{":
                depth += 1
            elif cleaned[i] == "}":
                depth -= 1
                if depth == 0:
                    return cleaned[start:i + 1]

        return None

    def _repair_truncated_json(self, raw: str) -> Optional[str]:
        """截断兜底：针对 finish_reason=='length' 残留的不完整 JSON，补齐未闭合括号。

        仅处理"括号不平衡"（截断特征）的情况；对结构完好但内容非法（如字段名错）
        的 JSON 不做臆造式修复，避免产出伪合法的错误答案。
        """
        cleaned = re.sub(r"```(?:json)?\s*", "", raw).strip()
        start = cleaned.find("{")
        if start == -1:
            return None

        depth = 0
        last_brace = -1
        for i in range(start, len(cleaned)):
            if cleaned[i] == "{":
                depth += 1
            elif cleaned[i] == "}":
                depth -= 1
                last_brace = i
                if depth == 0:
                    # 已平衡，无需补齐
                    return cleaned[start:i + 1]

        # 截断：depth>0，从 start 到末尾补齐未闭合括号
        if depth <= 0:
            return None
        truncated = cleaned[start:]
        # 若末尾字符串未闭合（奇数个引号），先补引号再补括号，避免引号吞掉右括号
        if truncated.count('"') % 2 == 1:
            truncated += '"'
        truncated += "}" * depth
        return truncated

    def _repair_fields(self, data: dict, model_class: Type[T]) -> dict:
        """字段级修复：类型转换、默认值填充"""
        schema = model_class.model_json_schema()
        properties = schema.get("properties", {})

        for field_name, field_info in properties.items():
            if field_name not in data:
                continue

            value = data[field_name]
            expected_type = field_info.get("type")

            # number字段收到string → 尝试float
            if expected_type == "number" and isinstance(value, str):
                try:
                    data[field_name] = float(value)
                except ValueError:
                    pass

            # integer字段收到string → 尝试int
            elif expected_type == "integer" and isinstance(value, str):
                try:
                    data[field_name] = int(value)
                except ValueError:
                    pass

            # 枚举校验：不在白名单 → 设为默认值
            if "enum" in field_info and value not in field_info["enum"]:
                default = field_info.get("default")
                if default is not None:
                    data[field_name] = default

        return data

    # ============================================================
    # 第三层：LLM修复
    # ============================================================

    async def _layer3_llm_repair(
        self,
        raw: str,
        model_class: Type[T],
        schema_hint: Optional[str],
    ) -> Optional[T]:
        """发送原始输出+Schema+错误信息，要求LLM重新生成（仅重试1次）"""
        if self._llm is None:
            return None

        try:
            schema_str = schema_hint or json.dumps(
                model_class.model_json_schema(), ensure_ascii=False, indent=2
            )

            messages = [
                {
                    "role": "system",
                    "content": (
                        "你是一个JSON修复助手。以下文本应该是符合指定JSON Schema的JSON，"
                        "但格式有误。请修复格式问题，输出符合Schema的有效JSON。"
                        "只输出JSON，不要输出其他内容。"
                    ),
                },
                {
                    "role": "user",
                    "content": f"JSON Schema:\n{schema_str}\n\n原始输出:\n{raw}",
                },
            ]

            repaired = await self._llm.chat_json(messages, tier=ModelTier.MID)
            data = json.loads(repaired)
            return model_class.model_validate(data)

        except Exception as e:
            logger.debug(f"第三层LLM修复失败: {e}")
            return None


# 全局单例
_validator: Optional[JSONValidator] = None


def get_json_validator() -> JSONValidator:
    """获取JSON校验器单例"""
    global _validator
    if _validator is None:
        # 注入LLM客户端，使第三层LLM修复可用
        from backend.services.llm_client import get_llm_client
        _validator = JSONValidator(llm_client=get_llm_client())
    return _validator

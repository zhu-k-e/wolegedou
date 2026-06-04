"""
Agent 基础类。
所有Agent继承此类，统一接口：接收输入 → 调用LLM → 返回结构化输出。
"""

from openai import OpenAI
from config import LLM_CONFIG
from loguru import logger
import json


class BaseAgent:
    """
    Agent基类。
    子类只需定义 system_prompt 和 process() 方法。
    """

    def __init__(self, name: str, system_prompt: str):
        self.name = name
        self.system_prompt = system_prompt
        self.client = OpenAI(
            api_key=LLM_CONFIG["api_key"],
            base_url=LLM_CONFIG["base_url"],
            timeout=LLM_CONFIG["timeout"],
        )

    def call_llm(self, user_message: str, temperature: float = None) -> str:
        """
        调用大模型。
        返回原始文本。
        """
        temp = temperature if temperature is not None else LLM_CONFIG["temperature"]
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": user_message},
        ]
        logger.info(f"[{self.name}] 调用LLM, model={LLM_CONFIG['model']}, temp={temp}")
        response = self.client.chat.completions.create(
            model=LLM_CONFIG["model"],
            messages=messages,
            temperature=temp,
            max_tokens=LLM_CONFIG["max_tokens"],
        )
        content = response.choices[0].message.content
        logger.info(f"[{self.name}] LLM返回 {len(content)} 字符")
        return content

    def parse_json_output(self, raw_text: str) -> dict:
        """
        从LLM返回文本中提取JSON。
        处理常见的格式问题（多余Markdown标记、中文引号等）。
        """
        text = raw_text.strip()
        # 去掉可能的 ```json ... ``` 包裹
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            logger.warning(f"[{self.name}] JSON解析失败，返回原始文本")
            return {"raw_output": raw_text, "parse_error": True}

    def run(self, input_data: dict) -> dict:
        """
        子类重写此方法，实现具体的Agent逻辑。
        默认实现：将输入转为JSON字符串 → 调用LLM → 解析JSON输出。
        """
        user_msg = json.dumps(input_data, ensure_ascii=False, indent=2)
        raw = self.call_llm(user_msg)
        return self.parse_json_output(raw)

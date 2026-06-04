"""
审核纠偏Agent。
输入：生成Agent的输出 + 知识库检索结果
输出：审核报告（通过 / 需修正 / 打回重做）
"""

import json
from config import REVIEW_SYSTEM_PROMPT
from .base_agent import BaseAgent
from loguru import logger


class ReviewAgent(BaseAgent):
    """
    对生成内容进行事实核查与难度匹配审核。
    核心职责：防控大模型幻觉。
    """

    def __init__(self):
        super().__init__(name="ReviewAgent", system_prompt=REVIEW_SYSTEM_PROMPT)

    def run(self, input_data: dict) -> dict:
        """
        Args:
            input_data: {
                "generated_content": {...},  # GenerationAgent的输出
                "retrieved_docs": [...],     # 用于交叉验证的知识库原文
                "diagnosis": {...},          # 用于校验难度匹配
            }

        Returns:
            dict: 审核结果，包含 verdict, errors, suggestion 等
        """
        generated = input_data.get("generated_content", {})
        docs = input_data.get("retrieved_docs", [])
        diagnosis = input_data.get("diagnosis", {})

        # 构建验证上下文
        verify_context = ""
        for i, doc in enumerate(docs):
            verify_context += f"\n【原文{i+1}】{doc.get('content', '')[:1200]}\n"

        prompt = f"""请审核以下生成内容：

【学员水平】{diagnosis.get('knowledge_level', '未知')}

【生成内容】
- 讲义：{generated.get('theory_lecture', '')[:2000]}
- 实操指南：{generated.get('practical_guide', '')[:1500]}
- 测试题：{json.dumps(generated.get('exercises', []), ensure_ascii=False)[:1000]}
- 生成自信度：{generated.get('confidence', '未知')}

【知识库原文供交叉验证】
{verify_context if verify_context else "（无知识库原文，只能做逻辑一致性检查）"}

请逐条审核并给出结果（仅输出JSON，不要其他文字）。
"""
        raw = self.call_llm(prompt, temperature=0.1)  # 审核用极低温度，力求准确
        result = self.parse_json_output(raw)
        verdict = result.get("verdict", "未知")
        error_count = result.get("error_count", 0)
        logger.info(
            f"[ReviewAgent] 审核完成: verdict={verdict}, errors={error_count}"
        )
        return result

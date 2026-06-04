"""
知识生成Agent。
输入：学情画像 + 知识库检索结果
输出：个性化学习资源（讲义、实操指南、测试题）
"""

import json
from config import GENERATION_SYSTEM_PROMPT
from .base_agent import BaseAgent
from loguru import logger


class GenerationAgent(BaseAgent):
    """
    基于学习者画像和知识库检索结果，生成定制化学习资源。
    """

    def __init__(self):
        super().__init__(name="GenerationAgent", system_prompt=GENERATION_SYSTEM_PROMPT)

    def run(self, input_data: dict) -> dict:
        """
        Args:
            input_data: {
                "diagnosis": {...},       # DiagnosisAgent的输出
                "retrieved_docs": [...],  # 知识库检索到的文档片段
            }

        Returns:
            dict: 包含 theory_lecture, practical_guide, exercises 等
        """
        diagnosis = input_data.get("diagnosis", {})
        docs = input_data.get("retrieved_docs", [])

        # 构建检索上下文
        knowledge_context = ""
        for i, doc in enumerate(docs):
            knowledge_context += f"\n【参考资料{i+1}】{doc.get('content', '')[:1500]}\n"

        prompt = f"""请根据以下信息，为学员生成个性化学习资源：

【学员画像】
- 知识水平：{diagnosis.get('knowledge_level', '未知')}
- 强项：{json.dumps(diagnosis.get('strengths', []), ensure_ascii=False)}
- 盲区：{json.dumps(diagnosis.get('weaknesses', []), ensure_ascii=False)}
- 推荐方向：{json.dumps(diagnosis.get('recommended_focus', []), ensure_ascii=False)}
- 学习风格：{diagnosis.get('learning_style_hint', '均衡')}

【知识库参考资料】
{knowledge_context if knowledge_context else "（暂无知识库检索结果，请基于你的通用知识生成，但需标注'参考资料不足'）"}

请生成学习资源（仅输出JSON，不要其他文字）。
"""
        raw = self.call_llm(prompt, temperature=0.4)
        result = self.parse_json_output(raw)
        logger.info(
            f"[GenerationAgent] 生成完成: "
            f"讲义{len(result.get('theory_lecture', ''))}字, "
            f"题目{len(result.get('exercises', []))}道, "
            f"置信度={result.get('confidence')}"
        )
        return result

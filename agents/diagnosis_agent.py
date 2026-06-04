"""
学情诊断Agent。
输入：学习者背景信息
输出：知识能力画像（强项、盲区、推荐方向）
"""

import json
from config import DIAGNOSIS_SYSTEM_PROMPT
from .base_agent import BaseAgent
from loguru import logger


class DiagnosisAgent(BaseAgent):
    """
    分析学习者的理论强项与技能盲区，为后续个性化生成提供依据。
    """

    def __init__(self):
        super().__init__(name="DiagnosisAgent", system_prompt=DIAGNOSIS_SYSTEM_PROMPT)

    def run(self, learner_data: dict) -> dict:
        """
        Args:
            learner_data: 包含学员基本信息，格式见 config.LEARNER_PROFILE_TEMPLATE

        Returns:
            dict: 诊断结果，包含 knowledge_level, strengths, weaknesses 等
        """
        prompt = f"""请分析以下学习者的学情：

学员背景：
- 学历：{learner_data.get('background', {}).get('education', '未知')}
- 专业：{learner_data.get('background', {}).get('major', '未知')}
- 经验年限：{learner_data.get('background', {}).get('years_of_experience', 0)}年

已掌握技能：{json.dumps(learner_data.get('self_assessment', {}).get('known_topics', []), ensure_ascii=False)}
想学习技能：{json.dumps(learner_data.get('self_assessment', {}).get('target_topics', []), ensure_ascii=False)}
学习目标：{learner_data.get('self_assessment', {}).get('learning_goal', '未提供')}

如有前置测试成绩：{json.dumps(learner_data.get('test_results', {}), ensure_ascii=False)}

请给出诊断结果（仅输出JSON，不要其他文字）。
"""
        raw = self.call_llm(prompt, temperature=0.2)  # 诊断用低温度保证一致性
        result = self.parse_json_output(raw)
        result["learner_name"] = learner_data.get("name", "未知学员")
        logger.info(f"[DiagnosisAgent] 诊断完成: level={result.get('knowledge_level')}")
        return result

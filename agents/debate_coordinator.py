"""
辩论协调Agent（核心创新点）。
当生成Agent和审核Agent出现分歧时，进行仲裁决策。
这是本系统的核心创新机制——不是简单串联，而是多Agent交叉验证。
"""

import json
from config import DEBATE_SYSTEM_PROMPT
from .base_agent import BaseAgent
from loguru import logger


class DebateCoordinator(BaseAgent):
    """
    多Agent辩论仲裁器。

    工作流：
    1. 检测生成Agent与审核Agent之间的分歧点
    2. 结合知识库原文进行三方比对
    3. 裁定最终输出
    """

    def __init__(self):
        super().__init__(name="DebateCoordinator", system_prompt=DEBATE_SYSTEM_PROMPT)

    def run(self, input_data: dict) -> dict:
        """
        Args:
            input_data: {
                "generated_content": {...},   # 生成Agent的输出
                "review_result": {...},       # 审核Agent的输出
                "retrieved_docs": [...],      # 知识库原文
                "max_rounds": 2,              # 最大辩论轮次
            }

        Returns:
            dict: 仲裁结果，包含 arbitration, final_content, hallucination_risk
        """
        generated = input_data.get("generated_content", {})
        review = input_data.get("review_result", {})
        docs = input_data.get("retrieved_docs", [])
        max_rounds = input_data.get("max_rounds", 2)

        verdict = review.get("verdict", "通过")
        errors = review.get("errors", [])

        # 如果审核通过，不需要辩论
        if verdict == "通过" and not errors:
            logger.info("[DebateCoordinator] 审核通过，无需辩论")
            return {
                "arbitration": "采纳生成",
                "reason": "审核Agent验证通过，无分歧",
                "final_content": None,
                "hallucination_risk": "低",
                "debate_rounds": 0,
            }

        # 有分歧，进行辩论仲裁
        logger.info(f"[DebateCoordinator] 检测到 {len(errors)} 处分歧，启动辩论仲裁")

        evidence = ""
        for i, doc in enumerate(docs):
            evidence += f"\n【证据{i+1}】{doc.get('content', '')[:1000]}\n"

        prompt = f"""请对以下分歧进行仲裁：

【生成Agent的输出】
讲义摘要：{generated.get('theory_lecture', '')[:1500]}
置信度：{generated.get('confidence', '未知')}

【审核Agent的质疑】
判定：{verdict}
错误数量：{len(errors)}
错误详情：{json.dumps(errors, ensure_ascii=False, indent=2)[:2000]}
建议：{review.get('suggestion', '无')}

【知识库原文（权威证据）】
{evidence if evidence else "（无知识库原文，需谨慎判定）"}

请给出仲裁结果（仅输出JSON，不要其他文字）。最大辩论轮次={max_rounds}。
"""
        raw = self.call_llm(prompt, temperature=0.1)
        result = self.parse_json_output(raw)
        result["debate_rounds"] = 1
        logger.info(
            f"[DebateCoordinator] 仲裁完成: "
            f"裁定={result.get('arbitration')}, "
            f"幻觉风险={result.get('hallucination_risk')}"
        )
        return result

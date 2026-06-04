"""
多Agent协同调度器（主控制器）。
负责串联整个"诊断 → RAG检索 → 生成 → 审核 → 辩论仲裁 → 最终输出"全流程。
"""

import json
from loguru import logger

from .diagnosis_agent import DiagnosisAgent
from .generation_agent import GenerationAgent
from .review_agent import ReviewAgent
from .debate_coordinator import DebateCoordinator


class AgentOrchestrator:
    """
    多Agent编排器。

    流程：
    1. 诊断Agent → 分析学情
    2. RAG检索（外部） → 获取相关知识
    3. 生成Agent → 生成学习资源
    4. 审核Agent → 验证内容准确性
    5. 辩论仲裁（如有分歧） → 交叉验证决策
    6. 输出最终结果

    使用方式：
        orchestrator = AgentOrchestrator(retriever=my_retriever)
        result = orchestrator.run(learner_data)
    """

    def __init__(self, retriever=None):
        """
        Args:
            retriever: RAG检索器对象，需提供 retrieve(query, top_k) 方法。
                      如果为None，Agent将在无知识库模式下运行（生成内容质量会下降）。
        """
        self.retriever = retriever
        self.diagnosis_agent = DiagnosisAgent()
        self.generation_agent = GenerationAgent()
        self.review_agent = ReviewAgent()
        self.debate_coordinator = DebateCoordinator()

    def _retrieve_knowledge(self, diagnosis: dict) -> list:
        """
        根据诊断结果检索知识库。
        """
        if self.retriever is None:
            logger.warning("[Orchestrator] 无知识库连接，跳过检索")
            return []

        # 用盲区和推荐方向构建检索查询
        queries = diagnosis.get("weaknesses", []) + diagnosis.get("recommended_focus", [])
        if not queries:
            queries = [diagnosis.get("knowledge_level", "基础知识")]

        all_docs = []
        for query in queries[:3]:  # 最多用3个查询
            docs = self.retriever.retrieve(query)
            all_docs.extend(docs)

        logger.info(f"[Orchestrator] RAG检索完成，共 {len(all_docs)} 条文档")
        return all_docs

    def run(self, learner_data: dict) -> dict:
        """
        执行完整的Agent协同流程。

        Args:
            learner_data: 学员数据，格式见 config.LEARNER_PROFILE_TEMPLATE

        Returns:
            dict: {
                "diagnosis": {...},
                "generated_content": {...},
                "review_result": {...},
                "debate_result": {...},
                "final_output": {...},    # 最终的学习资源
                "trace": [...]            # 全流程执行日志
            }
        """
        trace = []

        # -------------------- 阶段1：学情诊断 --------------------
        logger.info("=" * 50)
        logger.info("[Orchestrator] 阶段1: 学情诊断")
        diagnosis = self.diagnosis_agent.run(learner_data)
        trace.append({"stage": "diagnosis", "result": diagnosis})

        # -------------------- 阶段2：知识库检索 --------------------
        logger.info("[Orchestrator] 阶段2: 知识库检索")
        retrieved_docs = self._retrieve_knowledge(diagnosis)
        trace.append({"stage": "retrieval", "doc_count": len(retrieved_docs)})

        # -------------------- 阶段3：知识生成 --------------------
        logger.info("[Orchestrator] 阶段3: 知识生成")
        generation_input = {
            "diagnosis": diagnosis,
            "retrieved_docs": retrieved_docs,
        }
        generated = self.generation_agent.run(generation_input)
        trace.append({"stage": "generation", "result": generated})

        # -------------------- 阶段4：审核纠偏 --------------------
        logger.info("[Orchestrator] 阶段4: 内容审核")
        review_input = {
            "generated_content": generated,
            "retrieved_docs": retrieved_docs,
            "diagnosis": diagnosis,
        }
        review_result = self.review_agent.run(review_input)
        trace.append({"stage": "review", "result": review_result})

        # -------------------- 阶段5：辩论仲裁 --------------------
        debate_result = {"arbitration": "无需辩论", "hallucination_risk": "低", "debate_rounds": 0}
        if review_result.get("verdict") != "通过":
            logger.info("[Orchestrator] 阶段5: 辩论仲裁")
            debate_input = {
                "generated_content": generated,
                "review_result": review_result,
                "retrieved_docs": retrieved_docs,
                "max_rounds": 2,
            }
            debate_result = self.debate_coordinator.run(debate_input)
            trace.append({"stage": "debate", "result": debate_result})

            # 如果仲裁结果建议采用修正后内容，更新最终输出
            if debate_result.get("final_content"):
                final_content = debate_result["final_content"]
                logger.info("[Orchestrator] 采纳仲裁修正后的内容")
            else:
                final_content = generated
        else:
            final_content = generated

        # -------------------- 汇总最终输出 --------------------
        final_output = {
            "learner_name": learner_data.get("name", "未知"),
            "diagnosis": diagnosis,
            "learning_resources": final_content,
            "quality_report": {
                "review_verdict": review_result.get("verdict"),
                "error_count": review_result.get("error_count", 0),
                "hallucination_risk": debate_result.get("hallucination_risk", "低"),
                "debate_rounds": debate_result.get("debate_rounds", 0),
            },
        }

        logger.info("=" * 50)
        logger.info("[Orchestrator] 全流程完成！")
        logger.info(
            f"  - 诊断等级: {diagnosis.get('knowledge_level')}"
        )
        logger.info(
            f"  - 审核结论: {review_result.get('verdict')}, "
            f"错误数: {review_result.get('error_count', 0)}"
        )
        logger.info(f"  - 幻觉风险: {debate_result.get('hallucination_risk')}")

        return {
            "diagnosis": diagnosis,
            "generated_content": generated,
            "review_result": review_result,
            "debate_result": debate_result,
            "final_output": final_output,
            "trace": trace,
        }

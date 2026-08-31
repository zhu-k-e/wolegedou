"""术语映射表 - 方案书 v7.0 查询扩展+术语映射

预定义 AI/ML 领域中英术语对照表，覆盖知识库 10 个分类：
  llm_basics / fine_tuning / huggingface / vector_db / prompt_engineering
  project_practice / agent_framework / rag_architecture / langchain / code_debug

用于查询扩展（query_expander.py）：将用户 query 中的中文术语替换为英文（或反之），
生成多变体以提升跨语言检索召回率。

支持从 JSON 文件加载自定义映射（覆盖/合并默认映射）。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from loguru import logger


# ======================================================================
# 默认术语映射表（中 → 英）
# 覆盖知识库 10 个分类的常见术语
# ======================================================================
DEFAULT_TERM_MAPPING: dict[str, str] = {
    # --- LLM 基础 ---
    "大语言模型": "LLM",
    "大型语言模型": "LLM",
    "生成式预训练变换器": "GPT",
    "变换器": "Transformer",
    "自注意力": "Self-Attention",
    "注意力机制": "Attention Mechanism",
    "多头注意力": "Multi-Head Attention",
    "位置编码": "Positional Encoding",
    "分词器": "Tokenizer",
    "分词": "Tokenization",
    "词嵌入": "Word Embedding",
    "嵌入": "Embedding",
    "上下文窗口": "Context Window",
    "温度参数": "Temperature",
    "束搜索": "Beam Search",
    "核采样": "Top-p Sampling",
    "拓扑采样": "Top-k Sampling",

    # --- 模型微调 ---
    "微调": "Fine-tuning",
    "全量微调": "Full Fine-tuning",
    "低秩适配": "LoRA",
    "量化": "Quantization",
    "蒸馏": "Distillation",
    "知识蒸馏": "Knowledge Distillation",
    "参数高效微调": "PEFT",
    "适配器": "Adapter",
    "前缀微调": "Prefix Tuning",
    "提示微调": "Prompt Tuning",
    "梯度下降": "Gradient Descent",
    "随机梯度下降": "SGD",
    "反向传播": "Backpropagation",
    "学习率": "Learning Rate",
    "过拟合": "Overfitting",
    "欠拟合": "Underfitting",
    "损失函数": "Loss Function",
    "交叉熵": "Cross Entropy",
    "批次大小": "Batch Size",
    "轮次": "Epoch",
    "早停": "Early Stopping",
    "学习率预热": "Learning Rate Warmup",
    "余弦退火": "Cosine Annealing",
    "梯度累积": "Gradient Accumulation",
    "混合精度训练": "Mixed Precision Training",
    "分布式训练": "Distributed Training",

    # --- HuggingFace 调用 ---
    "预训练模型": "Pre-trained Model",
    "模型仓库": "Model Hub",
    "数据集仓库": "Dataset Hub",
    "推理": "Inference",
    "管道": "Pipeline",
    "配置类": "Config",
    "自回归": "Autoregressive",
    "自编码": "Autoencoding",
    "序列到序列": "Seq2Seq",
    "填充": "Padding",
    "截断": "Truncation",
    "注意力掩码": "Attention Mask",

    # --- 向量数据库 ---
    "向量数据库": "Vector Database",
    "向量存储": "Vector Store",
    "向量检索": "Vector Retrieval",
    "相似度搜索": "Similarity Search",
    "余弦相似度": "Cosine Similarity",
    "点积": "Dot Product",
    "欧氏距离": "Euclidean Distance",
    "近似最近邻": "ANN",
    "倒排索引": "Inverted Index",
    "标量量化": "Scalar Quantization",
    "乘积量化": "Product Quantization",

    # --- Prompt 工程 ---
    "提示工程": "Prompt Engineering",
    "提示词": "Prompt",
    "提示模板": "Prompt Template",
    "少样本": "Few-shot",
    "零样本": "Zero-shot",
    "单样本": "One-shot",
    "思维链": "Chain of Thought",
    "指令微调": "Instruction Tuning",
    "人类反馈强化学习": "RLHF",
    "对齐": "Alignment",

    # --- Agent 框架 ---
    "智能体": "Agent",
    "代理": "Agent",
    "多智能体": "Multi-Agent",
    "工具调用": "Tool Calling",
    "函数调用": "Function Calling",
    "规划": "Planning",
    "反思": "Reflection",
    "记忆": "Memory",
    "角色扮演": "Role Playing",
    "任务分解": "Task Decomposition",

    # --- RAG 架构 ---
    "检索增强生成": "RAG",
    "知识库": "Knowledge Base",
    "文档检索": "Document Retrieval",
    "语义搜索": "Semantic Search",
    "文本分割": "Text Splitting",
    "文档加载": "Document Loading",
    "重排序": "Reranking",
    "混合检索": "Hybrid Search",
    "稠密检索": "Dense Retrieval",
    "稀疏检索": "Sparse Retrieval",

    # --- LangChain 组件 ---
    "链": "Chain",
    "检索链": "Retrieval Chain",
    "对话记忆": "Conversation Memory",
    "缓冲记忆": "Buffer Memory",
    "摘要记忆": "Summary Memory",
    "输出解析器": "Output Parser",
    "检索器": "Retriever",
    "文档加载器": "Document Loader",
    "文本分割器": "Text Splitter",
    "向量存储器": "Vector Store",
    "嵌入模型": "Embedding Model",
    "语言模型": "Language Model",
    "聊天模型": "Chat Model",

    # --- 代码调试 ---
    "调试": "Debugging",
    "断点": "Breakpoint",
    "堆栈跟踪": "Stack Trace",
    "异常处理": "Exception Handling",
    "类型注解": "Type Annotation",
    "类型提示": "Type Hint",
    "内存泄漏": "Memory Leak",
    "竞态条件": "Race Condition",
    "死锁": "Deadlock",
    "单元测试": "Unit Test",
    "集成测试": "Integration Test",
    "模拟对象": "Mock Object",

    # --- 通用深度学习 ---
    "神经网络": "Neural Network",
    "深度学习": "Deep Learning",
    "机器学习": "Machine Learning",
    "卷积神经网络": "CNN",
    "循环神经网络": "RNN",
    "生成对抗网络": "GAN",
    "批归一化": "Batch Normalization",
    "丢弃": "Dropout",
    "激活函数": "Activation Function",
    "池化": "Pooling",
    "全连接层": "Fully Connected Layer",
    "前馈网络": "Feedforward Network",
    "残差连接": "Residual Connection",
    "梯度裁剪": "Gradient Clipping",
    "权重衰减": "Weight Decay",
}


class TermMapping:
    """术语映射表管理器

    用法：
        tm = TermMapping()                    # 使用默认映射
        tm = TermMapping("path/to/custom.json")  # 合并自定义映射
        tm.get_en("大语言模型")  → "LLM"
        tm.get_cn("LLM")        → "大语言模型"
        tm.all_pairs()           → dict
    """

    def __init__(self, custom_path: Optional[str | Path] = None):
        """初始化术语映射表

        Args:
            custom_path: 自定义映射 JSON 文件路径（中→英 dict），
                         加载后与默认映射合并（自定义优先）
        """
        # 正向映射：中 → 英
        self._cn_to_en: dict[str, str] = dict(DEFAULT_TERM_MAPPING)

        # 合并自定义映射
        if custom_path:
            custom_path = Path(custom_path)
            if custom_path.exists():
                try:
                    custom = json.loads(custom_path.read_text(encoding="utf-8"))
                    if isinstance(custom, dict):
                        self._cn_to_en.update(custom)
                        logger.info(
                            f"[TermMapping] 加载自定义映射: {len(custom)} 条, "
                            f"总计 {len(self._cn_to_en)} 条"
                        )
                except Exception as e:
                    logger.warning(f"[TermMapping] 加载自定义映射失败: {e}")

        # 反向映射：英(小写) → 中（取第一个匹配，避免多对一冲突）
        self._en_to_cn: dict[str, str] = {}
        for cn, en in self._cn_to_en.items():
            key = en.lower()
            if key not in self._en_to_cn:
                self._en_to_cn[key] = cn

        logger.debug(
            f"[TermMapping] 初始化: {len(self._cn_to_en)} 条映射 "
            f"({len(self._en_to_cn)} 条反向)"
        )

    @property
    def size(self) -> int:
        """映射表条目数"""
        return len(self._cn_to_en)

    def get_en(self, cn_term: str) -> Optional[str]:
        """中文术语 → 英文"""
        return self._cn_to_en.get(cn_term)

    def get_cn(self, en_term: str) -> Optional[str]:
        """英文术语 → 中文"""
        return self._en_to_cn.get(en_term.lower())

    def all_pairs(self) -> dict[str, str]:
        """返回全部中→英映射"""
        return dict(self._cn_to_en)

    def find_in_query(self, query: str) -> list[tuple[str, str, str]]:
        """在 query 中查找术语映射命中

        Args:
            query: 查询文本

        Returns:
            命中列表: [(方向, 原文, 替换), ...]
            方向: "cn→en" 或 "en→cn"
        """
        hits: list[tuple[str, str, str]] = []
        seen_replacements: set[str] = set()

        # 中文 → 英文（先收集，再过滤子串冲突）
        cn_hits: list[tuple[str, str]] = []  # [(cn, en), ...]
        for cn, en in self._cn_to_en.items():
            if cn in query and en.lower() not in query.lower():
                key = f"cn→en:{cn}"
                if key not in seen_replacements:
                    cn_hits.append((cn, en))
                    seen_replacements.add(key)

        # 过滤子串冲突：如果短术语是已匹配长术语的子串，跳过
        # 例："语言模型" 是 "大语言模型" 的子串 → 跳过 "语言模型"
        filtered_cn: list[tuple[str, str]] = []
        for i, (cn_short, en_short) in enumerate(cn_hits):
            is_substring = False
            for j, (cn_long, en_long) in enumerate(cn_hits):
                if i != j and cn_short != cn_long and cn_short in cn_long:
                    # 短术语是长术语的子串，且长术语也在 query 中
                    is_substring = True
                    break
            if not is_substring:
                filtered_cn.append((cn_short, en_short))

        for cn, en in filtered_cn:
            hits.append(("cn→en", cn, en))

        # 英文 → 中文（注意大小写不敏感匹配，但替换时保持原文）
        query_lower = query.lower()
        for en_lower, cn in self._en_to_cn.items():
            # 用词边界匹配英文术语（避免部分匹配，如 "RAG" in "RAGged"）
            if self._contains_term(query_lower, en_lower) and cn not in query:
                key = f"en→cn:{en_lower}"
                if key not in seen_replacements:
                    hits.append(("en→cn", en_lower, cn))
                    seen_replacements.add(key)

        return hits

    @staticmethod
    def _contains_term(text: str, term: str) -> bool:
        """检查 term 是否作为独立词出现在 text 中（词边界匹配）"""
        if not term:
            return False
        # 简单词边界：前后是非字母字符或字符串边界
        idx = text.find(term)
        while idx >= 0:
            before = text[idx - 1] if idx > 0 else " "
            after = text[idx + len(term)] if idx + len(term) < len(text) else " "
            if not (before.isalnum() or before == "_") and not (after.isalnum() or after == "_"):
                return True
            idx = text.find(term, idx + 1)
        return False

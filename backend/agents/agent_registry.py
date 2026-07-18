"""Agent卡片注册表 - 11个Agent的静态信息定义

对应方案书 3.2 节 Agent池构成
10个领域Agent + 1个资源生成Agent
"""

# 10个领域Agent + 1个资源生成Agent
AGENT_CARDS = [
    {
        "agent_id": "agent_001",
        "agent_name": "LLM基础Agent",
        "primary_function": "LLM原理与概念",
        "secondary_functions": ["Token机制", "Embedding", "注意力机制"],
        "domain_tags": ["LLM基础", "Prompt工程"],
    },
    {
        "agent_id": "agent_002",
        "agent_name": "Prompt工程Agent",
        "primary_function": "Prompt设计与优化",
        "secondary_functions": ["Few-shot", "CoT", "模板设计"],
        "domain_tags": ["Prompt工程", "LangChain"],
    },
    {
        "agent_id": "agent_003",
        "agent_name": "LangChain组件Agent",
        "primary_function": "LangChain组件开发",
        "secondary_functions": ["Chain", "Tool", "Memory", "Callback"],
        "domain_tags": ["LangChain", "RAG"],
    },
    {
        "agent_id": "agent_004",
        "agent_name": "RAG架构Agent",
        "primary_function": "RAG系统搭建",
        "secondary_functions": ["文档切分", "向量检索", "检索增强生成"],
        "domain_tags": ["RAG", "向量数据库"],
    },
    {
        "agent_id": "agent_005",
        "agent_name": "Agent框架Agent",
        "primary_function": "LLM Agent开发",
        "secondary_functions": ["ReAct", "Function Calling", "多工具协作"],
        "domain_tags": ["Agent框架", "LangChain"],
    },
    {
        "agent_id": "agent_006",
        "agent_name": "HuggingFace调用Agent",
        "primary_function": "HF模型使用",
        "secondary_functions": ["模型加载", "Pipeline", "推理部署"],
        "domain_tags": ["HuggingFace", "模型微调"],
    },
    {
        "agent_id": "agent_007",
        "agent_name": "模型微调Agent",
        "primary_function": "模型微调训练",
        "secondary_functions": ["LoRA", "QLoRA", "数据集准备"],
        "domain_tags": ["模型微调", "HuggingFace"],
    },
    {
        "agent_id": "agent_008",
        "agent_name": "向量数据库Agent",
        "primary_function": "向量存储与检索",
        "secondary_functions": ["Chroma", "FAISS", "索引优化"],
        "domain_tags": ["向量数据库", "RAG"],
    },
    {
        "agent_id": "agent_009",
        "agent_name": "项目实战Agent",
        "primary_function": "项目架构与落地",
        "secondary_functions": ["需求分析", "技术选型", "部署上线"],
        "domain_tags": ["Agent框架", "项目部署"],
    },
    {
        "agent_id": "agent_010",
        "agent_name": "代码调试Agent",
        "primary_function": "代码排错与修复",
        "secondary_functions": ["报错分析", "依赖冲突", "环境配置"],
        "domain_tags": ["LangChain", "HuggingFace", "Prompt工程"],
    },
    # 第11个：资源生成Agent（不参与领域内容生成，只在裁判团通过后做格式转换）
    {
        "agent_id": "agent_011",
        "agent_name": "资源生成Agent",
        "primary_function": "多形态资源生成",
        "secondary_functions": ["讲义生成", "实操指南", "分阶测试题"],
        "domain_tags": [],
    },
]


def get_agent_card(agent_id: str) -> dict | None:
    """根据agent_id获取卡片信息"""
    for card in AGENT_CARDS:
        if card["agent_id"] == agent_id:
            return card
    return None


def get_domain_agents() -> list[dict]:
    """获取10个领域Agent（不含资源生成Agent）"""
    return [c for c in AGENT_CARDS if c["agent_id"] != "agent_011"]


def get_resource_agent() -> dict:
    """获取资源生成Agent"""
    return get_agent_card("agent_011")

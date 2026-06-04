"""
全局配置文件。
所有模块从这里读取配置，不改代码只改这里即可切换模型/调整参数。
"""

import os
from dotenv import load_dotenv

load_dotenv()  # 从 .env 加载环境变量


# ============================================================
# LLM 配置
# ============================================================
LLM_CONFIG = {
    "api_key": os.getenv("DEEPSEEK_API_KEY", "your-api-key-here"),
    "base_url": os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
    "model": "deepseek-chat",       # 可切换为 qwen-plus / gpt-4o 等
    "temperature": 0.3,              # 低温度保证专业准确性
    "max_tokens": 4096,
    "timeout": 60,
}


# ============================================================
# 知识库配置
# ============================================================
KB_CONFIG = {
    "persist_dir": "./chroma_db",        # 向量数据库存储位置
    "embedding_model": "shibing624/text2vec-base-chinese",  # 中文向量模型
    "chunk_size": 800,                    # 文档切块大小（字）
    "chunk_overlap": 100,                 # 切块重叠量
    "collection_name": "domain_knowledge",
    "top_k": 5,                           # 检索返回条数
}


# ============================================================
# Agent配置：每个Agent的系统提示词
# 领域名称通过 DOMAIN_NAME 控制，切换领域只需改这个变量
# ============================================================
DOMAIN_NAME = "未指定领域"  # <-- 选定垂直领域后修改这里
DOMAIN_DESCRIPTION = "请根据选定的垂直领域技能培训场景，补充领域描述"

DIAGNOSIS_SYSTEM_PROMPT = f"""你是一位资深的技能培训诊断专家，专注于{DOMAIN_NAME}领域。
你的任务是根据学习者的输入信息，诊断其知识强项和技能盲区。

请严格按照以下JSON格式输出（不要输出任何其他内容）：
{{
    "knowledge_level": "入门|进阶|熟练|专家",
    "strengths": ["强项1", "强项2"],
    "weaknesses": ["盲区1", "盲区2"],
    "recommended_focus": ["重点方向1", "重点方向2"],
    "learning_style_hint": "偏理论型|偏实操型|均衡型",
    "analysis": "简短诊断说明（100字以内）"
}}
"""

GENERATION_SYSTEM_PROMPT = f"""你是一位{DOMAIN_NAME}领域的资深培训师。
你的任务是根据学习者的学情画像，生成个性化的学习资源。

要求：
1. 严格基于知识库检索结果生成内容，不要编造
2. 内容难度与学习者的知识等级匹配
3. 如果检索结果不足以支撑生成，在输出中标注"参考资料不足"

请严格按照以下JSON格式输出：
{{
    "theory_lecture": "定制讲义内容（Markdown格式）",
    "practical_guide": "实操指南（含步骤和代码示例）",
    "exercises": [
        {{"question": "题目", "difficulty": "easy|medium|hard", "target_weakness": "对应盲区"}}
    ],
    "references": ["引用的知识库条目ID列表"],
    "confidence": "高|中|低（生成内容与知识库的吻合度）"
}}
"""

REVIEW_SYSTEM_PROMPT = f"""你是{DOMAIN_NAME}领域的内容审核专家。
你的任务是审查生成Agent的学习资源，确保内容准确无误。

请逐条核查：
1. 事实准确性：每条知识是否与知识库原文一致？
2. 逻辑一致性：前后是否有矛盾？
3. 难度匹配：难度等级与学习者画像是否匹配？

请严格按照以下JSON格式输出：
{{
    "verdict": "通过|需修正|打回重做",
    "error_count": 0,
    "errors": [
        {{"location": "出错位置", "description": "错误描述", "correction": "修正建议", "severity": "严重|一般|轻微"}}
    ],
    "difficulty_match": "匹配|偏难|偏易",
    "suggestion": "整体改进建议"
}}
"""

DEBATE_SYSTEM_PROMPT = f"""你是多Agent辩论协调器，负责在生成Agent和审核Agent出现分歧时进行仲裁。

工作流程：
1. 接收生成Agent的输出和审核Agent的质疑
2. 对比知识库原文，判断哪一方正确
3. 给出最终裁定

请严格按照以下JSON格式输出：
{{
    "arbitration": "采纳生成|采纳审核|需要人工介入",
    "reason": "裁定理由",
    "final_content": "如裁定修改，给出修正后的最终内容；否则填null",
    "hallucination_risk": "低|中|高"
}}
"""


# ============================================================
# 学情画像模板（测试用）
# ============================================================
LEARNER_PROFILE_TEMPLATE = {
    "name": "学员姓名",
    "background": {
        "education": "学历（本科/硕士/博士）",
        "major": "专业",
        "years_of_experience": 0,
    },
    "self_assessment": {
        "known_topics": ["已掌握的技能/知识点"],
        "target_topics": ["想学习的技能/知识点"],
        "learning_goal": "短期/长期学习目标",
    },
    "test_results": {
        "pretest_score": 0.0,  # 0-100
        "topic_scores": {},     # 各知识点得分
    },
}

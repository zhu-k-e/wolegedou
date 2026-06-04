"""
测试数据生成器。
生成模拟学习者画像，用于测试 Agent 链路。
"""

import json
import random
from config import LEARNER_PROFILE_TEMPLATE


def generate_test_learners() -> list:
    """
    生成 3 组差异化学习者数据。
    用于：
    - 验证系统对不同水平学习者的适配能力
    - 评分标准要求的「≥ 2 组差异化学习者数据源」
    """
    return [
        {
            "name": "学员A（入门级）",
            "background": {"education": "本科", "major": "计算机科学", "years_of_experience": 0},
            "self_assessment": {
                "known_topics": ["Python基础", "数据结构"],
                "target_topics": ["机器学习", "深度学习"],
                "learning_goal": "掌握AI工程实践能力",
            },
            "test_results": {"pretest_score": 45.0, "topic_scores": {}},
        },
        {
            "name": "学员B（进阶级）",
            "background": {"education": "硕士", "major": "人工智能", "years_of_experience": 2},
            "self_assessment": {
                "known_topics": ["机器学习基础", "PyTorch", "NumPy"],
                "target_topics": ["Transformer", "大模型微调", "多模态"],
                "learning_goal": "掌握大模型实战技能",
            },
            "test_results": {"pretest_score": 72.0, "topic_scores": {}},
        },
        {
            "name": "学员C（熟练级）",
            "background": {"education": "博士", "major": "计算机视觉", "years_of_experience": 4},
            "self_assessment": {
                "known_topics": ["CV基础", "YOLO", "Transformer"],
                "target_topics": ["多Agent系统", "大模型幻觉防控", "知识图谱"],
                "learning_goal": "掌握前沿AI系统架构设计能力",
            },
            "test_results": {"pretest_score": 88.0, "topic_scores": {}},
        },
    ]


def save_test_data(path: str = "tests/test_data/learners.json"):
    """将测试数据保存为 JSON 文件。"""
    import os

    os.makedirs(os.path.dirname(path), exist_ok=True)
    data = generate_test_learners()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return path

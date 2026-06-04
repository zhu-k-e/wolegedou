"""
快速入口。
生成 3 组差异化 learner 数据到 tests/test_data/learners.json。
用法：python -m utils.quick_test
"""

import os
import sys

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from utils.test_data import generate_test_learners, save_test_data


def main():
    path = os.path.join(project_root, "tests", "test_data", "learners.json")
    print("生成测试数据...", save_test_data(path))
    data = generate_test_learners()
    print(f"✅ 完成！共 {len(data)} 组学习者数据：")
    for d in data:
        print(f"  - {d['name']}（前置成绩 {d['test_results']['pretest_score']}）")


if __name__ == "__main__":
    main()

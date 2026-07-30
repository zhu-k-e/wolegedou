"""P0-2 测试用例验证：100 道测试用例的格式与分布校验

对应方案书 7.2.2 节 + 7.2.3 节验证指标。
校验 tests/test_cases_100.json：
  - 总数 100 道
  - 类别分布：概念理解30 / 操作步骤30 / 调试排错20 / 架构设计15 / 全链路规划5
  - 复杂度分布：simple ~40% / medium ~45% / complex ~15%
  - 领域覆盖：10 个领域全覆盖
  - 每道用例字段完整（id/category/question/expected_domains/expected_complexity/
    expected_question_type/reference_answer_points/suitable_profile）
  - ID 唯一连续
  - 学情画像字段完整
"""

import json
from pathlib import Path
from collections import Counter

import pytest

TEST_CASES_PATH = Path(__file__).resolve().parent.parent.parent / "tests" / "test_cases_100.json"

# 合法领域（DOMAIN_HINT_ENUMS + 代码调试Agent）
VALID_DOMAINS = {
    "LLM基础", "Prompt工程", "LangChain", "RAG", "HuggingFace",
    "模型微调", "向量数据库", "Agent框架", "项目部署", "代码调试",
}

VALID_CATEGORIES = {"概念理解", "操作步骤", "调试排错", "架构设计", "全链路规划"}
VALID_COMPLEXITIES = {"simple", "medium", "complex"}
VALID_QUESTION_TYPES = {"concept", "operation", "debug", "architecture", "full_pipeline"}
VALID_KNOWLEDGE_LEVELS = {"beginner", "intermediate", "advanced"}


@pytest.fixture(scope="module")
def test_cases_data():
    """加载测试用例数据"""
    with open(TEST_CASES_PATH, encoding="utf-8") as f:
        return json.load(f)


# ============================================================
# 1. 总数与分布
# ============================================================

class TestTestCaseDistribution:
    """测试用例分布校验（方案书 7.2.2 节）"""

    def test_total_count_100(self, test_cases_data):
        """总数 100 道"""
        assert test_cases_data["total"] == 100
        assert len(test_cases_data["test_cases"]) == 100

    def test_category_distribution(self, test_cases_data):
        """类别分布：30/30/20/15/5"""
        cats = Counter(tc["category"] for tc in test_cases_data["test_cases"])
        assert cats["概念理解"] == 30
        assert cats["操作步骤"] == 30
        assert cats["调试排错"] == 20
        assert cats["架构设计"] == 15
        assert cats["全链路规划"] == 5

    def test_complexity_distribution(self, test_cases_data):
        """复杂度分布：simple ~40% / medium ~45% / complex ~15%"""
        comps = Counter(tc["expected_complexity"] for tc in test_cases_data["test_cases"])
        # 允许 ±5 浮动
        assert 35 <= comps["simple"] <= 45
        assert 40 <= comps["medium"] <= 50
        assert 10 <= comps["complex"] <= 20

    def test_all_domains_covered(self, test_cases_data):
        """10 个领域全覆盖"""
        doms = set()
        for tc in test_cases_data["test_cases"]:
            doms.update(tc["expected_domains"])
        for d in VALID_DOMAINS:
            assert d in doms, f"领域未覆盖: {d}"

    def test_distribution_metadata_correct(self, test_cases_data):
        """distribution 元数据与实际一致"""
        dist = test_cases_data["distribution"]
        cats = Counter(tc["category"] for tc in test_cases_data["test_cases"])
        assert dist["concept"] == cats["概念理解"]
        assert dist["operation"] == cats["操作步骤"]
        assert dist["debug"] == cats["调试排错"]
        assert dist["architecture"] == cats["架构设计"]
        assert dist["full_pipeline"] == cats["全链路规划"]


# ============================================================
# 2. 单条用例字段完整性
# ============================================================

class TestTestCaseFields:
    """每道用例字段完整性"""

    REQUIRED_FIELDS = {
        "id", "category", "question", "expected_domains",
        "expected_complexity", "expected_question_type",
        "reference_answer_points", "suitable_profile",
    }

    def test_all_cases_have_required_fields(self, test_cases_data):
        """每道用例包含 8 个必填字段"""
        for tc in test_cases_data["test_cases"]:
            missing = self.REQUIRED_FIELDS - set(tc.keys())
            assert not missing, f"{tc.get('id')} 缺字段: {missing}"

    def test_id_unique(self, test_cases_data):
        """ID 唯一"""
        ids = [tc["id"] for tc in test_cases_data["test_cases"]]
        assert len(ids) == len(set(ids)), "ID 有重复"

    def test_id_format(self, test_cases_data):
        """ID 格式 TC-XXX"""
        for tc in test_cases_data["test_cases"]:
            assert tc["id"].startswith("TC-"), f"ID 格式错误: {tc['id']}"

    def test_id_continuous(self, test_cases_data):
        """ID 连续 TC-001 ~ TC-100"""
        ids = sorted(tc["id"] for tc in test_cases_data["test_cases"])
        expected = [f"TC-{i:03d}" for i in range(1, 101)]
        assert ids == expected

    def test_question_nonempty(self, test_cases_data):
        """问题文本非空"""
        for tc in test_cases_data["test_cases"]:
            assert tc["question"].strip(), f"{tc['id']} 问题为空"
            assert len(tc["question"]) >= 5, f"{tc['id']} 问题过短"

    def test_expected_domains_nonempty(self, test_cases_data):
        """预期领域标签非空"""
        for tc in test_cases_data["test_cases"]:
            assert len(tc["expected_domains"]) >= 1, f"{tc['id']} 无预期领域"

    def test_expected_domains_valid(self, test_cases_data):
        """预期领域标签合法"""
        for tc in test_cases_data["test_cases"]:
            for d in tc["expected_domains"]:
                assert d in VALID_DOMAINS, f"{tc['id']} 非法领域: {d}"

    def test_category_valid(self, test_cases_data):
        """类别合法"""
        for tc in test_cases_data["test_cases"]:
            assert tc["category"] in VALID_CATEGORIES, f"{tc['id']} 非法类别: {tc['category']}"

    def test_complexity_valid(self, test_cases_data):
        """复杂度合法"""
        for tc in test_cases_data["test_cases"]:
            assert tc["expected_complexity"] in VALID_COMPLEXITIES, (
                f"{tc['id']} 非法复杂度: {tc['expected_complexity']}"
            )

    def test_question_type_valid(self, test_cases_data):
        """题型合法"""
        for tc in test_cases_data["test_cases"]:
            assert tc["expected_question_type"] in VALID_QUESTION_TYPES, (
                f"{tc['id']} 非法题型: {tc['expected_question_type']}"
            )

    def test_question_type_matches_category(self, test_cases_data):
        """题型与类别对应"""
        type_map = {
            "概念理解": "concept", "操作步骤": "operation", "调试排错": "debug",
            "架构设计": "architecture", "全链路规划": "full_pipeline",
        }
        for tc in test_cases_data["test_cases"]:
            expected_type = type_map[tc["category"]]
            assert tc["expected_question_type"] == expected_type, (
                f"{tc['id']} 题型与类别不匹配: {tc['category']} → {tc['expected_question_type']}"
            )

    def test_reference_answer_points_nonempty(self, test_cases_data):
        """参考答案要点非空（至少 3 个）"""
        for tc in test_cases_data["test_cases"]:
            assert len(tc["reference_answer_points"]) >= 3, (
                f"{tc['id']} 参考答案要点不足 3 个"
            )


# ============================================================
# 3. 学情画像字段
# ============================================================

class TestSuitableProfile:
    """适配学情画像字段校验"""

    PROFILE_FIELDS = {"knowledge_level", "background", "current_goal"}

    def test_profile_has_required_fields(self, test_cases_data):
        """学情画像包含 3 个字段"""
        for tc in test_cases_data["test_cases"]:
            profile = tc["suitable_profile"]
            missing = self.PROFILE_FIELDS - set(profile.keys())
            assert not missing, f"{tc['id']} 学情画像缺字段: {missing}"

    def test_knowledge_level_valid(self, test_cases_data):
        """knowledge_level 合法"""
        for tc in test_cases_data["test_cases"]:
            kl = tc["suitable_profile"]["knowledge_level"]
            assert kl in VALID_KNOWLEDGE_LEVELS, f"{tc['id']} 非法 knowledge_level: {kl}"

    def test_knowledge_level_aligned_with_complexity(self, test_cases_data):
        """knowledge_level 与 complexity 联动（simple→beginner / medium→intermediate / complex→advanced）"""
        alignment = {"simple": "beginner", "medium": "intermediate", "complex": "advanced"}
        mismatches = []
        for tc in test_cases_data["test_cases"]:
            expected_kl = alignment[tc["expected_complexity"]]
            actual_kl = tc["suitable_profile"]["knowledge_level"]
            if actual_kl != expected_kl:
                mismatches.append((tc["id"], tc["expected_complexity"], actual_kl))
        # 允许少量偏差（≤10%），统计报告
        assert len(mismatches) <= 10, f"knowledge_level 与 complexity 联动偏差过多: {len(mismatches)}"


# ============================================================
# 4. 方案书 7.2.3 节验证指标可达性
# ============================================================

class TestVerificationIndicators:
    """方案书 7.2.3 节验证指标可达性"""

    def test_concept_cases_for_error_rate(self, test_cases_data):
        """谬误率验证（≤3%）需要概念理解类用例"""
        concept_count = sum(
            1 for tc in test_cases_data["test_cases"] if tc["category"] == "概念理解"
        )
        assert concept_count >= 30, "概念理解类用例不足，无法做谬误率验证"

    def test_all_question_types_for_coverage(self, test_cases_data):
        """知识点覆盖率（≥95%）需要所有题型"""
        types = set(tc["expected_question_type"] for tc in test_cases_data["test_cases"])
        assert types == VALID_QUESTION_TYPES

    def test_cross_domain_cases_exist(self, test_cases_data):
        """跨领域用例存在（适配准确率验证需要）"""
        cross = [tc for tc in test_cases_data["test_cases"] if len(tc["expected_domains"]) >= 2]
        assert len(cross) >= 10, f"跨领域用例不足: {len(cross)}"

    def test_full_pipeline_cases_exist(self, test_cases_data):
        """全链路规划用例存在（端到端验证需要）"""
        full = [tc for tc in test_cases_data["test_cases"] if tc["category"] == "全链路规划"]
        assert len(full) == 5

    def test_complex_cases_for_adaptability(self, test_cases_data):
        """complex 用例存在（适配准确率验证需要）"""
        complex_cases = [tc for tc in test_cases_data["test_cases"] if tc["expected_complexity"] == "complex"]
        assert len(complex_cases) >= 10

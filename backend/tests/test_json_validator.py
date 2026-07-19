"""JSON三层兜底校验器测试

对应方案书 3.5.2 节 JSON输出质量控制
"""

import asyncio

import pytest
from pydantic import BaseModel, Field

from backend.services.json_validator import JSONValidator


class SimpleModel(BaseModel):
    """简单测试模型"""
    name: str
    score: float = Field(ge=0.0, le=1.0)
    tags: list[str] = Field(default_factory=list)


class TestJSONValidator:
    """三层兜底校验测试"""

    def setup_method(self):
        self.validator = JSONValidator(llm_client=None)

    # ============================================================
    # 第一层：直接解析
    # ============================================================

    def test_layer1_valid_json(self):
        """第一层：合法JSON直接通过"""
        raw = '{"name": "test", "score": 0.85, "tags": ["a", "b"]}'
        result = asyncio.run(self.validator.validate(raw, SimpleModel))
        assert result is not None
        assert result.name == "test"
        assert result.score == 0.85

    def test_layer1_invalid_json(self):
        """第一层：非法JSON失败"""
        raw = '这不是JSON'
        result = self.validator._layer1_direct_parse(raw, SimpleModel)
        assert result is None

    # ============================================================
    # 第二层：正则修复
    # ============================================================

    def test_layer2_extract_from_markdown(self):
        """第二层：从markdown代码块中提取JSON"""
        raw = '```json\n{"name": "test", "score": 0.5, "tags": []}\n```'
        result = self.validator._layer2_regex_repair(raw, SimpleModel)
        assert result is not None
        assert result.name == "test"

    def test_layer2_extract_nested_json(self):
        """第二层：从包含其他文本的内容中提取JSON"""
        raw = '以下是结果：\n{"name": "test", "score": 0.7, "tags": ["x"]}\n以上。'
        result = self.validator._layer2_regex_repair(raw, SimpleModel)
        assert result is not None
        assert result.name == "test"

    def test_layer2_repair_number_in_string(self):
        """第二层：number字段收到string时修复"""
        raw = '{"name": "test", "score": "0.85", "tags": []}'
        result = self.validator._layer2_regex_repair(raw, SimpleModel)
        assert result is not None
        assert result.score == 0.85

    # ============================================================
    # 综合测试
    # ============================================================

    def test_full_pipeline_valid(self):
        """完整流程：合法JSON通过第一层"""
        raw = '{"name": "agent_001", "score": 0.9, "tags": ["LLM基础"]}'
        result = asyncio.run(self.validator.validate(raw, SimpleModel))
        assert result is not None
        assert result.name == "agent_001"

    def test_full_pipeline_with_markdown(self):
        """完整流程：带markdown标记的JSON通过第二层"""
        raw = '```json\n{"name": "agent_002", "score": 0.6, "tags": []}\n```'
        result = asyncio.run(self.validator.validate(raw, SimpleModel))
        assert result is not None
        assert result.name == "agent_002"

    def test_full_pipeline_failure(self):
        """完整流程：无法修复的内容返回None"""
        raw = '完全不是JSON的内容，没有任何花括号'
        result = asyncio.run(self.validator.validate(raw, SimpleModel))
        assert result is None

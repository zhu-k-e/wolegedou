"""GAP-7/8/9/10 验证测试"""
import inspect
import json
import asyncio
import pytest


class TestGap7JsonLayer:
    """GAP-7: 三层校验统一 — 所有Agent方法改用parse_json_safe"""

    def test_parse_json_safe_exists(self):
        from backend.services.json_validator import JSONValidator
        from backend.agents.base_agent import BaseAgent
        assert hasattr(JSONValidator, 'parse_json_safe')
        assert hasattr(BaseAgent, 'parse_json_safe')

    def test_domain_agent_no_json_loads(self):
        from backend.agents.domain_agent import DomainAgent
        for method_name in ['debate_challenge', 'debate_defense']:
            source = inspect.getsource(getattr(DomainAgent, method_name))
            assert 'json.loads' not in source, f'{method_name} still uses json.loads'
            assert 'parse_json_safe' in source, f'{method_name} should use parse_json_safe'

    def test_judge_panel_no_json_loads(self):
        from backend.agents.judge_panel import JudgePanel
        for method_name in ['_judge_single', '_majority_response', '_chief_judge_arbitrate', 'recheck']:
            source = inspect.getsource(getattr(JudgePanel, method_name))
            assert 'json.loads' not in source, f'{method_name} still uses json.loads'
            assert 'parse_json_safe' in source, f'{method_name} should use parse_json_safe'

    def test_profile_agent_no_json_loads(self):
        from backend.agents.profile_agent import ProfileAgent
        source = inspect.getsource(ProfileAgent.generate_heuristic_followup)
        assert 'json.loads' not in source
        assert 'parse_json_safe' in source

    def test_resource_agent_no_json_loads(self):
        from backend.agents.resource_agent import ResourceAgent
        source = inspect.getsource(ResourceAgent.generate_advance_challenge)
        assert 'json.loads' not in source
        assert 'parse_json_safe' in source

    def test_review_team_no_json_loads(self):
        from backend.agents.review_team import ReviewTeam, Verifier, Skeptic, Evaluator
        for cls_name, cls in [('Verifier', Verifier), ('Skeptic', Skeptic), ('Evaluator', Evaluator)]:
            source = inspect.getsource(cls.review)
            assert 'json.loads' not in source, f'{cls_name}.review still uses json.loads'
            assert 'parse_json_safe' in source, f'{cls_name}.review should use parse_json_safe'
        source = inspect.getsource(ReviewTeam.check_cross_segment_consistency)
        assert 'json.loads' not in source
        assert 'parse_json_safe' in source

    def test_parse_json_safe_logic(self):
        from backend.services.json_validator import JSONValidator
        validator = JSONValidator()

        result = asyncio.run(validator.parse_json_safe('{"key": "value"}'))
        assert result == {"key": "value"}

        result = asyncio.run(validator.parse_json_safe('```json\n{"key": "value"}\n```'))
        assert result == {"key": "value"}

        result = asyncio.run(validator.parse_json_safe('Here is the result:\n{"evidence": ["item1"]}\nDone.'))
        assert result == {"evidence": ["item1"]}


class TestGap8JudgeFastTrack:
    """GAP-8: 裁判团快速通道"""

    def test_review_unanimous(self):
        from backend.agents.judge_panel import JudgePanel
        from backend.schemas.review_feedback import ReviewFeedback, CandidateReview, ReviewerScores
        jp = JudgePanel()
        rf = ReviewFeedback(seg_id='seg_1', candidates=[
            CandidateReview(agent_id='a1', scores=ReviewerScores(
                fact_accuracy=0.90, logic_completeness=0.92, pedagogical_fit=0.88
            ), issues_found=[], is_winner=True),
        ])
        assert jp._check_review_unanimous(rf) is True

    def test_review_non_unanimous(self):
        from backend.agents.judge_panel import JudgePanel
        from backend.schemas.review_feedback import ReviewFeedback, CandidateReview, ReviewerScores
        jp = JudgePanel()
        rf = ReviewFeedback(seg_id='seg_1', candidates=[
            CandidateReview(agent_id='a1', scores=ReviewerScores(
                fact_accuracy=0.90, logic_completeness=0.70, pedagogical_fit=0.85
            ), issues_found=[], is_winner=True),
        ])
        assert jp._check_review_unanimous(rf) is False

    def test_review_unanimous_none(self):
        from backend.agents.judge_panel import JudgePanel
        jp = JudgePanel()
        assert jp._check_review_unanimous(None) is False

    def test_review_unanimous_boundary(self):
        from backend.agents.judge_panel import JudgePanel
        from backend.schemas.review_feedback import ReviewFeedback, CandidateReview, ReviewerScores
        jp = JudgePanel()
        rf = ReviewFeedback(seg_id='seg_1', candidates=[
            CandidateReview(agent_id='a1', scores=ReviewerScores(
                fact_accuracy=0.90, logic_completeness=0.95, pedagogical_fit=0.88
            ), issues_found=[], is_winner=True),
        ])
        assert jp._check_review_unanimous(rf) is False

    def test_judge_signature(self):
        from backend.agents.judge_panel import JudgePanel
        sig = inspect.signature(JudgePanel.judge)
        assert 'review_feedback' in sig.parameters


class TestGap9ProfileCache:
    """GAP-9: 学情画像缓存"""

    def test_profile_from_dict_exists(self):
        from backend.agents.profile_agent import ProfileAgent
        pa = ProfileAgent()
        assert hasattr(pa, '_profile_from_dict')

    def test_profile_dict_conversion(self):
        from backend.agents.profile_agent import ProfileAgent
        pa = ProfileAgent()
        test_data = {
            'session_id': 'test_session',
            'version': 3,
            'knowledge_level': '中级',
            'background': '有Python基础',
            'current_goal': '深入理解原理',
            'question_type': '概念理解',
            'domain_hint': json.dumps(['RAG', 'LangChain'], ensure_ascii=False),
            'complexity_estimate': '跨领域',
            'intent_type': 'generation',
            'domain_confidence': json.dumps({'RAG': 'high', 'LangChain': 'low'}, ensure_ascii=False),
        }
        profile = pa._profile_from_dict(test_data)
        assert profile is not None
        assert profile.knowledge_level.value == '中级'
        assert profile.background.value == '有Python基础'
        assert profile.version == 3
        assert profile.domain_hint == ['RAG', 'LangChain']

    def test_profile_dict_invalid(self):
        from backend.agents.profile_agent import ProfileAgent
        pa = ProfileAgent()
        result = pa._profile_from_dict({'knowledge_level': 'INVALID', 'background': '文科'})
        assert result is None

    def test_generate_profile_cache(self):
        from backend.agents.profile_agent import ProfileAgent
        source = inspect.getsource(ProfileAgent.generate_profile)
        assert '画像缓存' in source
        assert '_profile_from_dict' in source


class TestGap10CodeChecker:
    """GAP-10: 代码可执行性检查"""

    def test_safe_code(self):
        from backend.services.code_checker import check_code_safety
        safe, _ = check_code_safety('x = 1 + 2\nprint(x)')
        assert safe is True

    def test_syntax_error(self):
        from backend.services.code_checker import check_code_safety
        safe, msg = check_code_safety('def foo(\n')
        assert safe is False
        assert '语法错误' in msg

    def test_dangerous_eval(self):
        from backend.services.code_checker import check_code_safety
        safe, msg = check_code_safety('result = eval("1+1")')
        assert safe is False
        assert 'eval' in msg

    def test_dangerous_os_system(self):
        from backend.services.code_checker import check_code_safety
        safe, msg = check_code_safety('import os\nos.system("ls")')
        assert safe is False

    def test_dangerous_subprocess(self):
        from backend.services.code_checker import check_code_safety
        safe, msg = check_code_safety('import subprocess\nsubprocess.run(["ls"])')
        assert safe is False

    def test_empty_code(self):
        from backend.services.code_checker import check_code_safety
        safe, _ = check_code_safety('')
        assert safe is True

    def test_focused_output_none(self):
        from backend.services.code_checker import check_focused_output_code
        assert check_focused_output_code(None) is None

    def test_valid_ml_code(self):
        from backend.services.code_checker import check_code_safety
        safe, msg = check_code_safety(
            'import torch\n'
            'import numpy as np\n'
            'model = torch.nn.Linear(10, 5)\n'
            'x = torch.randn(3, 10)\n'
            'output = model(x)\n'
            'print(output.shape)\n'
        )
        assert safe is True, f'Valid ML code should pass: {msg}'

    def test_open_dangerous(self):
        from backend.services.code_checker import check_code_safety
        safe, msg = check_code_safety('f = open("data.txt", "r")')
        assert safe is False
        assert 'open' in msg

    def test_resource_agent_integrates_code_checker(self):
        from backend.agents.resource_agent import ResourceAgent
        source = inspect.getsource(ResourceAgent.generate_resource_package)
        assert 'check_code_in_markdown' in source
        assert 'lecture_warning' in source or 'code_warning' in source

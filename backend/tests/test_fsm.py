"""FSM编排器状态转移逻辑测试

对应方案书 7.5 节单元测试策略 - 测试用例1：
  FSM编排器状态转移逻辑
"""

import pytest

from backend.core.fsm import FSMState, can_transition, get_valid_transitions


class TestFSMStates:
    """FSM状态定义测试"""

    def test_all_states_defined(self):
        """验证所有状态都已定义"""
        expected_states = [
            "IDLE", "PROFILING", "DISPATCHING", "GENERATING",
            "REVIEWING", "FOCUSING", "JUDGING", "FORMATTING", "COMPLETE",
            "REVISING", "ERROR",
            "QUIZ_EVAL", "REDIMENSION", "ADVANCE", "RECHECK", "HEURISTIC_FOLLOWUP",
        ]
        actual_states = [s.value for s in FSMState]
        for state in expected_states:
            assert state in actual_states, f"缺少状态: {state}"

    def test_main_flow_transitions(self):
        """测试主流程状态转移"""
        assert can_transition(FSMState.IDLE, FSMState.PROFILING)
        assert can_transition(FSMState.PROFILING, FSMState.DISPATCHING)
        assert can_transition(FSMState.DISPATCHING, FSMState.GENERATING)
        assert can_transition(FSMState.GENERATING, FSMState.REVIEWING)
        assert can_transition(FSMState.REVIEWING, FSMState.FOCUSING)
        assert can_transition(FSMState.FOCUSING, FSMState.JUDGING)
        assert can_transition(FSMState.JUDGING, FSMState.FORMATTING)
        assert can_transition(FSMState.FORMATTING, FSMState.COMPLETE)

    def test_revision_flow(self):
        """测试退回修改流程"""
        # JUDGING → REVISING
        assert can_transition(FSMState.JUDGING, FSMState.REVISING)
        # REVISING → JUDGING
        assert can_transition(FSMState.REVISING, FSMState.JUDGING)

    def test_extension_flow(self):
        """测试延伸路径"""
        assert can_transition(FSMState.COMPLETE, FSMState.QUIZ_EVAL)
        assert can_transition(FSMState.QUIZ_EVAL, FSMState.REDIMENSION)
        assert can_transition(FSMState.QUIZ_EVAL, FSMState.ADVANCE)
        assert can_transition(FSMState.QUIZ_EVAL, FSMState.RECHECK)
        assert can_transition(FSMState.REDIMENSION, FSMState.HEURISTIC_FOLLOWUP)
        assert can_transition(FSMState.ADVANCE, FSMState.HEURISTIC_FOLLOWUP)

    def test_invalid_transitions(self):
        """测试非法状态转移"""
        assert not can_transition(FSMState.IDLE, FSMState.GENERATING)
        assert not can_transition(FSMState.PROFILING, FSMState.JUDGING)
        assert not can_transition(FSMState.GENERATING, FSMState.FORMATTING)

    def test_get_valid_transitions(self):
        """测试获取合法后续状态"""
        transitions = get_valid_transitions(FSMState.JUDGING)
        assert FSMState.FORMATTING in transitions
        assert FSMState.REVISING in transitions
        assert FSMState.ERROR in transitions

    def test_heuristic_followup_is_terminal(self):
        """HEURISTIC_FOLLOWUP是延伸路径终态"""
        transitions = get_valid_transitions(FSMState.HEURISTIC_FOLLOWUP)
        assert len(transitions) == 0

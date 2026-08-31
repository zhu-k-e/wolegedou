"""P0-3a 单元测试：FSM 编排器状态转移逻辑

对应方案书 6.1 节 + 7.5 节测试要求。
覆盖：
  - 主流程全链路
  - 退回修改（REVISING）
  - 延伸路径（REDIMENSION / ADVANCE / RECHECK / HEURISTIC_FOLLOWUP）
  - 非法转移拒绝
  - ERROR 异常状态
  - 终态判定
  - can_transition / get_valid_transitions 函数
"""

import pytest

from backend.core.fsm import (
    FSMState,
    MAIN_TRANSITIONS,
    EXTENSION_TRANSITIONS,
    can_transition,
    get_valid_transitions,
)


class TestMainFlowTransitions:
    """主流程状态转移"""

    def test_full_main_pipeline(self):
        """主流程全链路：IDLE → ... → COMPLETE"""
        path = [
            FSMState.IDLE,
            FSMState.PROFILING,
            FSMState.DISPATCHING,
            FSMState.GENERATING,
            FSMState.REVIEWING,
            FSMState.FOCUSING,
            FSMState.JUDGING,
            FSMState.FORMATTING,
            FSMState.COMPLETE,
        ]
        for i in range(len(path) - 1):
            assert can_transition(path[i], path[i + 1]), (
                f"主流程转移应合法: {path[i].value} → {path[i+1].value}"
            )

    def test_profiling_can_go_error(self):
        """PROFILING 可转 ERROR（异常路径）"""
        assert can_transition(FSMState.PROFILING, FSMState.ERROR)

    def test_each_main_state_can_go_error(self):
        """所有主流程状态都允许转 ERROR（异常逃生通道）"""
        main_states = [
            FSMState.PROFILING,
            FSMState.DISPATCHING,
            FSMState.GENERATING,
            FSMState.REVIEWING,
            FSMState.FOCUSING,
            FSMState.JUDGING,
            FSMState.FORMATTING,
        ]
        for s in main_states:
            assert can_transition(s, FSMState.ERROR), f"{s.value} 应能转 ERROR"


class TestRevisionFlow:
    """退回修改流程（方案书 6.1 异常状态 REVISING）"""

    def test_judging_to_revising(self):
        """JUDGING 可退回 REVISING"""
        assert can_transition(FSMState.JUDGING, FSMState.REVISING)

    def test_revising_back_to_judging(self):
        """REVISING 修改完回到 JUDGING 重审"""
        assert can_transition(FSMState.REVISING, FSMState.JUDGING)

    def test_revision_cycle_twice(self):
        """退回修改可循环 2 次（上限由 orchestrator 的 revision_count 控制）"""
        # FSM 层不限制次数，orchestrator 层用 fsm_max_revisions=2 限制
        for _ in range(2):
            assert can_transition(FSMState.JUDGING, FSMState.REVISING)
            assert can_transition(FSMState.REVISING, FSMState.JUDGING)

    def test_revising_cannot_skip_to_formatting(self):
        """REVISING 不能跳过 JUDGING 直接进 FORMATTING（必须重审）"""
        assert not can_transition(FSMState.REVISING, FSMState.FORMATTING)


class TestExtensionFlow:
    """延伸路径（方案书 6.1.2 节，从 COMPLETE 触发）"""

    def test_complete_to_quiz_eval(self):
        """COMPLETE 可触发 QUIZ_EVAL（延伸路径入口）"""
        assert can_transition(FSMState.COMPLETE, FSMState.QUIZ_EVAL)

    def test_quiz_eval_to_redimension(self):
        """QUIZ_EVAL → REDIMENSION（正确率<85%）"""
        assert can_transition(FSMState.QUIZ_EVAL, FSMState.REDIMENSION)

    def test_quiz_eval_to_advance(self):
        """QUIZ_EVAL → ADVANCE（正确率≥85%）"""
        assert can_transition(FSMState.QUIZ_EVAL, FSMState.ADVANCE)

    def test_quiz_eval_to_recheck(self):
        """QUIZ_EVAL → RECHECK（内容有误反馈）"""
        assert can_transition(FSMState.QUIZ_EVAL, FSMState.RECHECK)

    def test_redimension_to_followup(self):
        """REDIMENSION → HEURISTIC_FOLLOWUP"""
        assert can_transition(FSMState.REDIMENSION, FSMState.HEURISTIC_FOLLOWUP)

    def test_advance_to_followup(self):
        """ADVANCE → HEURISTIC_FOLLOWUP"""
        assert can_transition(FSMState.ADVANCE, FSMState.HEURISTIC_FOLLOWUP)

    def test_recheck_to_followup(self):
        """RECHECK 复检通过 → HEURISTIC_FOLLOWUP"""
        assert can_transition(FSMState.RECHECK, FSMState.HEURISTIC_FOLLOWUP)

    def test_recheck_to_redimension(self):
        """RECHECK 复检发现错误 → REDIMENSION"""
        assert can_transition(FSMState.RECHECK, FSMState.REDIMENSION)

    def test_heuristic_followup_is_terminal(self):
        """HEURISTIC_FOLLOWUP 是终态，无后续转移"""
        assert get_valid_transitions(FSMState.HEURISTIC_FOLLOWUP) == []

    def test_full_extension_path_redimension(self):
        """完整延伸路径：COMPLETE → QUIZ_EVAL → REDIMENSION → HEURISTIC_FOLLOWUP"""
        path = [
            FSMState.COMPLETE,
            FSMState.QUIZ_EVAL,
            FSMState.REDIMENSION,
            FSMState.HEURISTIC_FOLLOWUP,
        ]
        for i in range(len(path) - 1):
            assert can_transition(path[i], path[i + 1])


class TestInvalidTransitions:
    """非法转移应被拒绝"""

    @pytest.mark.parametrize("from_state, to_state", [
        (FSMState.IDLE, FSMState.GENERATING),       # 跳过 PROFILING
        (FSMState.IDLE, FSMState.COMPLETE),          # 跳过整个流程
        (FSMState.PROFILING, FSMState.COMPLETE),     # 跳过中间
        (FSMState.GENERATING, FSMState.PROFILING),   # 逆向
        (FSMState.REVISING, FSMState.COMPLETE),      # REVISING 必须重审
        (FSMState.COMPLETE, FSMState.PROFILING),     # COMPLETE 不能回 PROFILING
        (FSMState.HEURISTIC_FOLLOWUP, FSMState.QUIZ_EVAL),  # 终态不可转
        (FSMState.ERROR, FSMState.COMPLETE),         # ERROR 不可恢复到 COMPLETE
    ])
    def test_invalid_transition_rejected(self, from_state, to_state):
        assert not can_transition(from_state, to_state), (
            f"非法转移应被拒绝: {from_state.value} → {to_state.value}"
        )


class TestGetValidTransitions:
    """get_valid_transitions 函数"""

    def test_idle_only_profiling(self):
        """IDLE 只能转 PROFILING"""
        valid = get_valid_transitions(FSMState.IDLE)
        assert valid == [FSMState.PROFILING]

    def test_judging_has_options(self):
        """JUDGING 有多个合法后续（FORMATTING/REVISING/ERROR）"""
        valid = get_valid_transitions(FSMState.JUDGING)
        assert FSMState.FORMATTING in valid
        assert FSMState.REVISING in valid
        assert FSMState.ERROR in valid

    def test_complete_only_quiz_eval(self):
        """COMPLETE 只能转 QUIZ_EVAL（延伸入口）"""
        valid = get_valid_transitions(FSMState.COMPLETE)
        assert valid == [FSMState.QUIZ_EVAL]

    def test_terminal_state_empty(self):
        """终态 HEURISTIC_FOLLOWUP 无合法后续"""
        assert get_valid_transitions(FSMState.HEURISTIC_FOLLOWUP) == []

    def test_all_states_have_entry_in_transitions(self):
        """所有 FSMState 都能在转移表里查到（未定义的返回空列表）"""
        for state in FSMState:
            valid = get_valid_transitions(state)
            assert isinstance(valid, list)


class TestFSMStateEnum:
    """FSMState 枚举完整性"""

    def test_state_count(self):
        """方案书 6.1 节：16 个状态（9 主流程 + 2 异常 + 5 延伸）"""
        assert len(FSMState) == 16

    def test_state_is_string_enum(self):
        """FSMState 值为字符串（便于 JSON 序列化给前端）"""
        for state in FSMState:
            assert isinstance(state.value, str)

    def test_state_value_equals_name(self):
        """状态枚举值与名称一致（前端展示用）"""
        for state in FSMState:
            assert state.value == state.name

    def test_all_states_defined(self):
        """验证 16 个状态全部定义"""
        expected = {
            "IDLE", "PROFILING", "DISPATCHING", "GENERATING",
            "REVIEWING", "FOCUSING", "JUDGING", "FORMATTING", "COMPLETE",
            "REVISING", "ERROR",
            "QUIZ_EVAL", "REDIMENSION", "ADVANCE", "RECHECK", "HEURISTIC_FOLLOWUP",
        }
        actual = {s.value for s in FSMState}
        assert actual == expected


class TestTransitionTableConsistency:
    """转移表一致性校验"""

    def test_main_transitions_no_undefined_state(self):
        """MAIN_TRANSITIONS 里的状态都应在 FSMState 中"""
        for from_state in MAIN_TRANSITIONS:
            assert isinstance(from_state, FSMState)
            for to_state in MAIN_TRANSITIONS[from_state]:
                assert isinstance(to_state, FSMState)

    def test_extension_transitions_no_undefined_state(self):
        """EXTENSION_TRANSITIONS 里的状态都应在 FSMState 中"""
        for from_state in EXTENSION_TRANSITIONS:
            assert isinstance(from_state, FSMState)
            for to_state in EXTENSION_TRANSITIONS[from_state]:
                assert isinstance(to_state, FSMState)

    def test_no_duplicate_targets(self):
        """同一源状态的目标不应有重复（JUDGING 允许 FORMATTING 出现两次是已知设计，单独豁免）"""
        for from_state, targets in MAIN_TRANSITIONS.items():
            if from_state == FSMState.JUDGING:
                continue  # JUDGING 有两个 FORMATTING（通过 + 低置信度强制通过），设计如此
            assert len(targets) == len(set(targets)), (
                f"{from_state.value} 的目标有重复: {targets}"
            )

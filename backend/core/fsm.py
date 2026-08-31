"""FSM状态机 - 状态定义与转移规则

对应方案书 6.1.1 节 FSM状态定义

主FSM：
  IDLE → PROFILING → DISPATCHING → GENERATING → REVIEWING
  → FOCUSING → JUDGING → FORMATTING → COMPLETE

异常状态：
  REVISING（Agent修改后回到JUDGING重审，上限2次）
  ERROR（任何阶段出错）

延伸路径（从COMPLETE触发，可选）：
  QUIZ_EVAL → REDIMENSION / ADVANCE / RECHECK → HEURISTIC_FOLLOWUP
"""

from enum import Enum


class FSMState(str, Enum):
    """FSM状态枚举"""

    # 主流程
    IDLE = "IDLE"
    PROFILING = "PROFILING"
    DISPATCHING = "DISPATCHING"
    GENERATING = "GENERATING"
    REVIEWING = "REVIEWING"
    FOCUSING = "FOCUSING"
    JUDGING = "JUDGING"
    FORMATTING = "FORMATTING"
    COMPLETE = "COMPLETE"

    # 异常状态
    REVISING = "REVISING"
    ERROR = "ERROR"

    # 延伸路径
    QUIZ_EVAL = "QUIZ_EVAL"
    REDIMENSION = "REDIMENSION"
    ADVANCE = "ADVANCE"
    RECHECK = "RECHECK"
    HEURISTIC_FOLLOWUP = "HEURISTIC_FOLLOWUP"


# ============================================================
# 状态转移规则
# ============================================================

# 主流程转移
MAIN_TRANSITIONS = {
    FSMState.IDLE: [FSMState.PROFILING],
    FSMState.PROFILING: [FSMState.DISPATCHING, FSMState.ERROR],
    FSMState.DISPATCHING: [FSMState.GENERATING, FSMState.ERROR],
    FSMState.GENERATING: [FSMState.REVIEWING, FSMState.ERROR],
    FSMState.REVIEWING: [FSMState.FOCUSING, FSMState.ERROR],
    FSMState.FOCUSING: [FSMState.JUDGING, FSMState.ERROR],
    FSMState.JUDGING: [
        FSMState.FORMATTING,   # 通过
        FSMState.REVISING,     # 退回修改
        FSMState.FORMATTING,   # 低置信度强制通过
        FSMState.ERROR,
    ],
    FSMState.REVISING: [FSMState.JUDGING],
    FSMState.FORMATTING: [FSMState.COMPLETE, FSMState.ERROR],
    FSMState.COMPLETE: [FSMState.QUIZ_EVAL],  # 延伸路径入口
}

# 延伸路径转移
EXTENSION_TRANSITIONS = {
    FSMState.QUIZ_EVAL: [
        FSMState.REDIMENSION,   # 正确率<85%
        FSMState.ADVANCE,       # 正确率≥85%
        FSMState.RECHECK,       # 内容有误反馈
        FSMState.HEURISTIC_FOLLOWUP,
    ],
    FSMState.REDIMENSION: [FSMState.HEURISTIC_FOLLOWUP],
    FSMState.ADVANCE: [FSMState.HEURISTIC_FOLLOWUP],
    FSMState.RECHECK: [
        FSMState.REDIMENSION,   # 复检发现错误
        FSMState.HEURISTIC_FOLLOWUP,  # 复检通过
    ],
    FSMState.HEURISTIC_FOLLOWUP: [],  # 终态，学生回答可触发新一轮PROFILING
}


def can_transition(from_state: FSMState, to_state: FSMState) -> bool:
    """检查状态转移是否合法"""
    allowed = MAIN_TRANSITIONS.get(from_state, []) + EXTENSION_TRANSITIONS.get(from_state, [])
    return to_state in allowed


def get_valid_transitions(state: FSMState) -> list[FSMState]:
    """获取某状态的合法后续状态"""
    return MAIN_TRANSITIONS.get(state, []) + EXTENSION_TRANSITIONS.get(state, [])

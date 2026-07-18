"""自定义异常"""


class OrchestratorError(Exception):
    """编排器基础异常"""


class FSMTransitionError(OrchestratorError):
    """FSM状态转移异常"""
    def __init__(self, current_state: str, target_state: str, reason: str = ""):
        self.current_state = current_state
        self.target_state = target_state
        super().__init__(f"FSM状态转移失败: {current_state} -> {target_state}. {reason}")


class LLMCallError(OrchestratorError):
    """LLM调用异常"""


class SchemaValidationError(OrchestratorError):
    """Schema校验异常"""
    def __init__(self, schema_name: str, detail: str = ""):
        self.schema_name = schema_name
        super().__init__(f"Schema校验失败 [{schema_name}]: {detail}")


class KnowledgeBaseError(OrchestratorError):
    """知识库异常"""


class AgentNotFoundError(OrchestratorError):
    """Agent未找到"""
    def __init__(self, agent_id: str):
        self.agent_id = agent_id
        super().__init__(f"Agent未找到: {agent_id}")

"""Domain errors for the Agent concept."""


class AgentNotFoundError(Exception):
    def __init__(self, agent_id: str) -> None:
        super().__init__(f"Agent not found: {agent_id}")
        self.agent_id = agent_id


class AgentNameConflictError(Exception):
    def __init__(self, name: str) -> None:
        super().__init__(f"Agent with name already exists: {name}")
        self.name = name


class AgentNoDefaultPromptError(Exception):
    def __init__(self, agent_id: str) -> None:
        super().__init__(f"Agent has no default_prompt to reset from: {agent_id}")
        self.agent_id = agent_id

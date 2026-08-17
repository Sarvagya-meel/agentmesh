from agentmesh.agents.agent_langgraph_copilot.factory import create_langgraph_worker_agent
from agentmesh.agents.common.runtime import create_agent_runtime_app, worker_enabled_from_env

app = create_agent_runtime_app(
    kind="langgraph",
    factory=create_langgraph_worker_agent,
    worker_enabled=worker_enabled_from_env(),
)

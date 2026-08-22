from agentmesh.agents.agent_langgraph_copilot.factory import create_langgraph_worker_agent
from agentmesh.agents.common.runtime import create_agent_runtime_app

app = create_agent_runtime_app(
    kind="langgraph",
    factory=create_langgraph_worker_agent,
)

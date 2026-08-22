from agentmesh.agents.agent_adk_spark.factory import create_google_adk_worker_agent
from agentmesh.agents.common.runtime import create_agent_runtime_app

app = create_agent_runtime_app(
    kind="google-adk",
    factory=create_google_adk_worker_agent,
)

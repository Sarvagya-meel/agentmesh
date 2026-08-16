from agentmesh.agents.adk_spark.factory import create_google_adk_worker_agent
from agentmesh.agents.common.runtime import create_agent_runtime_app, worker_enabled_from_env

app = create_agent_runtime_app(
    kind="google-adk",
    factory=create_google_adk_worker_agent,
    worker_enabled=worker_enabled_from_env(),
)

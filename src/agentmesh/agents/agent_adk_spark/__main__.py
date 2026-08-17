from agentmesh.agents.agent_adk_spark.factory import create_google_adk_worker_agent
from agentmesh.agents.common.cli import run_agent_cli


def main() -> None:
    run_agent_cli(
        create_google_adk_worker_agent,
        description="Run the AgentMesh Google ADK LLM agent standalone or as a worker.",
    )


if __name__ == "__main__":
    main()

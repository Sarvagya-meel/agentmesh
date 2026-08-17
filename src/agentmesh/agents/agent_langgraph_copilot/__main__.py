from agentmesh.agents.agent_langgraph_copilot.factory import create_langgraph_worker_agent
from agentmesh.agents.common.cli import run_agent_cli


def main() -> None:
    run_agent_cli(
        create_langgraph_worker_agent,
        description="Run the AgentMesh LangGraph LLM agent standalone or as a worker.",
    )


if __name__ == "__main__":
    main()

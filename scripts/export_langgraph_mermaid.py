from __future__ import annotations

import argparse
from pathlib import Path

from agentmesh.agents.agent_langgraph_copilot.agent import ConversationAgent
from agentmesh.agents.agent_langgraph_orchestrator_supervisor import (
    MasterOrchestratorAgent,
)
from agentmesh.core.database import InMemoryEventRepository
from agentmesh.services.service_agentmesh_server.events.service import EventService
from agentmesh.services.service_agentmesh_server.events.state import StateService
from agentmesh.services.service_agentmesh_server.registry.repository import (
    InMemoryRegistryRepository,
)
from agentmesh.services.service_agentmesh_server.registry.service import RegistryService


def main() -> int:
    parser = argparse.ArgumentParser(description="Export offline LangGraph diagrams.")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Fail when committed graph exports differ from the current graphs.",
    )
    args = parser.parse_args()
    output_dir = Path(__file__).resolve().parents[1] / "docs" / "graphs"
    if not args.check:
        output_dir.mkdir(parents=True, exist_ok=True)
    else:
        # In check mode, ensure directory exists
        output_dir.mkdir(parents=True, exist_ok=True)

    copilot = ConversationAgent(auto_register=False)
    event_service = EventService(InMemoryEventRepository())
    supervisor = MasterOrchestratorAgent(
        registry_service=RegistryService(InMemoryRegistryRepository()),
        event_service=event_service,
        state_service=StateService(event_service),
    )
    diagrams = {
        "langgraph-copilot.mmd": copilot.graph_mermaid(),
        "orchestrator-supervisor.mmd": supervisor.graph_mermaid(),
    }
    stale_files: list[str] = []
    for file_name, source in diagrams.items():
        expected = source + "\n"
        output_path = output_dir / file_name
        if args.check:
            if not output_path.exists() or output_path.read_text(encoding="ascii") != expected:
                stale_files.append(file_name)
            continue
        output_path.write_text(expected, encoding="ascii")
        print(f"exported {file_name}")
    if stale_files:
        print("stale graph exports: " + ", ".join(stale_files))
        return 1
    if args.check:
        print("graph exports are current")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

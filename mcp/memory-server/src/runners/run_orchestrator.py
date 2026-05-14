# Phase 7/9: Provides an independent executable entrypoint for the Orchestrator.
# When implemented, this will:
#   1. Load config from environment
#   2. Instantiate MCPClient pointing at the running MCP server
#   3. Instantiate OrchestratorService with the MCPClient
#   4. Run the orchestrator decision loop for a given workflow_id
# Usage (future): python -m src.runners.run_orchestrator --workflow-id <uuid>

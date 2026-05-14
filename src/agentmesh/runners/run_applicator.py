# Phase 8/9: Provides an independent executable entrypoint for ApplicationAgent.
# When implemented, this will:
#   1. Load config from environment
#   2. Instantiate MCPClient pointing at the running MCP server
#   3. Instantiate ApplicationAgent with the MCPClient and injected tools
#   4. Run the agent polling loop for a given workflow_id
# Usage (future): python -m agentmesh.runners.run_applicator --workflow-id <uuid>

# Phase 13: AgentCore Runtime adapter — optional agent worker deployment
# Implements RuntimeAdapter interface. Only active when AWS_AGENTCORE_ENABLED=true.
# Hosted agents still communicate with AgentMesh MCP via clients/mcp_client.py.
# AgentCore does not replace MCP as the event store.

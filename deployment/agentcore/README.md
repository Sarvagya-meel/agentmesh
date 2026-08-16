# AgentCore Deployment

This directory is reserved for a future AWS AgentCore deployment adapter.

Agent logic and request contracts stay inside `src/agentmesh`, so adding AgentCore should
introduce deployment wrappers and configuration here without changing the agents' core code.
The local Docker runtime remains the reference implementation until that adapter is added.

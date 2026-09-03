# AgentCore Deployment

This directory is reserved for a future AWS AgentCore deployment adapter.

Agent logic and request contracts stay inside `src/agentmesh`, so adding AgentCore should
introduce deployment wrappers and configuration here without changing the agents' core code.
The local Docker runtime remains the reference implementation until that adapter is added.

## Portability Contract

An AgentCore adapter should preserve the same worker contract used locally: a
synchronous `/invoke` receives an immutable per-step input manifest and the adapter
returns a structured result to the control plane. Agent code must not import Docker,
Compose, Streamlit, supervisor, or AgentCore lifecycle APIs. Environment-backed
provider configuration, stable thread/workflow IDs, JSON-safe results, and
externally managed PostgreSQL remain the boundary.

The durable control plane remains responsible for registry data, queueing, leased
dispatch, retries, DAG state, deterministic validation, events, and LangGraph
checkpoint mappings. LiteLLM Gateway is required for supervisor model calls only,
not as an AgentCore worker dependency.

The selective agent image is also built for `linux/arm64` as an early portability
check. AgentCore-specific request translation, identity, session mapping, and managed
observability belong in this deployment folder, not in the concrete agent package.

Before exposing an adapter publicly, add authentication, scoped service identity,
secret-manager integration, network policy, and provider-specific load/recovery tests.

# Phase 6/8: Provides the MCP API client used by independent agents and workers.
# This client wraps the MCP HTTP API (FastAPI service) so agents running as
# separate processes can append events, query events, and get workflow state
# without importing the service layer directly.
# Implementation will use httpx.AsyncClient with retry and backoff logic.

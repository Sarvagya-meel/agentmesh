#!/usr/bin/env bash
# Start services in order: registry -> streamlit -> agent
# Usage: ./scripts/start_registry_streamlit_agent.sh

set -euo pipefail
REPO_ROOT="$(pwd)"
COMPOSE_FILE="deployment/docker/compose.yml"
WAIT_INTERVAL=2

echo "Starting registry (orchestrator-supervisor-agent)..."
docker compose -f "$COMPOSE_FILE" up -d orchestrator-supervisor-agent

echo "Waiting for registry health at http://127.0.0.1:8000/health ..."
until curl -sSf http://127.0.0.1:8000/health >/dev/null 2>&1; do
  echo "waiting for registry..."
  sleep $WAIT_INTERVAL
done

echo "Registry is healthy."

echo "Starting Streamlit (no-deps)..."
docker compose -f "$COMPOSE_FILE" up -d --no-deps streamlit

echo "Waiting for Streamlit at http://127.0.0.1:8501 ..."
until curl -sSf http://127.0.0.1:8501 >/dev/null 2>&1; do
  echo "waiting for streamlit..."
  sleep $WAIT_INTERVAL
done

echo "Streamlit appears available at http://127.0.0.1:8501"

echo "Starting agent: agent-langgraph-copilot ..."
docker compose -f "$COMPOSE_FILE" up -d agent-langgraph-copilot

echo "Waiting for agent health at http://127.0.0.1:8101/health ..."
until curl -sSf http://127.0.0.1:8101/health >/dev/null 2>&1; do
  echo "waiting for agent..."
  sleep $WAIT_INTERVAL
done

echo "Agent is healthy. All requested services started."
